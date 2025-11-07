import ast

from flat.py.diagnostics import Position, Range

# Factory methods

def mk_name(name: str) -> ast.Name:
    return ast.Name(name, ctx=ast.Load())

def mk_lambda(args: list[str], body: ast.expr) -> ast.Lambda:
    arguments = ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, [])
    return ast.Lambda(arguments, body)

def mk_call(func: ast.expr, *args: ast.expr) -> ast.expr:
    return ast.Call(func, list(args), [])

def mk_call_method(receiver: ast.expr, method: str, *args: ast.expr) -> ast.expr:
    return ast.Call(ast.Attribute(receiver, method), list(args), [])

def mk_assign(target: str, value: ast.expr) -> ast.stmt:
    return ast.Assign([mk_name(target)], value)

def mk_call_runtime(name: str, *args: ast.expr) -> ast.expr:
    return mk_call_method(mk_name(f'runtime'), name, *args)

def mk_rt(name: str, *args: ast.expr) -> ast.stmt:
    return ast.Expr(ast.Call(ast.Name(name, ast.Load()), list(args), []))

def get_left_vars(left_value: ast.expr) -> list[str]:
    match left_value:
        case ast.Name(x):
            return [x]
        case ast.Tuple(es):
            return [x for e in es for x in get_left_vars(e)]
        case _:
            return []

# Arguments

def get_type_args(subscript: ast.Subscript) -> list[ast.expr]:
    match subscript.slice:
        case ast.Tuple(es):
            return es
        case e:
            return [e]

def check_args(call: ast.Call, required: list[str], optional: list[tuple[str, ast.expr]] = []) -> list[ast.expr]:
    args: dict[str, ast.expr] = {}
    names = required + [x for x, _ in optional]
    for e, x in zip(call.args, names):
        args[x] = e
    for kw in call.keywords:
        if kw.arg in names:
            if kw.arg not in args:
                args[kw.arg] = kw.value
            else:
                raise TypeError(f"Argument '{kw.arg}' repeated.")
        else:
            raise TypeError(f"Unexpected keyword argument '{kw.arg}'.")
    
    missing = set(required) - args.keys()
    if len(missing) > 0:
        raise TypeError(f"Missing required arguments: {', '.join(missing)}.")

    for x, default in optional:
        if x not in args:
            args[x] = default

    return [args[x] for x in names]

# Binary operations

def get_operands(expr: ast.expr, op: type[ast.operator]) -> list[ast.expr]:
    """Gets the operands of a binary operation AST."""
    match expr:
        case ast.BinOp(left, o, right) if isinstance(o, op):
            return get_operands(left, op) + get_operands(right, op)
        case _:
            return [expr]

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