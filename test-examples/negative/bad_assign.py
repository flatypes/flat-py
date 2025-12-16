from typing import Literal

type A = Literal[1, 2, 3]


def f() -> None:
    x1: Literal[1] = 1
    x1: int = 2
    x2: list[int] = [x1]
    x2[0]: int = 3
    global A
    A = 3
