import ast
from textwrap import dedent
from typing import cast
import unittest

from flat.py.diagnostics import *
from flat.py.semantics import Context
from flat.py.instrumentation import Instrumentor

class TestInstrumentor(unittest.TestCase):
    def process(self, code: str) -> ast.Module:
        issuer = Issuer()
        ctx = Context('<test>', issuer)
        instrumentor = Instrumentor(ctx)
        input = ast.parse(dedent(code), filename='<test>')
        output = instrumentor.visit(input)
        ast.fix_missing_locations(output)
        return output
    
    def assert_ast_equal(self, actual: ast.AST, expected_code: str):
        actual_code = ast.unparse(actual)
        self.assertEqual(actual_code, expected_code)

    def test_basic_type_annotation(self):
        tree = self.process(
            """\
            from typing import Literal

            def inc(x: Literal[1]) -> Literal[2]:
                return x + 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_type_alias(self):
        tree = self.process(
            """\
            from typing import Literal

            type A = Literal[1]
            type B = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_type_assign(self):
        tree = self.process(
            """\
            from typing import Literal

            A: type = Literal[1]
            B: type = Literal[2]
            def inc(x: A) -> B:
                return x + 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[0], "rt.check_type(x, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(__return__, rt.LiteralType([2]))")

    def test_ann_assign(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1]
                x = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_conditional(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                if ...:
                    x: Literal[1] = 1
                else:
                    x = 2
                x = 3
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        check = "rt.check_type(x, rt.LiteralType([1]))"
        if_stmt = cast(ast.If, fun.body[0])
        self.assert_ast_equal(if_stmt.body[-1], check)
        self.assert_ast_equal(if_stmt.orelse[-1], check)
        self.assert_ast_equal(fun.body[-1], check)

    def test_assign_global(self):
        tree = self.process(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                global x
                x = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_shadow_global(self):
        tree = self.process(
            """\
            from typing import Literal

            x: Literal[1]

            def f() -> None:
                x = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "x = 1")

    def test_assign_nonlocal(self):
        tree = self.process(
            """\
            from typing import Literal

            def outer() -> None:
                x: Literal[1]

                def inner(y) -> None:
                    nonlocal x
                    x = y

                inner(1)
            """)
        outer_fun = cast(ast.FunctionDef, tree.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_ast_equal(inner_fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

    def test_assign_shadow_nonlocal(self):
        tree = self.process(
            """\
            from typing import Literal

            def outer() -> None:
                x: Literal[1]

                def inner(y) -> None:
                    x = y

                inner(1)
            """)
        outer_fun = cast(ast.FunctionDef, tree.body[-1])
        inner_fun = cast(ast.FunctionDef, outer_fun.body[-2])
        self.assert_ast_equal(inner_fun.body[-1], "x = y")

    def test_assign_list_index(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1]]
                xs[0] = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(xs[0], rt.LiteralType([1]))")

    def test_assign_list_slice(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                xs: list[Literal[1, 2, 3]]
                xs[:3] = list(range(1, 4))
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(xs[:3], rt.ListType(rt.LiteralType([1, 2, 3])))")

    def test_assign_dict_key(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                d: dict[Literal['a', 'b'], Literal[1, 2, 3]]
                d['a'] = 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-2], "rt.check_type('a', rt.LiteralType(['a', 'b']))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(d['a'], rt.LiteralType([1, 2, 3]))")

    def test_assign_targets(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                a, b = b, a
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-2], "rt.check_type(a, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(b, rt.LiteralType([2]))")

    def test_assign_tuple(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                a: Literal[1] = 1
                b: Literal[2] = 2
                c: Literal[3] = 3
                ((a, b), c) = ((c, b), a)
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-3], "rt.check_type(a, rt.LiteralType([1]))")
        self.assert_ast_equal(fun.body[-2], "rt.check_type(b, rt.LiteralType([2]))")
        self.assert_ast_equal(fun.body[-1], "rt.check_type(c, rt.LiteralType([3]))")

    def test_aug_assign(self):
        tree = self.process(
            """\
            from typing import Literal

            def f() -> None:
                x: Literal[1] = 1
                x += 1
            """)
        fun = cast(ast.FunctionDef, tree.body[-1])
        self.assert_ast_equal(fun.body[-1], "rt.check_type(x, rt.LiteralType([1]))")

class TestInstrumentorNegative(unittest.TestCase):
    def process(self, code: str) -> Diagnostic:
        issuer = Issuer()
        ctx = Context('<test>', issuer)
        instrumentor = Instrumentor(ctx)
        input = ast.parse(dedent(code), filename='<test>')
        instrumentor.visit(input)
        errors = issuer.get_errors()
        if len(errors) == 1:
            return errors[0]
        else:
            self.fail(f"Expected one error, got {len(errors)}:\n{issuer.pretty()}")
    
    def test_redefine(self):
        diagnostic = self.process(
            """\
            from typing import Literal

            def f() -> None:
                x = 1
                x: Literal[2] = 2
            """)
        self.assertIsInstance(diagnostic, RedefinedName)
