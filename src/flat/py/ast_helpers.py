import ast
from dataclasses import is_dataclass, astuple
from typing import Sequence, Mapping

__all__ = ['mk_eq', 'mk_attr', 'mk_call', 'mk_lambda', 'mk_assign', 'mk_foreach', 'mk_import_from',
           'erase_ann', 'get_type_args', 'get_left_values', 'get_operands', 'is_ellipsis', 'is_pure',
           'ExprSerializer']


def mk_eq(left: ast.expr, right: ast.expr) -> ast.expr:
    return ast.Compare(left, [ast.Eq()], [right])


def mk_attr(path: str) -> ast.expr:
    parts = path.split('.')
    expr: ast.expr = ast.Name(parts[0], ctx=ast.Load())
    for part in parts[1:]:
        expr = ast.Attribute(expr, part, ctx=ast.Load())
    return expr


def mk_call(fun: ast.expr | str, *args: ast.expr | int | str) -> ast.expr:
    fun_node = mk_attr(fun) if isinstance(fun, str) else fun
    arg_nodes: list[ast.expr] = []
    for arg in args:
        if isinstance(arg, (int, str)):
            arg_nodes.append(ast.Constant(arg))
        else:
            arg_nodes.append(arg)

    return ast.Call(fun_node, arg_nodes, [])


def mk_lambda(args: Sequence[str], body: ast.expr) -> ast.Lambda:
    arguments = ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, [])
    return ast.Lambda(arguments, body)


def mk_assign(target: str, value: ast.expr) -> ast.stmt:
    return ast.Assign([ast.Name(target, ctx=ast.Store())], value)


def mk_foreach(target: str, iterator: ast.expr, body: list[ast.stmt]) -> ast.stmt:
    return ast.For(ast.Name(target), iterator, body, [])


def mk_import_from(module: str, name: str, *, as_name: str | None = None) -> ast.stmt:
    return ast.ImportFrom(module, [ast.alias(name, as_name)], 0)


def erase_ann(arguments: ast.arguments) -> ast.arguments:
    return ast.arguments([ast.arg(arg.arg) for arg in arguments.posonlyargs],
                         [ast.arg(arg.arg) for arg in arguments.args],
                         ast.arg(arguments.vararg.arg) if arguments.vararg else None,
                         [ast.arg(arg.arg) for arg in arguments.kwonlyargs],
                         arguments.kw_defaults,
                         ast.arg(arguments.kwarg.arg) if arguments.kwarg else None,
                         arguments.defaults)


def get_type_args(subscript: ast.Subscript) -> list[ast.expr]:
    match subscript.slice:
        case ast.Tuple(es):
            return es
        case e:
            return [e]


def get_left_values(target: ast.expr) -> list[ast.expr]:
    extractor = LeftValueExtractor()
    extractor.visit(target)
    return extractor.left_values


class LeftValueExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.left_values: list[ast.expr] = []

    def visit_Name(self, node: ast.Name) -> None:
        self.left_values.append(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.left_values.append(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        self.left_values.append(node)


def get_operands(expr: ast.expr, op: type[ast.operator]) -> list[ast.expr]:
    """Gets the operands of a binary operation AST."""
    match expr:
        case ast.BinOp(left, o, right) if isinstance(o, op):
            return get_operands(left, op) + get_operands(right, op)
        case _:
            return [expr]


def is_ellipsis(expr: ast.expr) -> bool:
    """Tests whether an expression is an ellipsis."""
    return isinstance(expr, ast.Constant) and expr.value is Ellipsis


def is_pure(expr: ast.expr) -> bool:
    """Tests whether an expression is pure. This implementation is conservative (sound but incomplete)."""
    match expr:
        case ast.Constant() | ast.Name():
            return True
        case ast.UnaryOp(_, e):
            return is_pure(e)
        case ast.BinOp(e1, _, e2):
            return is_pure(e1) and is_pure(e2)
        case ast.Attribute(e, _):
            return is_pure(e)
        case ast.Subscript(e, ei):
            return is_pure(e) and is_pure(ei)
        case ast.Slice(e1, e2, e3):
            return (e1 is None or is_pure(e1)) and (e2 is None or is_pure(e2)) and (e3 is None or is_pure(e3))
        case _:
            return False


class ExprSerializer:
    def __init__(self, recognized_modules: Mapping[str, str]) -> None:
        self.recognized_modules = recognized_modules

    def serialize(self, value: object) -> ast.expr:
        """Build an AST expression that represents the given value."""
        if isinstance(value, (int, bool, str)):
            return ast.Constant(value)

        if value is None:
            return ast.Constant(None)

        if isinstance(value, Sequence):
            return ast.List([self.serialize(elem) for elem in value])

        if isinstance(value, Mapping):
            return ast.Dict([self.serialize(k) for k in value.keys()],
                            [self.serialize(v) for v in value.values()])

        if is_dataclass(value):
            module_name = type(value).__module__
            if module_name in self.recognized_modules:
                constr = self.recognized_modules[module_name] + '.' + type(value).__qualname__
                args = astuple(value)  # type: ignore
                return mk_call(constr, *[self.serialize(arg) for arg in args])

        raise ValueError(f"Cannot serialize value {repr(value)} of "
                         f"type '{type(value).__module__}.{type(value).__qualname__}'")
