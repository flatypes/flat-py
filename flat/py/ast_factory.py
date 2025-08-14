import ast
from typing import Any, Callable


def mk_assign(var: str, value: ast.expr | int) -> ast.stmt:
    """Create an AST assignment statement."""
    if isinstance(value, int):
        value = ast.Constant(value)
    return ast.Assign([ast.Name(var, ctx=ast.Store())], value)


def to_attr(full_name: str) -> ast.Attribute:
    """Convert a full name to an AST attribute."""
    parts = full_name.split('.')
    if len(parts) == 1 or (len(parts) == 2 and parts[0] == 'builtins'):
        return ast.Name(parts[-1], ctx=ast.Load())
    return ast.Attribute(to_attr('.'.join(parts[:-1])), parts[-1], ctx=ast.Load())


def mk_call_flat(func: Callable, *args: ast.expr | int | str) -> ast.expr:
    """Create an AST call expression for a function/constructor in the 'flat' module."""
    f = to_attr(func.__module__ + '.' + func.__qualname__)
    es = []
    for arg in args:
        match arg:
            case int() as n:
                es += [ast.Constant(n)]
            case str() as s:
                es += [ast.Constant(s)]
            case ast.expr() as e:
                es += [e]
    return ast.Call(f, es, keywords=[])


def mk_invoke_flat(func: Callable, *args: int | str | ast.expr) -> ast.stmt:
    """Create an AST statement for invoking a function/constructor in the 'flat' module."""
    return ast.Expr(mk_call_flat(func, *args))


# def lambda_expr(args: list[str], body: ast.expr) -> ast.Lambda:
# return ast.Lambda(ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, []), body)

def mk_and(values: list[ast.expr]) -> ast.expr:
    """Create an AST boolean AND operation."""
    match len(values):
        case 0:
            return ast.Constant(True)
        case 1:
            return values[0]
        case _:
            return ast.BoolOp(ast.And(), values)


def to_expr(obj: Any) -> ast.expr:
    """Convert a Python object to an AST expression."""
    match obj:
        case ast.expr() as e:
            return e
        case str() as s:
            return ast.Constant(s)
        case bool() as b:
            return ast.Constant(b)
        case int() as i:
            return ast.Constant(i)
        case None:
            return ast.Constant(None)
        case list() as xs:
            return ast.List([to_expr(x) for x in xs])
        case tuple() as xs:
            return ast.Tuple([to_expr(x) for x in xs])
        case dict() as d:
            return ast.Dict([to_expr(k) for k in d.keys()], [to_expr(v) for v in d.values()])
        case _:
            if hasattr(obj, '__dataclass_fields__'):
                if type(obj) is type:
                    return to_attr(obj.__module__ + '.' + obj.__qualname__)
                if type(type(obj)) is type:
                    attr = to_attr(obj.__class__.__module__ + '.' + obj.__class__.__qualname__)
                    args = [to_expr(getattr(obj, x)) for x in obj.__match_args__]
                    return ast.Call(attr, args, keywords=[])

            raise ValueError(f"Cannot convert `{obj}` of type {type(obj)} to an AST expression.")


def parse_expr(code: str) -> ast.expr:
    """Parse a string into an AST expression."""
    return ast.parse(code, mode='eval').body
