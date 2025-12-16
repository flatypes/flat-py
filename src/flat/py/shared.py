import ast
import linecache
import sys
from dataclasses import dataclass
from typing import Sequence

__all__ = ['Range', 'get_range', 'get_code', 'print_details']


@dataclass(frozen=True)
class Range:
    """Position range in source file."""
    lineno: int  # inclusive, one-based
    end_lineno: int  # inclusive, one-based
    col_offset: int  # inclusive, zero-based
    end_col_offset: int  # exclusive, zero-based

    def __rshift__(self, delta: tuple[int, int]) -> 'Range':
        delta_row, delta_col = delta
        return Range(self.lineno + delta_row,
                     self.end_lineno + delta_row,
                     self.col_offset + delta_col if self.lineno == 1 else self.col_offset,
                     self.end_col_offset + delta_col if self.lineno == 1 else self.end_col_offset)

    @staticmethod
    def at(row: int, col_offset: int) -> 'Range':
        return Range(row + 1, row + 1, col_offset, col_offset + 1)


def get_range(node: ast.AST) -> Range:
    """Get the position range of an AST node."""
    lineno = getattr(node, 'lineno')
    end_lineno = getattr(node, 'end_lineno')
    col_offset = getattr(node, 'col_offset')
    end_col_offset = getattr(node, 'end_col_offset')

    assert lineno is not None
    assert end_lineno is not None
    assert col_offset is not None
    assert end_col_offset is not None
    return Range(lineno, end_lineno, col_offset, end_col_offset)


def get_code(file_path: str, pos: Range) -> str:
    """Get the source code at the given position range."""
    lines = []
    for lineno in range(pos.lineno, pos.end_lineno + 1):
        line = linecache.getline(file_path, lineno)
        start = pos.col_offset if lineno == pos.lineno else 0
        end = pos.end_col_offset if lineno == pos.end_lineno else len(line)
        lines.append(line[start:end])
    return ''.join(lines)


def print_details(file_path: str, caret_range: Range, details: Sequence[str],
                  *, width: int | None = None, show_file_path: bool = True) -> None:
    lineno_width = width if width is not None else len(str(caret_range.end_lineno))
    if show_file_path:
        print(' ' * lineno_width + f'--> {file_path}:{caret_range.lineno}', file=sys.stderr)

    before_caret = ''
    for lineno in range(caret_range.lineno, caret_range.end_lineno + 1):
        line = linecache.getline(file_path, lineno)
        lineno_str = str(lineno).ljust(lineno_width)
        print(f'{lineno_str} |{line}', end='', file=sys.stderr)
        start = caret_range.col_offset if lineno == caret_range.lineno else 0
        end = caret_range.end_col_offset if lineno == caret_range.end_lineno else len(line)
        before_caret = ' ' * lineno_width + ' |' + ' ' * start
        print(before_caret + '^' * (end - start), file=sys.stderr)
    for detail in details:
        print(before_caret + detail, file=sys.stderr)
