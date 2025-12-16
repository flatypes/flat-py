import ast
import string
import unittest
from typing import Mapping

from flat.backend.lang import NT, Lang
from flat.py.analyzer import analyze_lang, analyze
from flat.py.compile_time import *


class TestAnalyzeLang(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Context('<test>', Issuer())

    def assert_equal(self, actual: LangType | AnyType, expected: Lang) -> None:
        match actual:
            case LangType(lang):
                self.assertFalse(self.ctx.issuer.has_errors)
                self.assertDictEqual(lang, expected)
            case AnyType():
                self.fail(f"Expected language, but got error: {self.ctx.issuer.pretty()}")

    def assert_error(self, actual: LangType | AnyType, typ: type[Diagnostic]) -> None:
        match actual:
            case AnyType():
                errs = [d for d in self.ctx.issuer.get_diagnostics() if d.level == Level.ERROR]
                if len(errs) != 1:
                    self.fail(f"Multiple errors ({len(errs)}): {self.ctx.issuer.pretty()}")
                elif not isinstance(errs[0], typ):
                    self.fail(f"Expected {typ.__name__}, but got {type(errs[0]).__name__}")
            case LangType(lang):
                self.fail(f"Expected error, but got language: {lang}")

    def assert_diagnostic(self, typ: type[Diagnostic]) -> None:
        diagnostics = list(self.ctx.issuer.get_diagnostics())
        if len(diagnostics) != 1:
            self.fail(f"Multiple diagnostics ({len(diagnostics)}): {self.ctx.issuer.pretty()}")
        elif not isinstance(diagnostics[0], typ):
            self.fail(f"Expected {typ.__name__}, but got {type(diagnostics[0]).__name__}")

    def test_char_class(self) -> None:
        actual = analyze_lang('[a-c+*]', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [[NT('@1')]], '@1': [['a'], ['b'], ['c'], ['+'], ['*']]})

    def test_empty_char_range(self) -> None:
        actual = analyze_lang('[ad-b]', self.ctx, syntax='regex')
        self.assert_diagnostic(EmptyRange)
        self.assert_equal(actual, {'start': [['a']]})

    def test_union(self) -> None:
        actual = analyze_lang('a|b|c', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [['a'], ['b'], ['c']]})

    def test_nested_union(self) -> None:
        actual = analyze_lang('x(a|b)', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [['x', NT('@1')]], '@1': [['a'], ['b']]})

    def test_star(self) -> None:
        actual = analyze_lang('a*', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [[NT('@1')]], '@1': [[], ['a', NT('@1')]]})

    def test_plus(self) -> None:
        actual = analyze_lang('ab+', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [['a', NT('@1')]], '@1': [['b'], ['b', NT('@1')]]})

    def test_optional(self) -> None:
        actual = analyze_lang('a?b', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [[NT('@1'), 'b']], '@1': [[], ['a']]})

    def test_power(self) -> None:
        actual = analyze_lang('a{3}b{1}c{0}', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [['a', 'a', 'a', 'b']]})

    def test_loop(self) -> None:
        actual = analyze_lang('a{2,4}b{3,}c{,2}', self.ctx, syntax='regex')
        self.assert_equal(actual, {'start': [['a', 'a', NT('@1'), 'b', 'b', 'b', NT('@2'), NT('@3')]],
                                   '@1': [[], ['a'], ['a', 'a']],
                                   '@2': [[], ['b', NT('@2')]],
                                   '@3': [[], ['c'], ['c', 'c']]})

    def test_empty_loop_range(self) -> None:
        actual = analyze_lang('ab{5,3}', self.ctx, syntax='regex')
        self.assert_diagnostic(EmptyRange)
        self.assert_equal(actual, {'start': [['a']]})

    def test_cfg(self) -> None:
        actual = analyze_lang("""
            S: '(' S ')' | 'a' | B;
            B: ('+'|'-') [0-9]+;
        """, self.ctx)
        self.assert_equal(actual, {'S': [['(', NT('S'), ')'], ['a'], [NT('B')]],
                                   'B': [[NT('@1'), NT('@2')]],
                                   '@1': [['+'], ['-']],
                                   '@2': [[NT('@3')], [NT('@3'), NT('@2')]],
                                   '@3': [[c] for c in string.digits]})


def parse_expr(code: str) -> ast.expr:
    return ast.parse(code, mode='eval').body


def mk_ctx(defs: Mapping[str, Def] = {}) -> Context:
    return Context('<test>', Issuer(), defs)


class TestAnalyze(unittest.TestCase):
    def test_name_builtin(self) -> None:
        annot = parse_expr('str')
        actual = analyze(annot, mk_ctx())
        self.assertEqual(actual, BuiltinType('str'))

    def test_name_alias(self) -> None:
        annot = parse_expr('Word')
        actual = analyze(annot, mk_ctx({'Word': TypeDef(BuiltinType('str'))}))
        self.assertEqual(actual, BuiltinType('str'))

    def test_none_type(self) -> None:
        annot = parse_expr('None')
        actual = analyze(annot, mk_ctx())
        self.assertEqual(actual, none_type)

    def test_lang_type(self) -> None:
        annot = parse_expr("""lang('start: "a";')""")
        actual = analyze(annot, mk_ctx({'lang': TypeConstrDef('flat.py.lang')}))
        self.assertEqual(actual, LangType({'start': [['a']]}))

    def test_lang_regex(self) -> None:
        annot = parse_expr("lang('a', syntax='regex')")
        actual = analyze(annot, mk_ctx({'lang': TypeConstrDef('flat.py.lang')}))
        self.assertEqual(actual, LangType({'start': [['a']]}))

    def test_refined_type(self) -> None:
        annot = parse_expr("refine(str, 'len(_) < 5')")
        actual = analyze(annot, mk_ctx({'refine': TypeConstrDef('flat.py.refine')}))
        assert isinstance(actual, RefinedType)
        self.assertEqual(actual.base, BuiltinType('str'))
        self.assertEqual(ast.unparse(actual.conds[0]), 'len(_) < 5')

    def test_tuple_type(self) -> None:
        annot = parse_expr('tuple[int, str, float]')
        actual = analyze(annot, mk_ctx())
        expected = TupleType([BuiltinType('int'), BuiltinType('str'), BuiltinType('float')])
        self.assertEqual(actual, expected)

    def test_list_type(self) -> None:
        annot = parse_expr('List[str]')
        actual = analyze(annot, mk_ctx({'List': TypeConstrDef('list')}))
        expected = ListType(BuiltinType('str'))
        self.assertEqual(actual, expected)

    def test_set_type(self) -> None:
        annot = parse_expr('set[int]')
        actual = analyze(annot, mk_ctx())
        expected = SetType(BuiltinType('int'))
        self.assertEqual(actual, expected)

    def test_dict_type(self) -> None:
        annot = parse_expr('dict[str, int]')
        actual = analyze(annot, mk_ctx())
        expected = DictType(BuiltinType('str'), BuiltinType('int'))
        self.assertEqual(actual, expected)

    def test_literal_type(self) -> None:
        annot = parse_expr("Literal[1, 'a']")
        actual = analyze(annot, mk_ctx({'Literal': TypeConstrDef('typing.Literal')}))
        expected = LitType([1, 'a'])
        self.assertEqual(actual, expected)

    def test_literal_type_nested(self) -> None:
        annot = parse_expr('Literal[None, A, 10, Literal[-10]]')
        actual = analyze(annot, mk_ctx({'Literal': TypeConstrDef('typing.Literal'), 'A': TypeDef(LitType([1, 'a']))}))
        expected = LitType([None, 1, 'a', 10, -10])
        self.assertEqual(actual, expected)

    def test_union_type(self) -> None:
        annot = parse_expr('int | str | float')
        actual = analyze(annot, mk_ctx())
        expected = UnionType([BuiltinType('int'), BuiltinType('str'), BuiltinType('float')])
        self.assertEqual(actual, expected)

    def test_optional_type(self) -> None:
        annot = parse_expr('Optional[str]')
        actual = analyze(annot, mk_ctx({'Optional': TypeConstrDef('typing.Optional')}))
        expected = UnionType([BuiltinType('str'), none_type])
        self.assertEqual(actual, expected)
