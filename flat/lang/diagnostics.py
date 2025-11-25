from dataclasses import dataclass
from enum import Enum
from typing import Iterable

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
    
    def get_diagnostics(self) -> Iterable[Diagnostic]:
        return self._diagnostics

    def pretty(self) -> str:
        lines = []
        for d in self._diagnostics:
            prefix = "ERROR" if d.level == Level.ERROR else "WARN"
            loc_str = f"{d.loc.file_path}:{d.loc.range.start.line}:{d.loc.range.start.column}" if d.loc else "<unknown location>"
            lines.append(f"{loc_str} - {prefix}: {d.msg}")
        return "\n".join(lines)

# Diagnostic subclasses

class EmptyRange(Diagnostic):
    def __init__(self, lower: str, upper: str, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg=f"Empty range: {lower} > {upper}")

class RedefinedRule(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Redefined rule: {id}")

class UndefinedRule(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Undefined rule: {id}")

class NoStartRule(Diagnostic):
    def __init__(self, lang_id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"No 'start' rule in '{lang_id}'")