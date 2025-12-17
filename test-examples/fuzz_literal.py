from typing import Literal

from flat.py import fuzz


def f(x: Literal[1, 2]) -> int:
    return x


fuzz(f)
