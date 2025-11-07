import ast
from dataclasses import dataclass
from typing import Literal

from flat.py.diagnostics import Issuer, Level, Range, Location, Diagnostic
from flat.py.ast_helpers import mk_call_runtime, mk_name, get_range

class Type:
    """Type at compile time."""

    @property
    def ast(self) -> ast.expr:
        """The AST representation of this type."""
        raise NotImplementedError()

@dataclass
class AnyType(Type):
    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('AnyType')
    
@dataclass
class TypeName(Type):
    id: str

    @property
    def ast(self) -> ast.expr:
        return mk_name(self.id)

@dataclass
class LangType(Type):
    grammar: str
    key: str

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('LangType', mk_name(self.grammar), ast.Constant(self.key))

@dataclass
class RefinedType(Type):
    base: Type
    predicate: ast.expr

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('RefinedType', self.base.ast, self.predicate)

type LiteralValue = ast._ConstantValue

@dataclass
class LiteralType(Type):
    values: list[LiteralValue]

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('LiteralType', ast.List([ast.Constant(v) for v in self.values], ctx=ast.Load()))

none_type = LiteralType([None])

@dataclass
class UnionType(Type):
    options: list[Type]

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('UnionType', ast.List([t.ast for t in self.options], ctx=ast.Load()))

@dataclass
class TupleType(Type):
    elements: list[Type]
    variant: bool = False

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('TupleType', ast.List([t.ast for t in self.elements], ctx=ast.Load()))
    
@dataclass
class ListType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('ListType', self.element.ast)
    
@dataclass
class SetType(Type):
    element: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('SetType', self.element.ast)
    
@dataclass
class DictType(Type):
    key: Type
    value: Type

    @property
    def ast(self) -> ast.expr:
        return mk_call_runtime('DictType', self.key.ast, self.value.ast)


class Contract:
    pass

@dataclass
class PreCond(Contract):
    predicate: ast.expr

@dataclass
class PostCond(Contract):
    predicate: ast.expr

@dataclass
class ExcSpec(Contract):
    exception: ast.expr
    when: ast.expr


@dataclass
class Def:
    """Definition at semantic level."""
    pass

@dataclass
class VarDef(Def):
    """Variable definition."""
    typ: Type

@dataclass
class ArgDef(VarDef):
    """Function argument definition."""
    kind: Literal['arg', 'vararg', 'kwarg']
    default: ast.expr | None

@dataclass
class TypeDef(Def):
    """Type definition/alias."""
    expansion: Type

@dataclass
class TypeConstrDef(Def):
    """Type constructor definition."""
    id: str

@dataclass
class FunDef(Def):
    args: list[str]
    return_type: Type
    contracts: list[Contract]

class UnknownDef(Def):
    pass


@dataclass
class Scope:
    owner: FunDef | None
    _defs: dict[str, Def]
    _next_fresh: int = 1

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

    def __init__(self, file_path: str, issuer: Issuer, defs: dict[str, Def] = {}) -> None:
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

    def lookup_nonlocal(self, key: str) -> Def | None:
        for scope in reversed(self._local_scopes[:-1]):
            if key in scope:
                return scope[key]

        return None
    
    def create_global_var(self, key: str) -> None:
        var_def = VarDef(AnyType())
        self._global_scope[key] = var_def

    def push(self, owner: FunDef, defs: dict[str, Def] = {}) -> None:
        scope = Scope(owner, defs)
        self._local_scopes.append(scope)

    def pop(self) -> None:
        assert len(self._local_scopes) > 0, "No local level to pop"
        self._local_scopes.pop()

    def report(self, level: Level, msg: str, at: Range | ast.AST) -> None:
        range = at if isinstance(at, Range) else get_range(at)
        self.issuer.report(Diagnostic(level, msg, Location(self.file_path, range)))
    
    def error(self, msg: str, at: Range | ast.AST) -> None:
        return self.report(Level.ERROR, msg, at)

    def warn(self, msg: str, at: Range | ast.AST) -> None:
        return self.report(Level.WARN, msg, at)
