from dataclasses import dataclass

from isla.derivation_tree import DerivationTree
from isla.helpers import is_nonterminal
from parsy import string, seq, decimal_digit, regex

from flat.typing import LangType


@dataclass(frozen=True)
class XPathSelector:
    of: str


@dataclass(frozen=True)
class XPathSelectDirectAt(XPathSelector):
    k: int  # k-th, where k >= 1


class XPathSelectAllDirect(XPathSelector):
    pass


class XPathSelectAllIndirect(XPathSelector):
    pass


ident_start = regex(r'[_a-zA-Z]')
ident_rest = ident_start | decimal_digit | string("'")
ident_name = seq(ident_start, ident_rest.many()).combine(lambda c, cs: ''.join([c] + cs))

xpath_select_direct_at = string('.') >> seq(
    ident_name, string('[') >> decimal_digit.map(int) << string(']')).combine(XPathSelectDirectAt)
xpath_select_all_direct = string('.') >> ident_name.map(XPathSelectAllDirect)
xpath_select_all_indirect = string('..') >> ident_name.map(XPathSelectAllIndirect)
xpath_parser = (xpath_select_direct_at | xpath_select_all_direct | xpath_select_all_indirect).at_least(1)


@dataclass
class XPath:
    language: LangType
    selectors: list[XPathSelector]


def children_labelled_with(tree: DerivationTree, symbol: str) -> list[DerivationTree]:
    nonterminal = f'<{symbol}>'
    children = []
    for node in tree.children:
        if is_nonterminal(node.value):
            if node.value.startswith('<-'):  # intermediate node: skip and collect in its children
                children += children_labelled_with(node, nonterminal)
            elif node.value == nonterminal:
                children += [node]
    return children


def select_by_xpath(tree: DerivationTree, path: XPath) -> list[DerivationTree]:
    old = [tree]
    for selector in path.selectors:
        new = []
        if len(old) == 0:
            return []

        for parent in old:
            match selector:
                case XPathSelectDirectAt(symbol, k):
                    candidates = children_labelled_with(parent, symbol)
                    if len(candidates) >= k:
                        new.append(candidates[k - 1])
                case XPathSelectAllDirect(symbol):
                    new += children_labelled_with(parent, symbol)
                case XPathSelectAllIndirect(symbol):
                    nonterminal = f'<{symbol}>'
                    new += [node for _, node in parent.filter(lambda node: node.value == nonterminal)]
        old = new

    return old
