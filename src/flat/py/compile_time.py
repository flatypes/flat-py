import ast
import sys
from abc import abstractmethod, ABC
from dataclasses import dataclass
from enum import Enum
from types import EllipsisType
from typing import Literal, Mapping, Sequence, Any

from flat.backend.lang import Lang
from flat.py.ast_helpers import mk_call
from flat.py.shared import Range, print_details

__all__ = ['Type', 'AnyType', 'TypeName', 'LangType', 'RefinedType',
           'LitValue', 'LitType', 'none_type', 'UnionType', 'TupleType', 'ListType',
           'SetType', 'DictType', 'ClassType', 'Contract', 'Require', 'Ensure',
           'Def', 'AnnDef', 'TypeDef', 'TypeConstrDef', 'VarDef', 'ArgDef',
           'FunDef', 'UnknownDef', 'Scope', 'Context',
           'Diagnostic', 'Level', 'Issuer',
           'InvalidSyntax', 'UndefinedRule', 'RedefinedRule', 'NoStartRule',
           'EmptyRange', 'ArityMismatch', 'UndefinedName', 'RedefinedName',
           'InvalidType', 'InvalidLitValue', 'InvalidFormat', 'UndefinedNonlocal',
           'NotAssignable', 'UnsupportedFeature']


class Type(ABC):
    """(Compile-time) Type."""

    @abstractmethod
    def to_runtime(self, rt: str) -> ast.expr:
        """Convert to runtime type."""
        raise NotImplementedError()


@dataclass(frozen=True)
class AnyType(Type):
    """Do-not-care type."""

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.AnyType')


@dataclass(frozen=True)
class TypeName(Type):
    """Builtin-type, or type alias reference."""
    name: str

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.BuiltinType', ast.Name(self.name))


@dataclass(frozen=True)
class LangType(Type):
    lang: Lang

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.LangType')


@dataclass(frozen=True)
class RefinedType(Type):
    base: Type
    predicate: ast.expr

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.RefinedType', self.base.to_runtime(rt), self.predicate)


type LitValue = str | bytes | bool | int | float | complex | None | EllipsisType


@dataclass(frozen=True)
class LitType(Type):
    values: Sequence[LitValue]

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.LitType', ast.List([ast.Constant(v) for v in self.values]))


none_type = LitType([None])


@dataclass(frozen=True)
class UnionType(Type):
    options: Sequence[Type]

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.UnionType', ast.List([t.to_runtime(rt) for t in self.options]))


@dataclass(frozen=True)
class TupleType(Type):
    elements: Sequence[Type]
    variant: bool = False

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.TupleType', ast.List([t.to_runtime(rt) for t in self.elements]))


@dataclass(frozen=True)
class ListType(Type):
    element: Type

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.ListType', self.element.to_runtime(rt))


@dataclass(frozen=True)
class SetType(Type):
    element: Type

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.SetType', self.element.to_runtime(rt))


@dataclass(frozen=True)
class DictType(Type):
    key: Type
    value: Type

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.DictType', self.key.to_runtime(rt), self.value.to_runtime(rt))


@dataclass(frozen=True)
class ClassType(Type):
    id: str
    fields: dict[str, Type]

    def to_runtime(self, rt: str) -> ast.expr:
        return mk_call(f'{rt}.ClassType', ast.Constant(self.id),
                       ast.Dict([ast.Constant(k) for k in self.fields.keys()],
                                [v.to_runtime(rt) for v in self.fields.values()]))


class Contract(ABC):
    pass


@dataclass(frozen=True)
class Require(Contract):
    cond: ast.expr  # bind to function args
    cond_tree: ast.expr


@dataclass(frozen=True)
class Ensure(Contract):
    cond: ast.expr  # bind to function args and '_' (for the return value)
    cond_tree: ast.expr


@dataclass(frozen=True)
class Def:
    """Definition at semantic level."""
    pass


@dataclass(frozen=True)
class AnnDef(Def):
    """FLAT annotation."""
    qual_name: str


@dataclass(frozen=True)
class TypeDef(Def):
    """Type definition/alias."""
    expansion: Type


@dataclass(frozen=True)
class TypeConstrDef(Def):
    """Type constructor definition."""
    id: str


@dataclass(frozen=True)
class VarDef(Def):
    """Variable definition."""
    typ: Type


@dataclass(frozen=True)
class ArgDef(VarDef):
    """Function argument definition."""
    kind: Literal['posonly', 'normal', '*', 'kwonly', '**']
    default: ast.expr | None


@dataclass(frozen=True)
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


class Level(Enum):
    """Diagnostic level."""
    ERROR = 1
    WARN = 2

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Diagnostic:
    file_path: str
    pos: Range
    summary: str
    detail: str = ''
    level: Level = Level.ERROR


class Issuer:
    """Diagnostic collector."""

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def issue(self, diagnostic: Diagnostic) -> None:
        """Add a diagnostic."""
        self._diagnostics.append(diagnostic)

    @property
    def has_diagnostics(self) -> bool:
        """Test if there are any diagnostics."""
        return len(self._diagnostics) > 0

    @property
    def has_errors(self) -> bool:
        """Test if there are any ERROR-level diagnostics."""
        return any(d.level == Level.ERROR for d in self._diagnostics)

    def get_diagnostics(self) -> Sequence[Diagnostic]:
        """Get all diagnostics."""
        return self._diagnostics

    def pretty(self) -> str:
        """Pretty-print all diagnostics."""
        lines = []
        for d in self._diagnostics:
            prefix = "ERROR" if d.level == Level.ERROR else "WARN"
            loc_str = f"{d.pos}" if d.pos else "<unknown location>"
            lines.append(f"{loc_str} - {prefix}: {d.summary}")
        return "\n".join(lines)

    def print(self) -> None:
        """Pretty-print all diagnostics."""
        for diagnostic in self._diagnostics:
            print(f"-- {diagnostic.level}: {diagnostic.summary}", file=sys.stderr)
            print_details(diagnostic.file_path, diagnostic.pos, [])


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

    @DeprecationWarning
    def get_loc(self, node: ast.AST) -> Any:
        raise NotImplementedError


# Instances of specific diagnostics:
class InvalidSyntax(Diagnostic):
    def __init__(self, detail: str, file_path: str, pos: Range) -> None:
        super().__init__(file_path, pos, "invalid syntax", detail)


class UndefinedRule(Diagnostic):
    def __init__(self, file_path: str, rule_pos: Range) -> None:
        super().__init__(file_path, rule_pos, "undefined rule")


class RedefinedRule(Diagnostic):
    def __init__(self, file_path: str, rule_pos: Range) -> None:
        super().__init__(file_path, rule_pos, "undefined rule")


class NoStartRule(Diagnostic):
    def __init__(self, file_path: str, grammar_pos: Range) -> None:
        super().__init__(file_path, grammar_pos, "no 'start' rule")


class EmptyRange(Diagnostic):
    def __init__(self, file_path: str, range_pos: Range) -> None:
        super().__init__(file_path, range_pos, "empty range", level=Level.WARN)


class ArityMismatch(Diagnostic):
    def __init__(self, expected: int | str, actual: int, file_path: str, fun_pos: Range) -> None:
        super().__init__(file_path, fun_pos, "arity mismatch", f"expected {expected} argument(s), but got {actual}")


class UndefinedName(Diagnostic):
    def __init__(self, file_path: str, name_pos: Range) -> None:
        super().__init__(file_path, name_pos, "undefined name")


class RedefinedName(Diagnostic):
    def __init__(self, file_path: str, name_pos: Range) -> None:
        super().__init__(file_path, name_pos, "redefined name")


class InvalidType(Diagnostic):
    def __init__(self, file_path: str, type_pos: Range) -> None:
        super().__init__(file_path, type_pos, "invalid type")


class InvalidLitValue(Diagnostic):
    def __init__(self, file_path: str, value_pos: Range) -> None:
        super().__init__(file_path, value_pos, "invalid literal value for 'typing.Literal'")


class InvalidFormat(Diagnostic):
    def __init__(self, file_path: str, format_pos: Range) -> None:
        super().__init__(file_path, format_pos, "invalid grammar format")


class UndefinedNonlocal(Diagnostic):
    def __init__(self, file_path: str, name_pos: Range) -> None:
        super().__init__(file_path, name_pos, "undefined nonlocal", "this is not defined in any enclosing scope")


class NotAssignable(Diagnostic):
    def __init__(self, file_path: str, target_pos: Range) -> None:
        super().__init__(file_path, target_pos, "not assignable", "cannot assign to this target")


class UnsupportedFeature(Diagnostic):
    def __init__(self, file_path: str, pos: Range) -> None:
        super().__init__(file_path, pos, "unsupported feature")
