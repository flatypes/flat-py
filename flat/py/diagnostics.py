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

@dataclass
class Diagnostic:
    level: Level
    msg: str
    loc: Location | None

class Issuer:
    _diagnostics: list[Diagnostic]

    def __init__(self) -> None:
        self._diagnostics = []

    def report(self, diagnostic: Diagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def has_errors(self) -> bool:
        return any(d.level == Level.ERROR for d in self._diagnostics)

    def pretty(self) -> str:
        lines = []
        for d in self._diagnostics:
            prefix = "ERROR" if d.level == Level.ERROR else "WARN"
            loc_str = f"{d.loc.file_path}:{d.loc.range.start.line}:{d.loc.range.start.column}" if d.loc else "<unknown location>"
            lines.append(f"{loc_str} - {prefix}: {d.msg}")
        return "\n".join(lines)