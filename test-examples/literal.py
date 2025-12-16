from typing import Literal


def f(x: Literal['a', 'b']) -> Literal['b', 'c']:
    return chr(ord(x) + 1)


def g(x: Literal[1, 2], y: Literal[1] = 0) -> int:
    return x + y


def h(x: str) -> Literal['a']:
    return x


def test(x: int) -> None:
    y1: Literal['bc'] = f('a') + f('b')
    y2: Literal['bb'] = f('a') + f('b')
    y3 = ord(f('c')) + g(0)
    y4 = h('b')


test(0)
