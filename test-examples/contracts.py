from flat.py import requires, ensures, returns


@requires('x > 0')
@ensures('_ > 0')
@returns('x * 2')
def f(x: int) -> int:
    return x + x + 1


f(1)
f(0)
