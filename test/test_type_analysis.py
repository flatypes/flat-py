import ast
import unittest

from flat.py.type_analysis import *

def analyze(type_code: str, defs: dict[str, Def] = {}) -> Type:
    expr = ast.parse(type_code, mode='eval').body
    issuer = Issuer()
    ctx = Context('<test>', issuer, defs)
    assert not issuer.has_errors()
    return analyze_type(expr, ctx)

class TestTypeAnalyzer(unittest.TestCase):
    def test_name_builtin(self):
        actual = analyze("str")
        self.assertEqual(actual, TypeName('str'))

    def test_name_alias(self):
        actual = analyze("Word", defs={'Word': TypeDef(TypeName('str'))})
        self.assertEqual(actual, TypeName('str'))

    def test_none_type(self):
        actual = analyze("None")
        self.assertEqual(actual, none_type)

    def test_lang_type(self):
        actual = analyze("""lang('start: A; A: "a";')""", defs={'lang': TypeConstrDef('flat.py.lang')})
        self.assertEqual(actual, LangType(0))

    def test_lang_regex(self):
        actual = analyze("""lang('a', format='regex')""", defs={'lang': TypeConstrDef('flat.py.lang')})
        self.assertEqual(actual, LangType(0))

    def test_refined_type(self):
        actual = analyze("refine(str, 'len(_) < 5')", defs={'refine': TypeConstrDef('flat.py.refine')})
        assert isinstance(actual, RefinedType)
        self.assertEqual(actual.base, TypeName('str'))
        self.assertEqual(ast.unparse(actual.predicate), 'lambda _: len(_) < 5')

    def test_tuple_type(self):
        actual = analyze("tuple[int, str, float]")
        expected = TupleType([TypeName('int'), TypeName('str'), TypeName('float')])
        self.assertEqual(actual, expected)

    def test_raw_tuple_type(self):
        actual = analyze("tuple")
        expected = TupleType([AnyType()], variant=True)
        self.assertEqual(actual, expected)

    def test_list_type(self):
        actual = analyze("List[str]", defs={'List': TypeConstrDef('list')})
        expected = ListType(TypeName('str'))
        self.assertEqual(actual, expected)

    def test_raw_list_type(self):
        actual = analyze("list")
        expected = ListType(AnyType())
        self.assertEqual(actual, expected)

    def test_set_type(self):
        actual = analyze("set[int]")
        expected = SetType(TypeName('int'))
        self.assertEqual(actual, expected)

    def test_raw_set_type(self):
        actual = analyze("set")
        expected = SetType(AnyType())
        self.assertEqual(actual, expected)

    def test_dict_type(self):
        actual = analyze("dict[str, int]")
        expected = DictType(TypeName('str'), TypeName('int'))
        self.assertEqual(actual, expected)

    def test_literal_type(self):
        actual = analyze("Literal[1, 'a']", defs={'Literal': TypeConstrDef('typing.Literal')})
        expected = LiteralType([1, 'a'])
        self.assertEqual(actual, expected)

    def test_literal_type_nested(self):
        actual = analyze("Literal[None, A, 10, Literal[-10]]", 
                         defs={'Literal': TypeConstrDef('typing.Literal'), 'A': TypeDef(LiteralType([1, 'a']))})
        expected = LiteralType([None, 1, 'a', 10, -10])
        self.assertEqual(actual, expected)

    def test_union_type(self):
        actual = analyze("int | str | float")
        expected = UnionType([TypeName('int'), TypeName('str'), TypeName('float')])
        self.assertEqual(actual, expected)

    def test_optional_type(self):
        actual = analyze("Optional[str]", defs={'Optional': TypeConstrDef('typing.Optional')})
        expected = UnionType([TypeName('str'), none_type])
        self.assertEqual(actual, expected)
