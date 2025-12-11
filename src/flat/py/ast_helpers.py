import ast
from typing import Sequence

__all__ = ['mk_tuple', 'mk_list', 'mk_eq', 'mk_call', 'mk_lambda', 'mk_assign',
           'mk_call_rt', 'mk_import_from', 'mk_foreach', 'mk_get_item',
           'mk_attr', 'erase_arguments_ann',
           'get_type_args', 'get_left_values', 'get_operands', 'to_expr',
           'pure']


# Factory methods

def mk_tuple(*elems: int | str | ast.expr) -> ast.expr:
    elts: list[ast.expr] = []
    for elem in elems:
        if isinstance(elem, (int, str)):
            elts.append(ast.Constant(elem))
        else:
            elts.append(elem)

    return ast.Tuple(elts)


def mk_list(*elems: ast.expr | str) -> ast.expr:
    elts: list[ast.expr] = []
    for elem in elems:
        if isinstance(elem, str):
            elts.append(ast.Constant(elem))
        else:
            elts.append(elem)

    return ast.List(elts)


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


def mk_get_item(container: ast.expr, index: ast.expr) -> ast.expr:
    return ast.Subscript(container, index)


def mk_call_rt(name: str, *args: ast.expr) -> ast.expr:
    return mk_call(ast.Attribute(ast.Name(f'rt'), name), *args)


def mk_import_from(module: str, name: str, *, as_name: str | None = None) -> ast.stmt:
    return ast.ImportFrom(module, [ast.alias(name, as_name)], 0)


def erase_arguments_ann(args: ast.arguments) -> ast.arguments:
    return ast.arguments([ast.arg(arg.arg) for arg in args.posonlyargs],
                         [ast.arg(arg.arg) for arg in args.args],
                         ast.arg(args.vararg.arg) if args.vararg else None,
                         [ast.arg(arg.arg) for arg in args.kwonlyargs],
                         args.kw_defaults,
                         ast.arg(args.kwarg.arg) if args.kwarg else None,
                         args.defaults)


type PositionRange = tuple[int, int, int, int]
"""Position range of AST node: (lineno, end_lineno, col_offset, end_col_offset).
Note: end_col_offset is exclusive.
"""


def get_position_range(node: ast.AST) -> PositionRange:
    start_line = getattr(node, 'lineno')
    end_line = getattr(node, 'end_lineno', start_line)
    start_col = getattr(node, 'col_offset')
    end_col = getattr(node, 'end_col_offset')
    return start_line, end_line, start_col, end_col


def mk_position_range(node: ast.AST) -> ast.expr:
    return mk_tuple(*get_position_range(node))


# Extractors

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


def get_operands(expr: ast.expr, op: type[ast.operator]) -> list[ast.expr]:
    """Gets the operands of a binary operation AST."""
    match expr:
        case ast.BinOp(left, o, right) if isinstance(o, op):
            return get_operands(left, op) + get_operands(right, op)
        case _:
            return [expr]


def to_expr(expr: ast.expr) -> ast.expr:
    match expr:
        case ast.Constant(str() as s):
            return ast.parse(s, mode='eval').body
        case _:
            return expr


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


# def check_args(call: ast.Call, required: list[str], optional: list[tuple[str, ast.expr]] = []) -> list[ast.expr]:
#     args: dict[str, ast.expr] = {}
#     names = required + [x for x, _ in optional]
#     for e, x in zip(call.args, names):
#         args[x] = e
#     for kw in call.keywords:
#         if kw.arg in names:
#             if kw.arg not in args:
#                 args[kw.arg] = kw.value
#             else:
#                 raise TypeError(f"Argument '{kw.arg}' repeated.")
#         else:
#             raise TypeError(f"Unexpected keyword argument '{kw.arg}'.")

#     missing = set(required) - args.keys()
#     if len(missing) > 0:
#         raise TypeError(f"Missing required arguments: {', '.join(missing)}.")

#     for x, default in optional:
#         if x not in args:
#             args[x] = default

#     return [args[x] for x in names]

# Binary operations


# Range

def pure(expr: ast.expr) -> bool:
    """Tests whether an expression is pure. This implementation is conservative (sound but incomplete)."""
    match expr:
        case ast.Constant() | ast.Name():
            return True
        case ast.UnaryOp(_, e):
            return pure(e)
        case ast.BinOp(e1, _, e2):
            return pure(e1) and pure(e2)
        case ast.Attribute(e, _):
            return pure(e)
        case ast.Subscript(e, ei):
            return pure(e) and pure(ei)
        case ast.Slice(e1, e2, e3):
            return (e1 is None or pure(e1)) and (e2 is None or pure(e2)) and (e3 is None or pure(e3))
        case _:
            return False
