from dataclasses import dataclass

from flat.typing import Type


@dataclass(frozen=True)
class FunType(Type):
    takes: list[Type]
    returns: Type
