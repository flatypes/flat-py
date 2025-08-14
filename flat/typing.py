from dataclasses import dataclass
from enum import Enum
from typing import Any

from flat.grammars import CFG


class Type:
    pass


class BuiltinType(Type, Enum):
    Int = 0
    Bool = 1
    String = 2


@dataclass
class LangType(Type):
    grammar: CFG

    def __str__(self) -> str:
        return self.grammar.name

    @staticmethod
    def from_literals(values: list[str]) -> "LangType":
        return LangType(CFG('<unnamed>', {'start': values}))


@dataclass
class ListType(Type):
    elem_type: Type

    def __str__(self) -> str:
        return f'list[{self.elem_type}]'


@dataclass
class TupleType(Type):
    elems: list[Type]

    def __str__(self) -> str:
        return '(' + ', '.join(self.elems) + ')'


@dataclass
class RecordType(Type):
    constr: type
    fields: dict[str, Type]

    def __str__(self) -> str:
        return self.constr.__name__


@dataclass
class RefinedType(Type):
    base: Type
    refinement: Any  # This is an AST lambda at compile time;

    # it is a callable function at runtime.

    def __str__(self) -> str:
        return '{' + f'{self.base} | {self.refinement}' + '}'


def get_base_type(typ: Type) -> BuiltinType:
    match typ:
        case BuiltinType() as b:
            return b
        case LangType():
            return BuiltinType.String
        case RefinedType(b, _):
            return get_base_type(b)
        case _:
            raise ValueError(f"Illegal input: {typ}")
