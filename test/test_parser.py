import unittest
from typing import Sequence

from flat.py.diagnostics import InvalidSyntax
from flat.py.grammar import *
from flat.py.parser import parse


class Base(unittest.TestCase):
    def assert_equal(self, actual: Grammar | InvalidSyntax, expected: Grammar | Expr) -> None:
        if isinstance(actual, Sequence):
            if isinstance(expected, Expr):
                expected = [Rule(Ref('start'), expected)]
            self.assertSequenceEqual(actual, expected)
        else:
            self.fail(f"Expected grammar, but got error: {actual.msg}")

    def assert_error(self, actual: Grammar | InvalidSyntax, msg_contains: str) -> None:
        if isinstance(actual, InvalidSyntax):
            if msg_contains not in actual.msg:
                self.fail(f"Actual message does not contain '{msg_contains}': {actual.msg}")
        else:
            self.fail(f"Expected error, but got grammar: {actual}")


class TestParseLiteral(Base):
    def test_ordinary(self) -> None:
        actual = parse('a', grammar_format='regex')
        self.assert_equal(actual, Lit('a'))

    def test_escape_backslash(self) -> None:
        actual = parse(r'\\', grammar_format='regex')
        self.assert_equal(actual, Lit('\\'))

    def test_escape_tab(self) -> None:
        actual = parse(r'\t', grammar_format='regex')
        self.assert_equal(actual, Lit('\t'))

    def test_escape_special(self) -> None:
        actual = parse(r'\*', grammar_format='regex')
        self.assert_equal(actual, Lit('*'))

    def test_escape_octal(self) -> None:
        actual = parse(r'\777', grammar_format='regex')
        self.assert_equal(actual, Lit(chr(0o777)))

    def test_escape_hexadecimal_2(self) -> None:
        actual = parse(r'\xFF', grammar_format='regex')
        self.assert_equal(actual, Lit(chr(0xFF)))

    def test_escape_hexadecimal_4(self) -> None:
        actual = parse(r'\uFFFF', grammar_format='regex')
        self.assert_equal(actual, Lit(chr(0xFFFF)))

    def test_escape_hexadecimal_8(self) -> None:
        actual = parse(r'\U0010FFFF', grammar_format='regex')
        self.assert_equal(actual, Lit(chr(0x10FFFF)))

    def test_invalid_escape(self) -> None:
        actual = parse(r'\z', grammar_format='regex')
        self.assert_error(actual, "invalid escape sequence")

    def test_invalid_escape_hexadecimal_2(self) -> None:
        actual = parse(r'\xF', grammar_format='regex')
        self.assert_error(actual, "expected 2 hex digits")

    def test_invalid_escape_hexadecimal_4(self) -> None:
        actual = parse(r'\uFFF', grammar_format='regex')
        self.assert_error(actual, "expected 4 hex digits")

    def test_invalid_escape_hexadecimal_8(self) -> None:
        actual = parse(r'\U10FFFF', grammar_format='regex')
        self.assert_error(actual, "expected 8 hex digits")

    def test_escape_line_str(self) -> None:
        actual = parse(r'0\n\+1', grammar_format='regex')
        self.assert_equal(actual, Concat([Lit('0'), Lit('\n'), Lit('+'), Lit('1')]))

    def test_escape_octal_str(self) -> None:
        actual = parse(r'\7777', grammar_format='regex')
        self.assert_equal(actual, Concat([Lit(chr(0o777)), Lit('7')]))

    def test_escape_hexadecimal_str(self) -> None:
        actual = parse(r'\xFFFF', grammar_format='regex')
        self.assert_equal(actual, Concat([Lit(chr(0xFF)), Lit('F'), Lit('F')]))


class TestParseRegex(Base):
    def test_union(self) -> None:
        actual = parse('a|b|c', grammar_format='regex')
        self.assert_equal(actual, Union([Lit('a'), Lit('b'), Lit('c')]))

    def test_concat(self) -> None:
        actual = parse('abc', grammar_format='regex')
        self.assert_equal(actual, Concat([Lit('a'), Lit('b'), Lit('c')]))

    def test_star(self) -> None:
        actual = parse('a*', grammar_format='regex')
        self.assert_equal(actual, Star(Lit('a')))

    def test_plus(self) -> None:
        actual = parse('a+', grammar_format='regex')
        self.assert_equal(actual, Plus(Lit('a')))

    def test_optional(self) -> None:
        actual = parse('a?', grammar_format='regex')
        self.assert_equal(actual, Optional(Lit('a')))

    def test_power(self) -> None:
        actual = parse('a{3}', grammar_format='regex')
        self.assert_equal(actual, Power(Lit('a'), 3))

    def test_loop(self) -> None:
        actual = parse('a{2,5}', grammar_format='regex')
        self.assert_equal(actual, Loop(Lit('a'), NatRange(2, 5)))

    def test_loop_unbounded(self) -> None:
        actual = parse('a{,}', grammar_format='regex')
        self.assert_equal(actual, Loop(Lit('a'), NatRange(0, None)))

    def test_char_class_inclusive(self) -> None:
        actual = parse('[a-cx-z]', grammar_format='regex')
        self.assert_equal(actual, CharClass('inclusive', [CharRange('a', 'c'), CharRange('x', 'z')]))

    def test_char_class_exclusive(self) -> None:
        actual = parse(r'[^.+\-|]', grammar_format='regex')
        self.assert_equal(actual, CharClass('exclusive', ['.', '+', '-', '|']))

    def test_char_class_escape(self) -> None:
        actual = parse(r'[\'\x41-\x5A\[\-\]]', grammar_format='regex')
        self.assert_equal(actual, CharClass('inclusive', ["'", CharRange('A', 'Z'), '[', '-', ']']))

    def test_invalid_char_class(self) -> None:
        actual = parse('[ab-]', grammar_format='regex')
        self.assertIsInstance(actual, InvalidSyntax)

    def test_nested_expr(self) -> None:
        actual = parse('(ab?|c(d|e)[^f])*', grammar_format='regex')
        self.assert_equal(actual, Star(Union([Concat([Lit('a'), Optional(Lit('b'))]),
                                              Concat([Lit('c'), Union([Lit('d'), Lit('e')]),
                                                      CharClass('exclusive', ['f'])])])))

    def test_invalid_multiple_stars(self) -> None:
        actual = parse('a**', grammar_format='regex')
        self.assert_error(actual, 'EOF')


class TestParseEBNF(Base):
    def test_union(self) -> None:
        actual = parse('start: "foo" | "bar";')
        self.assert_equal(actual, [Rule(Ref('start'), Union([Lit('foo'), Lit('bar')]))])

    def test_concat(self) -> None:
        actual = parse('start: "foo" start "bar";')
        self.assert_equal(actual, [Rule(Ref('start'), Concat([Lit('foo'), Ref('start'), Lit('bar')]))])

    def test_star(self) -> None:
        actual = parse('start: "foo"*;')
        self.assert_equal(actual, [Rule(Ref('start'), Star(Lit('foo')))])

    def test_plus(self) -> None:
        actual = parse('start: "foo"+;')
        self.assert_equal(actual, [Rule(Ref('start'), Plus(Lit('foo')))])

    def test_optional(self) -> None:
        actual = parse('start: "foo"?;')
        self.assert_equal(actual, [Rule(Ref('start'), Optional(Lit('foo')))])

    def test_power(self) -> None:
        actual = parse('start: "foo"{3};')
        self.assert_equal(actual, [Rule(Ref('start'), Power(Lit('foo'), 3))])

    def test_loop(self) -> None:
        actual = parse('start: "foo"{2,5};')
        self.assert_equal(actual, [Rule(Ref('start'), Loop(Lit('foo'), NatRange(2, 5)))])

    def test_loop_unbounded(self) -> None:
        actual = parse('start: "foo"{,};')
        self.assert_equal(actual, [Rule(Ref('start'), Loop(Lit('foo'), NatRange(0, None)))])

    def test_angled_Names(self) -> None:
        actual = parse('<start>: <foo> | <bar>;')
        self.assert_equal(actual, [Rule(Ref('start'), Union([Ref('foo'), Ref('bar')]))])

    def test_multiple_rules(self) -> None:
        actual = parse("""
            start: ('val' | 'var') id "=" expr;
            id: [A-Za-z_][A-Za-z0-9_]*;
            expr: [0-9]+ | id | '(' expr ')' | expr ('+' | '-') expr;
        """)
        self.assert_equal(actual, [
            Rule(Ref('start'), Concat([Union([Lit('val'), Lit('var')]), Ref('id'), Lit('='), Ref('expr')])),
            Rule(Ref('id'), Concat([CharClass('inclusive', [CharRange('A', 'Z'), CharRange('a', 'z'), '_']),
                                    Star(CharClass('inclusive', [CharRange('A', 'Z'), CharRange('a', 'z'),
                                                                 CharRange('0', '9'), '_']))])),
            Rule(Ref('expr'), Union([Plus(CharClass('inclusive', [CharRange('0', '9')])), Ref('id'),
                                     Concat([Lit('('), Ref('expr'), Lit(')')]),
                                     Concat([Ref('expr'), Union([Lit('+'), Lit('-')]), Ref('expr')])]))
        ])
