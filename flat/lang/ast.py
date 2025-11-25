from dataclasses import dataclass, fields
from typing import Any, Literal, Sequence

from flat.lang.diagnostics import Location

class Node:
    """AST node."""
    loc: Location

@dataclass
class Expr(Node):
    """A regular expression or an expression in a context-free grammar."""
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
    If exclusive, matches any character not in the items.
    """
    mode: Literal['inclusive', 'exclusive']
    items: Sequence[str | CharRange]

@dataclass
class Name(Expr):
    """Either a nonterminal symbol or a reference to another language.
    If `start` is given, it is a reference to another language using this start symbol.
    """
    id: str
    start: str | None = None

@dataclass
class Concat(Expr):
    """Concatenation."""
    elements: Sequence[Expr]

@dataclass
class Union(Expr):
    """Union/alternation."""
    options: Sequence[Expr]

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
    """Power. Matches the element repeated exactly a number of times."""
    element: Expr
    times: int

@dataclass
class NatRange(Node):
    """Natural number range. Both bounds are inclusive. If upper is None, it is unbounded."""
    lower: int
    upper: int | None

@dataclass
class Loop(Expr):
    """Loop. Matches the element repeated a number of times."""    
    element: Expr
    times: NatRange

class ExprVisitor:
    def visit(self, node: Expr) -> Any:
        """Visit a node."""
        method_name = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: Expr) -> Any:
        """Default visitor if no explicit visitor is given for this node."""
        for field in fields(node):
            value = getattr(node, field.name)
            if isinstance(value, Sequence):
                for item in value:
                    if isinstance(item, Expr):
                        self.visit(item)
            elif isinstance(value, Expr):
                self.visit(value)

type RL = Expr

@dataclass
class Rule(Node):
    """Production rule in a context-free grammar."""
    name: Name
    body: Expr

type CFL = Sequence[Rule]

type Lang = RL | CFL