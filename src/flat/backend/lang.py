from dataclasses import dataclass
from typing import FrozenSet, Mapping, Sequence

__all__ = ['NT', 'Lang', 'project']


@dataclass
class NT:
    """NonTerminal symbol."""
    name: str


type Lang = Mapping[str, Sequence[Sequence[str | NT]]]


def project(lang: Lang, start: str) -> Lang:
    """Project the language to only include rules reachable from the start symbol."""
    reachable: set[str] = set()
    queue = [start]
    while len(queue) > 0:
        sym = queue.pop(0)
        if sym in lang and sym not in reachable:
            reachable.add(sym)
            for sym in collect_nonterminals(lang[sym]):
                if sym not in reachable:
                    queue.append(sym)

    return {sym: lang[sym] for sym in reachable}


def collect_nonterminals(body: Sequence[Sequence[str | NT]]) -> FrozenSet[str]:
    """Collect all nonterminals occurring in the body."""
    names: list[str] = []
    for seq in body:
        for sym in seq:
            if isinstance(sym, NT):
                names.append(sym.name)

    return frozenset(names)
