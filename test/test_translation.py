import string
import unittest

from flat.lang.diagnostics import *
from flat.lang.parsing import parse
from flat.lang.translation import NT, normalize, project

class TestValidate(unittest.TestCase):
    def test_empty_char_range(self):
        lang = parse('[ad-b]+', format='regex')
        issuer = Issuer()
        normalize(lang, issuer)
        diagnostics = issuer.get_diagnostics()
        self.assertEqual(len(diagnostics), 1)
        self.assertIsInstance(diagnostics[0], EmptyRange)

    def test_empty_loop_range(self):
        lang = parse('ab{5,3}', format='regex')
        issuer = Issuer()
        normalize(lang, issuer)
        diagnostics = issuer.get_diagnostics()
        self.assertEqual(len(diagnostics), 1)
        self.assertIsInstance(diagnostics[0], EmptyRange)

    def test_redefined_rule(self):
        lang = parse("""
            S: 'a' A;
            A: 'b';
            S: 'c';
        """)
        issuer = Issuer()
        normalize(lang, issuer)
        diagnostics = issuer.get_diagnostics()
        self.assertEqual(len(diagnostics), 1)
        self.assertIsInstance(diagnostics[0], RedefinedRule)

    def test_undefined_rule(self):
        lang = parse("""
            S: 'a' A;
        """)
        issuer = Issuer()
        normalize(lang, issuer)
        diagnostics = issuer.get_diagnostics()
        self.assertEqual(len(diagnostics), 1)
        self.assertIsInstance(diagnostics[0], UndefinedRule)

class TestNormalize(unittest.TestCase):
    def test_char_class(self):
        lang = parse('[a-c+*]', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [[NT('@1')]], '@1': [['a'], ['b'], ['c'], ['+'], ['*']]})

    def test_union(self):
        lang = parse('a|b|c', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [['a'], ['b'], ['c']]})

    def test_nested_union(self):
        lang = parse('x(a|b)', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [['x', NT('@1')]], '@1': [['a'], ['b']]})

    def test_star(self):
        lang = parse('a*', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [[NT('@1')]], '@1': [[], ['a', NT('@1')]]})

    def test_plus(self):
        lang = parse('ab+', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [['a', NT('@1')]], '@1': [['b'], ['b', NT('@1')]]})

    def test_optional(self):
        lang = parse('a?b', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [[NT('@1'), 'b']], '@1': [[], ['a']]})

    def test_power(self):
        lang = parse('a{3}b{1}c{0}', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [['a', 'a', 'a', 'b']]})

    def test_loop(self):
        lang = parse('a{2,4}b{3,}c{,2}', format='regex')
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'start': [['a', 'a', NT('@1'), 'b', 'b', 'b', NT('@2'), NT('@3')]],
                                         '@1': [[], ['a'], ['a', 'a']],
                                         '@2': [[], ['b', NT('@2')]],
                                         '@3': [[], ['c'], ['c', 'c']]})

    def test_cfg(self):
        lang = parse("""
            S: '(' S ')' | 'a' | B;
            B: ('+'|'-') [0-9]+;
        """)
        issuer = Issuer()
        norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())
        self.assertDictEqual(norm_lang, {'S': [['(', NT('S'), ')' ], ['a'], [NT('B')]],
                                         'B': [[NT('@1'), NT('@2')]],
                                         '@1': [['+'], ['-']],
                                         '@2': [[NT('@3')], [NT('@3'), NT('@2')]],
                                         '@3': [[c] for c in string.digits]})


class TestProject(unittest.TestCase):
    def setUp(self):
        lang = parse("""
            S: '(' S ')' | A;
            A: 'a';
            B: 'b' C | D;
            C: 'c' | D;
            D: 'd' | C;
            E: 'e' A;
        """)
        issuer = Issuer()
        self.norm_lang = normalize(lang, issuer)
        self.assertFalse(issuer.has_errors())

    def test_S(self):
        projected_lang = project(self.norm_lang, 'S')
        self.assertDictEqual(projected_lang, {'S': [['(', NT('S'), ')' ], [NT('A')]], 'A': [['a']]})

    def test_A(self):
        projected_lang = project(self.norm_lang, 'A')
        self.assertDictEqual(projected_lang, {'A': [['a']]})

    def test_B(self):
        projected_lang = project(self.norm_lang, 'B')
        self.assertDictEqual(projected_lang, {'B': [['b', NT('C')], [NT('D')]], 
                                              'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})
    
    def test_C(self):
        projected_lang = project(self.norm_lang, 'C')
        self.assertDictEqual(projected_lang, {'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})

    def test_D(self):
        projected_lang = project(self.norm_lang, 'D')
        self.assertDictEqual(projected_lang, {'C': [['c'], [NT('D')]], 'D': [['d'], [NT('C')]]})

    def test_E(self):
        projected_lang = project(self.norm_lang, 'E')
        self.assertDictEqual(projected_lang, {'A': [['a']], 'E': [['e', NT('A')]]})