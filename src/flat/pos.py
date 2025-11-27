from dataclasses import dataclass
from typing import Tuple


@dataclass
class Pos:
    """A position in source file that consists of a starting and ending point, both inclusive.
    Each point is a zero-based coordinate (row, offset in row)."""
    start: Tuple[int, int]
    end: Tuple[int, int]

    def __lt__(self, other):
        match other:
            case Pos(other_start, _):
                return self.start < other_start
            case _:
                raise TypeError


NoPos = Pos((-1, -1), (-1, -1))
