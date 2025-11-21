from dataclasses import dataclass
from typing import Literal

from flat.grammar.diagnostics import Location

class Node:
    loc: Location

# Expressions

class Expr(Node):
    """Grammar expression, regular or context-free."""
    pass

@dataclass
class Lit(Expr):
    """String literal."""
    value: str

@dataclass
class CharRange(Node):
    """Character range. Matches any character in between the bounds, both inclusive."""
    lower: str
    upper: str

@dataclass
class CharClass(Expr):
    """Character class.
    If inclusive, matches any character in the items.
    If exclusive, matches any character not in the items."""
    mode: Literal['inclusive', 'exclusive']
    items: list[str | CharRange]

@dataclass
class Symbol(Expr):
    """Nonterminal symbol."""
    id: str

@dataclass
class Concat(Expr):
    """Concatenation."""
    elements: list[Expr]

@dataclass
class Union(Expr):
    """Union/alternation."""
    options: list[Expr]

@dataclass
class Star(Expr):
    """Kleene star."""
    element: Expr

@dataclass
class Plus(Expr):
    """Kleene plus."""
    element: Expr

@dataclass
class Optional(Expr):
    """Optional."""
    element: Expr

@dataclass
class Power(Expr):
    """Exact repetition: matches the element repeated exactly a number of times."""
    element: Expr
    times: int

@dataclass
class NatRange(Node):
    """Natural number range: represents any natural number in between the bounds (both inclusive),
    or unbounded if upper is None."""
    lower: int
    upper: int | None

@dataclass
class Loop(Expr):
    """Range Repetition: matches the element repeated a number of times."""    
    element: Expr
    times: NatRange

# Grammars

type RE = Expr

@dataclass
class Rule(Node):
    symbol: Symbol
    body: Expr

type CFG = list[Rule]