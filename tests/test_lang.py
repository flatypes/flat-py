import unittest

from flat.backend.lang import project
from flat.py.analyzer import analyze_lang
from flat.py.compile_time import Context, LangType, Issuer
from flat.py.shared import Lang, NT


def parse_lang(grammar_source: str) -> Lang:
    ctx = Context('<test>', Issuer())
    match analyze_lang(grammar_source, ctx):
        case LangType(lang):
            assert not ctx.issuer.has_errors
            return lang
        case _:
            assert False


lang = parse_lang("""
    S: '(' S ')' | A;
    A: 'a';
    B: 'b' C | D;
    C: 'c' | D;
    D: 'd' | C;
    E: 'e' A;
    """)


class TestProject(unittest.TestCase):
    def test_S(self) -> None:
        actual = project(lang, 'S')
        self.assertDictEqual(actual, {'S': [['(', NT('S'), ')'], [NT('A')]], 'A': [['a']]})

    def test_A(self) -> None:
        actual = project(lang, 'A')
        self.assertDictEqual(actual, {'A': [['a']]})

    def test_B(self) -> None:
        actual = project(lang, 'B')
        self.assertDictEqual(actual, {'B': [['b', NT('C')], [NT('D')]],
                                      'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})

    def test_C(self) -> None:
        actual = project(lang, 'C')
        self.assertDictEqual(actual, {'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})

    def test_D(self) -> None:
        actual = project(lang, 'D')
        self.assertDictEqual(actual, {'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})

    def test_E(self) -> None:
        actual = project(lang, 'E')
        self.assertDictEqual(actual, {'A': [['a']], 'E': [['e', NT('A')]]})
