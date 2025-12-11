import ast
from dataclasses import dataclass
from types import EllipsisType
from typing import Literal, Mapping, Sequence

from flat.backend.lang import Lang
from flat.py.ast_helpers import mk_call_rt, mk_call
from flat.py.diagnostics import Issuer, Location, Diagnostic, Position, Range

__all__ = ['Type', 'AnyType', 'TypeName', 'LangType', 'RefinedType', 'LitType', 'none_type', 'UnionType',
           'TupleType', 'SeqType', 'ListType', 'SetType', 'DictType', 'ClassType',
           'Contract', 'Require', 'Ensure',
           'Def', 'AnnDef', 'TypeDef', 'TypeConstrDef', 'VarDef', 'ArgDef', 'FunDef', 'UnknownDef',
           'Scope', 'Context']


class Type:
    """(Compile-time) Type."""

    @property
    def ast(self) -> ast.expr:
        """The AST representation of this type."""
        raise NotImplementedError()


@dataclass
class AnyType(Type):
    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('AnyType')


@dataclass
class TypeName(Type):
    """Builtin-type, or type alias reference."""
    name: str

    @property
    def ast(self) -> ast.expr:
        return mk_call('rt.BuiltinType', ast.Name(self.name))


@dataclass
class LangType(Type):
    lang: Lang

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('LangType')


@dataclass
class RefinedType(Type):
    base: Type
    predicate: ast.expr

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('RefinedType', self.base.ast, self.predicate)


type LitValue = str | bytes | bool | int | float | complex | None | EllipsisType


@dataclass
class LitType(Type):
    values: Sequence[LitValue]

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('LitType', ast.List([ast.Constant(v) for v in self.values]))


none_type = LitType([None])


@dataclass
class UnionType(Type):
    options: Sequence[Type]

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('UnionType', ast.List([t.ast for t in self.options]))


@dataclass
class TupleType(Type):
    elements: Sequence[Type]
    variant: bool = False

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('TupleType', ast.List([t.ast for t in self.elements]))


@dataclass
class SeqType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('SeqType', self.element.ast)


@dataclass
class ListType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('ListType', self.element.ast)


@dataclass
class SetType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('SetType', self.element.ast)


@dataclass
class DictType(Type):
    key: Type
    value: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('DictType', self.key.ast, self.value.ast)


@dataclass
class ClassType(Type):
    id: str
    fields: dict[str, Type]

    @property
    def ast(self) -> ast.expr:
        return mk_call_rt('ClassType', ast.Constant(self.id),
                          ast.Dict([ast.Constant(k) for k in self.fields.keys()],
                                   [v.ast for v in self.fields.values()]))


class Contract:
    pass


@dataclass
class Require(Contract):
    cond: ast.expr  # bind to function args
    cond_tree: ast.expr


@dataclass
class Ensure(Contract):
    cond: ast.expr  # bind to function args and '_' (for the return value)
    cond_tree: ast.expr


@dataclass
class Def:
    """Definition at semantic level."""
    pass


@dataclass
class AnnDef(Def):
    """FLAT annotation."""
    qual_name: str


@dataclass
class TypeDef(Def):
    """Type definition/alias."""
    expansion: Type


@dataclass
class TypeConstrDef(Def):
    """Type constructor definition."""
    id: str


@dataclass
class VarDef(Def):
    """Variable definition."""
    typ: Type


@dataclass
class ArgDef(VarDef):
    """Function argument definition."""
    kind: Literal['posonly', 'normal', '*', 'kwonly', '**']
    default: ast.expr | None


@dataclass
class FunDef(Def):
    args: Sequence[str]
    return_type: Type
    contracts: Sequence[Contract]


class UnknownDef(Def):
    pass


class Scope:
    owner: FunDef | None
    _defs: dict[str, Def]
    _next_fresh: int

    def __init__(self, owner: FunDef | None, defs: Mapping[str, Def] = {}) -> None:
        self.owner = owner
        self._defs = {}
        self._defs.update(defs)
        self._next_fresh = 1

    def __contains__(self, key: str) -> bool:
        return key in self._defs

    def __getitem__(self, key: str) -> Def:
        return self._defs[key]

    def __setitem__(self, key: str, value: Def) -> None:
        self._defs[key] = value

    def get(self, key: str) -> Def | None:
        return self._defs.get(key)

    def fresh(self) -> str:
        key = f"__fresh_{self._next_fresh}__"
        self._next_fresh += 1
        return key


class Context:
    file_path: str
    issuer: Issuer
    _global_scope: Scope
    _local_scopes: list[Scope]

    def __init__(self, file_path: str, issuer: Issuer, defs: Mapping[str, Def] = {}) -> None:
        self.file_path = file_path
        self.issuer = issuer
        self._global_scope = Scope(None, defs)
        self._local_scopes = []

    def __contains__(self, key: str) -> bool:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        return key in scope

    def __getitem__(self, key: str) -> Def:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        return scope[key]

    def __setitem__(self, key: str, value: Def) -> None:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        scope[key] = value

    def get(self, key: str) -> Def | None:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        return scope.get(key)

    def fresh(self) -> str:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        return scope.fresh()

    def owner(self) -> FunDef | None:
        scope = self._local_scopes[-1] if len(self._local_scopes) > 0 else self._global_scope
        return scope.owner

    def lookup(self, key: str) -> Def | None:
        for scope in reversed(self._local_scopes):
            if key in scope:
                return scope[key]

        return self._global_scope.get(key)

    def lookup_global(self, key: str) -> Def | None:
        return self._global_scope.get(key)

    def create_global_var(self, key: str) -> None:
        var_def = VarDef(AnyType())
        self._global_scope[key] = var_def

    def lookup_nonlocal(self, key: str) -> Def | None:
        for scope in reversed(self._local_scopes[:-1]):
            if key in scope:
                return scope[key]

        return None

    def push(self, owner: FunDef, defs: Mapping[str, Def] = {}) -> None:
        scope = Scope(owner, defs)
        self._local_scopes.append(scope)

    def pop(self) -> None:
        assert len(self._local_scopes) > 0, "No local level to pop"
        self._local_scopes.pop()

    def issue(self, diagnostic: Diagnostic) -> None:
        self.issuer.issue(diagnostic)

    def get_loc(self, node: ast.AST) -> Location:
        if hasattr(node, 'lineno') and hasattr(node, 'col_offset'):
            start = Position(node.lineno, node.col_offset + 1)
            if hasattr(node, 'end_lineno') and hasattr(node, 'end_col_offset'):
                end = Position(node.end_lineno, node.end_col_offset + 1)
            else:
                end = start
            return Location(self.file_path, Range(start, end))

        raise ValueError("AST node does not have position information.")
