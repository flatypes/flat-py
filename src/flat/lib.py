from typing import TypeVar, Callable

from flat.selectors import XPath, select_by_xpath, xpath_parser
from flat.typing import LangType


def implies(p: bool, q: bool) -> bool:
    return q if p else True


# builtin functions for writing spec
T = TypeVar('T')


def forall(f: Callable[[T], bool], xs: list[T]) -> bool:
    return all(f(x) for x in xs)


def exists(f: Callable[[T], bool], xs: list[T]) -> bool:
    return any(f(x) for x in xs)


def first(xs: list[T]) -> T:
    return xs[0]


def last(xs: list[T]) -> T:
    return xs[-1]


def xpath(language: LangType, selector: str) -> XPath:
    return XPath(language, xpath_parser.parse(selector))


def select_all(path: XPath, word: str) -> list[str]:
    try:
        root = path.language.grammar.parse(word)
    except SyntaxError:
        return []

    return [tree.to_string() for tree in select_by_xpath(root, path)]


def select(path: XPath, word: str) -> str:
    candidates = select_all(path, word)
    assert len(candidates) == 1, f'selected: {candidates}'
    return candidates[0]


def select_kth(path: XPath, word: str, k: int) -> str:
    candidates = select_all(path, word)
    return candidates[k]


def selected_all(f: Callable[[str], bool], path: XPath, word: str) -> bool:
    return forall(f, select_all(path, word))


def selected_any(f: Callable[[str], bool], path: XPath, word: str) -> bool:
    return exists(f, select_all(path, word))
