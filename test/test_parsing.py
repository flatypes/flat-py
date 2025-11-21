import unittest

from parsy import Parser, ParseError

from flat.grammar.ast import *
from flat.grammar.parsers import ExprParser, parse_RE, parse_CFG

class TestParseCharSeq(unittest.TestCase):
    class TestParser(ExprParser):
        def __init__(self) -> None:
            super().__init__('<unknown>', '')

        def atomic(self) -> Parser:
            return self.char_seq('*+?')

    def setUp(self) -> None:
        self.parser = self.TestParser().atomic()

    def test_ordinary(self):
        result = self.parser.parse(r'a')
        self.assertEqual(result, 'a')

    def test_escape_backslash(self):
        result = self.parser.parse(r'\\')
        self.assertEqual(result, '\\')

    def test_escape_tab(self):
        result = self.parser.parse(r'\t')
        self.assertEqual(result, '\t')
    
    def test_escape_special(self):
        result = self.parser.parse(r'\*')
        self.assertEqual(result, '*')

    def test_escape_octal(self):
        result = self.parser.parse(r'\777')
        self.assertEqual(result, chr(0o777))

    def test_escape_hexadecimal_2(self):
        result = self.parser.parse(r'\xFF')
        self.assertEqual(result, chr(0xFF))

    def test_escape_hexadecimal_4(self):
        result = self.parser.parse(r'\uFFFF')
        self.assertEqual(result, chr(0xFFFF))

    def test_escape_hexadecimal_8(self):
        result = self.parser.parse(r'\U0010FFFF')
        self.assertEqual(result, chr(0x10FFFF))

    def test_invalid_escape(self):
        with self.assertRaises(ParseError):
            self.parser.parse(r'\z')

    def test_invalid_escape_hexadecimal_2(self):
        with self.assertRaises(ParseError):
            self.parser.parse(r'\xF')

    def test_invalid_escape_hexadecimal_4(self):
        with self.assertRaises(ParseError):
            self.parser.parse(r'\uFFF')

    def test_invalid_escape_hexadecimal_8(self):
        with self.assertRaises(ParseError):
            self.parser.parse(r'\U10FFFF')

    def test_escape_line_str(self):
        result = self.parser.parse(r'hello\n\+1')
        self.assertEqual(result, 'hello\n+1')

    def test_escape_octal_str(self):
        result = self.parser.parse(r'\7777')
        self.assertEqual(result, chr(0o777) + '7')

    def test_escape_hexadecimal_str(self):
        result = self.parser.parse(r'\xFFFF')
        self.assertEqual(result, chr(0xFF) + 'FF')

class TestParseRE(unittest.TestCase):
    def test_union(self):
        grammar = parse_RE(r'a|b|c')
        self.assertEqual(grammar, Union([Lit('a'), Lit('b'), Lit('c')]))

    def test_concat(self):
        grammar = parse_RE(r'abc')
        self.assertEqual(grammar, Concat([Lit('a'), Lit('b'), Lit('c')]))

    def test_star(self):
        grammar = parse_RE(r'a*')
        self.assertEqual(grammar, Star(Lit('a')))

    def test_plus(self):
        grammar = parse_RE(r'a+')
        self.assertEqual(grammar, Plus(Lit('a')))

    def test_optional(self):
        grammar = parse_RE(r'a?')
        self.assertEqual(grammar, Optional(Lit('a')))

    def test_power(self):
        grammar = parse_RE(r'a{3}')
        self.assertEqual(grammar, Power(Lit('a'), 3))

    def test_loop(self):
        grammar = parse_RE(r'a{2,5}')
        self.assertEqual(grammar, Loop(Lit('a'), NatRange(2, 5)))

    def test_loop_unbounded(self):
        grammar = parse_RE(r'a{,}')
        self.assertEqual(grammar, Loop(Lit('a'), NatRange(0, None)))

    def test_char_class_inclusive(self):
        grammar = parse_RE(r'[a-cx-z]')
        self.assertEqual(grammar, CharClass('inclusive', [CharRange('a', 'c'), CharRange('x', 'z')]))

    def test_char_class_exclusive(self):
        grammar = parse_RE(r'[^.+\-|]')
        self.assertEqual(grammar, CharClass('exclusive', ['.', '+', '-', '|']))

    def test_char_class_escape(self):
        grammar = parse_RE(r'[\'\x41-\x5A\[\-\]]')
        self.assertEqual(grammar, CharClass('inclusive', ["'", CharRange('A', 'Z'), '[', '-', ']']))

    def test_invalid_char_class(self):
        with self.assertRaises(ParseError):
            parse_RE(r'[ab-]')

    def test_nested_expr(self):
        grammar = parse_RE(r'(ab?|c(d|e)f)*')
        self.assertEqual(grammar, Star(Union([Concat([Lit('a'), Optional(Lit('b'))]),
                                              Concat([Lit('c'), Union([Lit('d'), Lit('e')]), Lit('f')])])))

    def test_invalid_multiple_stars(self):
        with self.assertRaises(ParseError):
            parse_RE(r'a**')

class TestParseCFG(unittest.TestCase):
    def test_union(self):
        grammar = parse_CFG(r'start: "foo" | "bar";')
        self.assertEqual(grammar, [Rule(Symbol('start'), Union([Lit('foo'), Lit('bar')]))])

    def test_concat(self):
        grammar = parse_CFG(r'start: "foo" start "bar";')
        self.assertEqual(grammar, [Rule(Symbol('start'), Concat([Lit('foo'), Symbol('start'), Lit('bar')]))])

    def test_star(self):
        grammar = parse_CFG(r'start: "foo"*;')
        self.assertEqual(grammar, [Rule(Symbol('start'), Star(Lit('foo')))])

    def test_plus(self):
        grammar = parse_CFG(r'start: "foo"+;')
        self.assertEqual(grammar, [Rule(Symbol('start'), Plus(Lit('foo')))])

    def test_optional(self):
        grammar = parse_CFG(r'start: "foo"?;')
        self.assertEqual(grammar, [Rule(Symbol('start'), Optional(Lit('foo')))])

    def test_power(self):
        grammar = parse_CFG(r'start: "foo"{3};')
        self.assertEqual(grammar, [Rule(Symbol('start'), Power(Lit('foo'), 3))])

    def test_loop(self):
        grammar = parse_CFG(r'start: "foo"{2,5};')
        self.assertEqual(grammar, [Rule(Symbol('start'), Loop(Lit('foo'), NatRange(2, 5)))])

    def test_loop_unbounded(self):
        grammar = parse_CFG(r'start: "foo"{,};')
        self.assertEqual(grammar, [Rule(Symbol('start'), Loop(Lit('foo'), NatRange(0, None)))])

    def test_angled_symbols(self):
        grammar = parse_CFG(r'<start>: <foo> | <bar>;')
        self.assertEqual(grammar, [Rule(Symbol('start'), Union([Symbol('foo'), Symbol('bar')]))])

    def test_multiple_rules(self):
        grammar = parse_CFG(r'''
            start: ("val" | "var") id "=" expr;
            id: [A-Za-z_][A-Za-z0-9_]*;
            expr: [0-9]+ | id | "(" expr ")" | expr ("+" | "-") expr;
        ''')
        self.assertEqual(grammar, [
            Rule(Symbol('start'), Concat([Union([Lit('val'), Lit('var')]), Symbol('id'), Lit('='), Symbol('expr')])),
            Rule(Symbol('id'), Concat([CharClass('inclusive', [CharRange('A', 'Z'), CharRange('a', 'z'), '_']),
                                       Star(CharClass('inclusive', [CharRange('A', 'Z'), CharRange('a', 'z'),
                                                                    CharRange('0', '9'), '_']))])),
            Rule(Symbol('expr'), Union([Plus(CharClass('inclusive', [CharRange('0', '9')])),
                                        Symbol('id'),
                                        Concat([Lit('('), Symbol('expr'), Lit(')')]),
                                        Concat([Symbol('expr'), Union([Lit('+'), Lit('-')]), Symbol('expr')])]))
        ])