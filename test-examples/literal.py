from typing import Literal


def f(x: Literal['a', 'b']) -> str:
    return chr(ord(x) + 1)


def g(x: Literal[1, 2], y: Literal[1] = 0) -> int:
    return x + y


def h(x: str) -> Literal['a']:
    return x


def test(x: int) -> None:
    y1: Literal['ac'] = f('a') + f('b')
    y2 = ord(f('c')) + g(0)
    y3 = h('b')


test(0)
