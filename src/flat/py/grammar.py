from dataclasses import dataclass, fields
from typing import Any, Literal, Sequence

from flat.py.shared import Range

__all__ = ['Node', 'Expr', 'Lit', 'CharRange', 'CharClass', 'Ref', 'Concat', 'Union',
           'Star', 'Plus', 'Optional', 'Power', 'NatRange', 'Loop', 'ExprVisitor', 'Rule', 'Grammar']


class Node:
    """Node with a location."""
    pos: Range


@dataclass
class Expr(Node):
    """Expression/Clause."""
    pass


@dataclass
class Lit(Expr):
    """String literal."""
    value: str


@dataclass
class CharRange(Node):
    """Character range: matches any character in between the two *inclusive* characters."""
    lower: str
    upper: str


@dataclass
class CharClass(Expr):
    """Character class: matches any character in (if inclusive) or not in (if exclusive) a set of chars."""
    mode: Literal['inclusive', 'exclusive']
    items: Sequence[str | CharRange]


@dataclass
class Ref(Expr):
    """Reference to a rule (possibly in another grammar)."""
    name: str


@dataclass
class Concat(Expr):
    """Concatenation."""
    elements: Sequence[Expr]


@dataclass
class Union(Expr):
    """Union/Alternation."""
    options: Sequence[Expr]


@dataclass
class Star(Expr):
    """Kleene star: repeats zero or more times."""
    element: Expr


@dataclass
class Plus(Expr):
    """Kleene plus: repeats one or more times."""
    element: Expr


@dataclass
class Optional(Expr):
    """Optional: repeats zero or one time."""
    element: Expr


@dataclass
class Power(Expr):
    """Power: repeats exactly a number of times."""
    element: Expr
    times: int


@dataclass
class NatRange(Node):
    """Natural number range: matches any number in between the two *inclusive* bounds.
    The upper bound can be unbounded.
    """
    lower: int
    upper: int | None


@dataclass
class Loop(Expr):
    """Loop: repeats a number of times in a given range."""
    element: Expr
    times: NatRange


class ExprVisitor:
    def visit(self, node: Expr) -> Any:
        """Visit a node."""
        method_name = 'visit_' + node.__class__.__name__
        if hasattr(self, method_name):
            return getattr(self, method_name)(node)
        else:
            raise NotImplementedError(f'No visit_{node.__class__.__name__} method')

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


@dataclass
class Rule(Node):
    """Production rule in a context-free grammar."""
    name: Ref
    body: Expr


type Grammar = Sequence[Rule]
