import ast

# operators

unary_ops = ['prefix_-', 'prefix_!']
py_unary_ops: list[ast.unaryop] = [ast.USub(), ast.Not()]

binary_ops = ['+', '-', '*', '/', '%']
py_binary_ops: list[ast.operator] = [ast.Add(), ast.Sub(), ast.Mult(), ast.FloorDiv(), ast.Mod()]

bool_ops = ['&&', '||']
py_bool_ops: list[ast.boolop] = [ast.And(), ast.Or()]

compare_ops = ['>=', '<=', '>', '<', '==', '!=']
py_compare_ops: list[ast.cmpop] = [ast.GtE(), ast.LtE(), ast.Gt(), ast.Lt(), ast.Eq(), ast.NotEq()]

ops = unary_ops + binary_ops + bool_ops + compare_ops


# library functions

def length(s: str) -> int:
    return len(s)


def concat(s1: str, s2: str) -> str:
    return s1 + s2


def nth(s: str, i: int) -> str:
    return s[i]


def substring(s: str, start: int, end: int) -> str:
    return s[start:end]


def contains(s: str, s1: str) -> bool:
    return s1 in s


def find(s: str, s1: str) -> int:
    return s.find(s1)


def rfind(s: str, s1: str) -> int:
    return s.rfind(s1)
