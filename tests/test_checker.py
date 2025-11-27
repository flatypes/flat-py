import ast
import unittest
from textwrap import dedent
from typing import cast

from flat.py.checker import check
from flat.py.diagnostics import Issuer


def parse_module(code: str) -> ast.Module:
    return ast.parse(dedent(code), filename='<module>')


class TestChecker(unittest.TestCase):
    def assert_ast_equal(self, actual: ast.AST, expected_code: str) -> None:
        ast.fix_missing_locations(actual)
        actual_code = ast.unparse(actual)
        self.assertEqual(actual_code, expected_code)

    def test_basic_type_annotation(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def inc(x: Literal[1]) -> Literal[2]:
                return x + 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_type_alias(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            type A = Literal[1]
            type B = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_type_assign(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            A: type = Literal[1]
            B: type = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_ann_assign(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1]
                x = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_conditional(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                if ...:
                    x: Literal[1] = 1
                else:
                    x = 2
                x = 3
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        ct = "rt.check_type(x, rt.LiteralType([1]))"
        if_stmt = cast(ast.If, fun.body[0])
        self.assert_ast_equal(if_stmt.body[-1], ct)
        self.assert_ast_equal(if_stmt.orelse[-1], ct)
        self.assert_ast_equal(fun.body[-1], ct)

    def test_assign_global(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                global x
                x = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_shadow_global(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                x = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "x = 1")

    def test_assign_nonlocal(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def outer() -> None:
                x: Literal[1]

                def inner(y) -> None:
                    nonlocal x
                    x = y

                inner(1)
            """)
        actual = check(tree, Issuer())
        outer_fun = cast(ast.FunctionDef, actual.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_ast_equal(inner_fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_shadow_nonlocal(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def outer() -> None:
                x: Literal[1]

                def inner(y) -> None:
                    x = y

                inner(1)
            """)
        actual = check(tree, Issuer())
        outer_fun = cast(ast.FunctionDef, actual.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_ast_equal(inner_fun.body[-1], "x = y")

    def test_assign_list_index(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1]]
                xs[0] = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(xs[0], rt.LiteralType([1]))")

    def test_assign_list_slice(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1, 2, 3]]
                xs[:3] = list(range(1, 4))
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(xs[:3], rt.ListType(rt.LiteralType([1, 2, 3])))")

    def test_assign_dict_key(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                d: dict[Literal['a', 'b'], Literal[1, 2, 3]]
                d['a'] = 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-2], "rt.check_type('a', rt.LiteralType(['a', 'b']))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(d['a'], rt.LiteralType([1, 2, 3]))")

    def test_assign_targets(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                a, b = b, a
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-2], "rt.check_type(a, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(b, rt.LiteralType([2]))")

    def test_assign_tuple(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                c: Literal[3] = 3
                ((a, b), c) = ((c, b), a)
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-3], "rt.check_type(a, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(b, rt.LiteralType([2]))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(c, rt.LiteralType([3]))")

    def test_aug_assign(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
                x += 1
            """)
        actual = check(tree, Issuer())
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

# class TestInstrumentorNegative(unittest.TestCase):
#     def process(self, code: str) -> Diagnostic:
#         issuer = Issuer()
#         ctx = Context('<test>', issuer)
#         instrumentor = Instrumentor(ctx)
#         input = ast.parse(dedent(code), filename='<test>')
#         instrumentor.visit(input)
#         errors = issuer.get_diagnostics()
#         self.assertEqual(len(errors), 1)
#         return errors[0]

#     def test_redefine(self):
#         diagnostic = self.process(
#             """\
#             from typing import Literal

#             def f() -> None:
#                 x = 1
#                 x: Literal[2] = 2
#             """)
#         self.assertIsInstance(diagnostic, RedefinedName)
