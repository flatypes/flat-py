import ast
import unittest
from textwrap import dedent
from typing import cast

from flat.py.checker import check
from flat.py.diagnostics import Issuer


def parse_module(code: str) -> ast.Module:
    return ast.parse(dedent(code), filename='<module>')


class Base(unittest.TestCase):
    def assert_ast_equal(self, actual: ast.AST, expected_code: str) -> None:
        ast.fix_missing_locations(actual)
        actual_code = ast.unparse(actual)
        self.assertEqual(actual_code, expected_code)

    def assert_rt_call_equal(self, actual: ast.AST, expected_rt_fun: str, *expected_args: str) -> None:
        assert isinstance(actual, ast.Expr)
        call = actual.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        self.assertEqual(call.func.attr, expected_rt_fun)
        for actual_arg, expected_arg in zip(call.args, expected_args):
            self.assertEqual(ast.unparse(actual_arg), expected_arg)


class TestCheckTypeAnnot(Base):
    def test_fun_annot(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def inc(x: Literal[1]) -> Literal[2]:
                return x + 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[0], 'check_arg_type', 'x', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-2], 'check_type', '_', 'rt.LitType([2])')

    def test_type_alias(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            type A = Literal[1]
            type B = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[0], 'check_arg_type', 'x', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-2], 'check_type', '_', 'rt.LitType([2])')

    def test_type_assign(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            A: type = Literal[1]
            B: type = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[0], 'check_arg_type', 'x', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-2], 'check_type', '_', 'rt.LitType([2])')


class TestCheckContractAnnot(Base):
    def test_requires(self) -> None:
        tree = parse_module(
            """\
            from flat.py import requires

            @requires('x > 0')
            def f(x: int) -> None:
                pass
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[1], 'check_pre', 'x > 0')

    def test_ensures(self) -> None:
        tree = parse_module(
            """\
            from flat.py import ensures

            @ensures('_ > x', '_ < 100')
            def f(x: int) -> int:
                return x + 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-3], 'check_post', '_ > x')
        self.assert_rt_call_equal(fun.body[-2], 'check_post', '_ < 100')

    def test_returns(self) -> None:
        tree = parse_module(
            """\
            from flat.py import returns

            @returns('x + 1')
            def f(x: int) -> int:
                return x + 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-2], 'check_post', '_ == x + 1')


class TestCheckAssign(Base):
    def test_simple(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1]
                x = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

    def test_ann(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

    def test_if(self) -> None:
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
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        if_stmt = cast(ast.If, fun.body[0])
        self.assert_rt_call_equal(if_stmt.body[-1], 'check_type', 'x', 'rt.LitType([1])')
        self.assert_rt_call_equal(if_stmt.orelse[-1], 'check_type', 'x', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

    def test_global(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                global x
                x = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

    def test_shadow_global(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                x = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_ast_equal(fun.body[-1], "x = 1")

    def test_nonlocal(self) -> None:
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
        actual = check(tree, Issuer(), with_lineno=False)
        outer_fun = cast(ast.FunctionDef, actual.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_rt_call_equal(inner_fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

    def test_shadow_nonlocal(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def outer() -> None:
                x: Literal[1]

                def inner(y) -> None:
                    x = y

                inner(1)
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        outer_fun = cast(ast.FunctionDef, actual.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_ast_equal(inner_fun.body[-1], "x = y")

    def test_list(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1]]
                xs[0] = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'xs[0]', 'rt.LitType([1])')

    def test_list_slice(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1, 2, 3]]
                xs[:3] = list(range(1, 4))
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'xs[:3]',
                                  'rt.ListType(rt.LitType([1, 2, 3]))')

    def test_dict(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                d: dict[Literal['a', 'b'], Literal[1, 2, 3]]
                d['a'] = 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-2], 'check_type', "'a'",
                                  "rt.LitType(['a', 'b'])")
        self.assert_rt_call_equal(fun.body[-1], 'check_type', "d['a']",
                                  "rt.LitType([1, 2, 3])")

    def test_multiple(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                a, b = b, a
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-2], 'check_type', 'a', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'b', 'rt.LitType([2])')

    def test_tuple(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                c: Literal[3] = 3
                ((a, b), c) = ((c, b), a)
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-3], 'check_type', 'a', 'rt.LitType([1])')
        self.assert_rt_call_equal(fun.body[-2], 'check_type', 'b', 'rt.LitType([2])')
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'c', 'rt.LitType([3])')

    def test_aug(self) -> None:
        tree = parse_module(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
                x += 1
            """)
        actual = check(tree, Issuer(), with_lineno=False)
        fun = cast(ast.FunctionDef, actual.body[-1])
        self.assert_rt_call_equal(fun.body[-1], 'check_type', 'x', 'rt.LitType([1])')

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
