from dataclasses import dataclass
from enum import Enum
from typing import Iterable

__all__ = ['Position', 'Range', 'Location', 'Level', 'Diagnostic', 'Issuer',
           'InvalidSyntax', 'UndefinedRule', 'RedefinedRule', 'NoStartRule', 'EmptyRange',
           'UndefinedName', 'RedefinedName', 'InvalidType', 'InvalidLiteral', 'InvalidFormat',
           'ArityMismatch', 'UndefinedNonlocal', 'NotAssignable', 'UnsupportedFeature']


@dataclass
class Position:
    """Position in a file: consists of a row number and an offset in that row, both *zero*-based."""
    row: int
    offset: int

    def __add__(self, delta: tuple[int, int]) -> 'Position':
        delta_row, delta_offset = delta
        return Position(self.row + delta_row, self.offset + delta_offset)

    def __str__(self):
        return f"{self.row}:{self.offset}"


@dataclass
class Range:
    """Position range in a file: consists of two *inclusive* endpoints."""
    start: Position
    end: Position

    def __str__(self):
        return f"{self.start}-{self.end}"


@dataclass
class Location:
    """Location in a file: consists of the file path and a range within that file."""
    file_path: str
    range: Range

    def __str__(self):
        return f"{self.file_path}:{self.range.start}"


class Level(Enum):
    """Diagnostic level."""
    ERROR = 1
    WARN = 2


@dataclass(kw_only=True)
class Diagnostic:
    """Diagnostic object: consists of a diagnostic level, a main error location, and a message."""
    level: Level = Level.ERROR
    loc: Location | None
    msg: str


class Issuer:
    """Diagnostic collector."""

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def issue(self, diagnostic: Diagnostic) -> None:
        """Add a diagnostic."""
        self._diagnostics.append(diagnostic)

    @property
    def has_diagnostics(self) -> bool:
        """Test if there are any diagnostics."""
        return len(self._diagnostics) > 0

    @property
    def has_errors(self) -> bool:
        """Test if there are any ERROR-level diagnostics."""
        return any(d.level == Level.ERROR for d in self._diagnostics)

    def get_diagnostics(self) -> Iterable[Diagnostic]:
        """Get all diagnostics."""
        return self._diagnostics

    def pretty(self) -> str:
        """Pretty-print all diagnostics."""
        lines = []
        for d in self._diagnostics:
            prefix = "ERROR" if d.level == Level.ERROR else "WARN"
            loc_str = f"{d.loc}" if d.loc else "<unknown location>"
            lines.append(f"{loc_str} - {prefix}: {d.msg}")
        return "\n".join(lines)


# Instances of specific diagnostics:
class InvalidSyntax(Diagnostic):
    def __init__(self, msg: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Invalid syntax: {msg}")


class UndefinedRule(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Undefined rule: {id}")


class RedefinedRule(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Redefined rule: {id}")


class NoStartRule(Diagnostic):
    def __init__(self, lang_id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"No 'start' rule in '{lang_id}'")


class EmptyRange(Diagnostic):
    def __init__(self, lower: str, upper: str, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg=f"Empty range: {lower} > {upper}")


class UndefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Undefined name: {id}")


class RedefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Name '{id}' is already defined")


class InvalidType(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(loc=loc, msg="Invalid type")


class InvalidLiteral(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(loc=loc, msg="Invalid literal value for 'typing.Literal'")


class InvalidFormat(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Invalid grammar format")


class ArityMismatch(Diagnostic):
    def __init__(self, id: str, expected: str, actual: int, loc: Location) -> None:
        super().__init__(loc=loc,
                         msg=f"Type constructor '{id}' expects {expected} argument(s), got {actual}")


class UndefinedNonlocal(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Nonlocal name '{id}' is not defined in any enclosing scope")


class NotAssignable(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Name '{id}' is not assignable")


class UnsupportedFeature(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg="Unsupported feature")
