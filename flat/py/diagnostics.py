from dataclasses import dataclass
from enum import Enum

@dataclass
class Position:
    line: int
    column: int

@dataclass
class Range:
    start: Position
    end: Position

@dataclass
class Location:
    file_path: str
    range: Range

class Level(Enum):
    ERROR = 1
    WARN = 2

@dataclass(kw_only=True)
class Diagnostic:
    level: Level = Level.ERROR
    loc: Location | None
    msg: str

class Issuer:
    _diagnostics: list[Diagnostic]

    def __init__(self) -> None:
        self._diagnostics = []

    def issue(self, diagnostic: Diagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def has_errors(self) -> bool:
        return any(d.level == Level.ERROR for d in self._diagnostics)
    
    def get_errors(self) -> list[Diagnostic]:
        return [d for d in self._diagnostics if d.level == Level.ERROR]

    def pretty(self) -> str:
        lines = []
        for d in self._diagnostics:
            prefix = "ERROR" if d.level == Level.ERROR else "WARN"
            loc_str = f"{d.loc.file_path}:{d.loc.range.start.line}:{d.loc.range.start.column}" if d.loc else "<unknown location>"
            lines.append(f"{loc_str} - {prefix}: {d.msg}")
        return "\n".join(lines)

# Diagnostic subclasses

class UndefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Name '{id}' is not defined")

## Type analysis

class InvalidType(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(loc=loc, msg="Invalid type")

class ArityMismatch(Diagnostic):
    def __init__(self, id: str, expected: str, actual: int, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Type constructor '{id}' expects {expected} argument(s), got {actual}")

class InvalidLiteral(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(loc=loc, msg="Invalid literal value for 'typing.Literal'")

## Instrumentation

class RedefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Name '{id}' is already defined")


class UndefinedNonlocal(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Nonlocal name '{id}' is not defined in any enclosing scope")

class NotAssignable(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(loc=loc, msg=f"Name '{id}' is not assignable")

class UnsupportedFeature(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg="Unsupported feature")

class IgnoredAnnot(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg="Type annotation is ignored")