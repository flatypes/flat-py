from dataclasses import dataclass
from typing import Optional

from flat.pos import Pos


@dataclass
class Lit:
    value: int | bool | str
    pos: Pos


@dataclass
class Ident:
    name: str
    pos: Pos


class Clause:
    pass


@dataclass
class Token(Clause):
    text: Lit


@dataclass
class Symbol(Clause):
    """A nonterminal symbol or referring to another lang."""
    ident: Ident


@dataclass
class CharRange(Clause):
    lhs: Lit  # char
    rhs: Lit  # char

    @property
    def begin(self) -> int:
        return ord(self.lhs.value)

    @property
    def end(self) -> int:
        return ord(self.rhs.value)

    @property
    def get_range(self) -> range:
        return range(self.begin, self.end + 1)


class RepRange:
    lower: int
    upper: Optional[int]  # None = inf


class RepStar(RepRange):
    lower = 0
    upper = None


class RepPlus(RepRange):
    lower = 1
    upper = None


class RepOpt(RepRange):
    lower = 0
    upper = 1


@dataclass
class RepExactly(RepRange):
    times: Lit  # int

    @property
    def lower(self) -> int:
        return self.times.value

    @property
    def upper(self) -> int:
        return self.times.value


@dataclass
class RepInRange(RepRange):
    at_least: Optional[Lit]  # int
    at_most: Optional[Lit]  # int

    @property
    def lower(self) -> int:
        return self.at_least.value if self.at_least else 0

    @property
    def upper(self) -> Optional[int]:
        return self.at_most.value if self.at_most else None


@dataclass
class Rep(Clause):
    clause: Clause
    rep_range: RepRange


@dataclass
class Seq(Clause):
    clauses: list[Clause]


@dataclass
class Alt(Clause):
    clauses: list[Clause]


@dataclass
class Rule:
    ident: Ident
    body: Clause

    @property
    def name(self) -> str:
        return self.ident.name
