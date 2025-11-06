from collections.abc import Callable
from dataclasses import dataclass


class Type:
    """Type at runtime."""
    def __contains__(self, value: object) -> bool:
        """Tests if the given `value` is a member of this type."""
        pass

@dataclass
class BaseType(Type):
    typ: type

    def __contains__(self, value: object) -> bool:
        return isinstance(value, self.typ)

@dataclass
class LangType(Type):
    pass

@dataclass
class RefinedType(Type):
    base: Type
    predicate: Callable[[object], bool]

    def __contains__(self, value: object) -> bool:
        return value in self.base and self.predicate(value)

@dataclass
class TupleType(Type):
    elems: list[Type]

    def __contains__(self, value: object) -> bool:
        match value:
            case tuple() as vs:
                return len(vs) == len(self.elems) and all(v in t for v, t in zip(vs, self.elems))
            case _:
                return False

@dataclass
class UnionType(Type):
    options: list[Type]

    def __contains__(self, value: object) -> bool:
        return any(value in t for t in self.options)

@dataclass
class ListType(Type):
    elem: Type

    def __contains__(self, value: object) -> bool:
        match value:
            case list() as vs:
                return all(v in self.elem for v in vs)
            case _:
                return False

@dataclass
class SetType(Type):
    elem: Type

    def __contains__(self, value: object) -> bool:
        match value:
            case set() as vs:
                return all(v in self.elem for v in vs)
            case _:
                return False

@dataclass
class DictType(Type):
    key: Type
    value: Type

    def __contains__(self, value: object) -> bool:
        match value:
            case dict() as d:
                return all(k in self.key and v in self.value for k, v in d.items())
            case _:
                return False

@dataclass
class NoneType(Type):
    def __contains__(self, value: object) -> bool:
        return value is None