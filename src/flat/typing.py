import abc
from dataclasses import dataclass
from enum import Enum
from typing import Union

from flat.grammars import Grammar

Value = int | bool | str


class Cond:
    @abc.abstractmethod
    def apply(self, value: Value) -> bool:
        raise NotImplementedError


class Type:
    @property
    def is_lang_type(self) -> bool:
        return False


class BaseType(Type):
    pass


class BuiltinType(BaseType, Enum):
    Int = 0
    Bool = 1
    String = 2


@dataclass
class LangType(BaseType):
    grammar: Grammar

    def is_lang_type(self) -> bool:
        return True

    def __str__(self) -> str:
        return self.grammar.name


@dataclass
class RefinementType(Type):
    base: BaseType
    cond: Cond

    def is_lang_type(self) -> bool:
        return self.base.is_lang_type

    def __str__(self) -> str:
        return '{' + f'{self.base} | {self.cond}' + '}'


@dataclass
class LiteralType(Type):
    values: list[Union[int, bool, str]]

    def __str__(self) -> str:
        return 'Literal[' + ', '.join(map(str, self.values)) + ']'


@dataclass
class ListType(Type):
    elem_type: Type

    def is_lang_type(self) -> bool:
        return self.elem_type.is_lang_type

    def __str__(self) -> str:
        return f'[{self.elem_type}]'


def get_base_type(typ: Type) -> BuiltinType:
    match typ:
        case BuiltinType() as b:
            return b
        case LangType():
            return BuiltinType.String
        case RefinementType(b, _):
            return get_base_type(b)


def value_has_type(value: Value, typ: Type) -> bool:
    match value, typ:
        case int(), BuiltinType.Int:
            return True
        case bool(), BuiltinType.Bool:
            return True
        case str(), BuiltinType.String:
            return True
        case str() as word, LangType(grammar):
            return word in grammar
        case value, RefinementType(base, cond):
            return value_has_type(value, base) and cond.apply(value)
        case _:
            return False
