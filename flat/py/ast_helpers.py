import ast

# Factory methods

def mk_name(name: str) -> ast.Name:
    return ast.Name(name, ctx=ast.Load())

def mk_lambda(args: list[str], body: ast.expr) -> ast.Lambda:
    arguments = ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, [])
    return ast.Lambda(arguments, body)

def mk_call_runtime(name: str, *args: ast.expr) -> ast.expr:
    return ast.Call(ast.Name(name, ast.Load()), list(args), keywords=[])

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
