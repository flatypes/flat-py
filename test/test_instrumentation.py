import ast
import code
from textwrap import dedent
import unittest

from flat.py.diagnostics import Issuer
from flat.py.semantics import Context
from flat.py.instrumentation import Instrumentor

class TestInstrumentor(unittest.TestCase):
    def visit(self, code: str) -> str:
        issuer = Issuer()
        ctx = Context('<test>', issuer)
        instrumentor = Instrumentor(ctx)
        input = ast.parse(dedent(code), filename='<test>')
        output = instrumentor.visit(input)
        ast.fix_missing_locations(output)
        return ast.unparse(output)

    def test_literal_type(self):
        actual = self.visit(
            """\
            from typing import Literal

            def inc(x: Literal[1]) -> Literal[2]:
                return x + 1
            """)
        expected = dedent(
            """\
            from typing import Literal

            def inc(x: Literal[1]) -> Literal[2]:
                check_type(x, runtime.LiteralType([1]))
                __return__ = x + 1
                check_type(__return__, runtime.LiteralType([2]))
                return __return__""")
        self.assertEqual(actual, expected)