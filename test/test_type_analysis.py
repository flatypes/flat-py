import ast
import unittest
from textwrap import dedent

from flat.py.type_analysis import *

def analyze(type_code: str, imports: dict[str, str] = {}, aliases: dict[str, Type] = {}) -> Type:
    expr = ast.parse(type_code, mode='eval').body
    analyzer = TypeAnalyzer(imports, aliases)
    type_tree = analyzer.visit(expr)
    return type_tree

class TestTypeAnalyzer(unittest.TestCase):
    def test_name_builtin(self):
        actual = analyze("str")
        self.assertEqual(actual, TypeName('str'))

    def test_name_alias(self):
        actual = analyze("A", aliases={'A': TypeName('str')})
        self.assertEqual(actual, TypeName('A'))

    def test_none_type(self):
        actual = analyze("None")
        self.assertEqual(actual, none_type)

    def test_tuple_type(self):
        actual = analyze("tuple[int, str, float]")
        expected = TupleType([TypeName('int'), TypeName('str'), TypeName('float')])
        self.assertEqual(actual, expected)

    def test_list_type(self):
        actual = analyze("List[str]", imports={'List': 'list'})
        expected = ListType(TypeName('str'))
        self.assertEqual(actual, expected)

    def test_set_type(self):
        actual = analyze("set[int]")
        expected = SetType(TypeName('int'))
        self.assertEqual(actual, expected)

    def test_dict_type(self):
        actual = analyze("dict[str, int]", imports={'Dict': 'dict'})
        expected = DictType(TypeName('str'), TypeName('int'))
        self.assertEqual(actual, expected)

    def test_literal_type(self):
        actual = analyze("Literal[1, 'a']", imports={'Literal': 'typing.Literal'})
        expected = LiteralType([1, 'a'])
        self.assertEqual(actual, expected)

    def test_literal_type_nested(self):
        actual = analyze("Literal[None, A, 10, Literal[-10]]", imports={'Literal': 'typing.Literal'},
                         aliases={'A': LiteralType([1, 'a'])})
        expected = UnionType([LiteralType([None, 10]), TypeName('A'), LiteralType([-10])])
        self.assertEqual(actual, expected)

    def test_union_type(self):
        actual = analyze("int | str | float")
        expected = UnionType([TypeName('int'), TypeName('str'), TypeName('float')])
        self.assertEqual(actual, expected)

    def test_optional_type(self):
        actual = analyze("Optional[str]", imports={'Optional': 'typing.Optional'})
        expected = UnionType([TypeName('str'), none_type])
        self.assertEqual(actual, expected)

    def test_invalid_type(self):
        with self.assertRaises(TypeError):
            analyze("-str")
