from flat.py import requires, ensures, returns


@requires(lambda x: x > 0)
@ensures(lambda result: result > 0)
@returns(x + 1)
@returns('x + 1', 'x + 2')
def f(x: int) -> int:
    return x + 1
