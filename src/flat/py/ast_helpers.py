import ast

from flat.py.diagnostics import Position, Range

__all__ = ["mk_assign", "mk_lambda", "mk_call", "mk_call_rt",
           "get_type_args", "get_left_values", "get_operands",
           "get_range", "pure"]


# Factory methods

def mk_assign(target: str, value: ast.expr) -> ast.stmt:
    return ast.Assign([ast.Name(target, ctx=ast.Store())], value)


def mk_lambda(args: list[str], body: ast.expr) -> ast.Lambda:
    arguments = ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, [])
    return ast.Lambda(arguments, body)


def mk_call(func: ast.expr, *args: ast.expr) -> ast.expr:
    return ast.Call(func, list(args), [])


def mk_call_rt(name: str, *args: ast.expr) -> ast.expr:
    return mk_call(ast.Attribute(ast.Name(f'rt'), name), *args)


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

def get_range(node: ast.AST) -> Range:
    if hasattr(node, 'lineno') and hasattr(node, 'col_offset'):
        start = Position(node.lineno, node.col_offset + 1)
        if hasattr(node, 'end_lineno') and hasattr(node, 'end_col_offset'):
            end = Position(node.end_lineno, node.end_col_offset + 1)
        else:
            end = start
        return Range(start, end)

    raise ValueError("AST node does not have position information.")


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
