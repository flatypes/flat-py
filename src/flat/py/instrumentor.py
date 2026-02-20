from typing import get_origin, Literal

from flat.py import fuzz as fuzz_annot, PyCond
from flat.py.rewrite import cnf, ISLaConvertor, free_vars, subst
from flat.py.runtime import *
from flat.py.utils import classify
from flat.typing import Type, RefinementType, LiteralType


@dataclass(frozen=True)
class FunSig:
    """Only interesting types are specified."""
    name: str
    params: list[Tuple[str, Optional[Type], Optional[ast.expr]]]
    defaults: dict[str, ast.expr]
    returns: Optional[Tuple[Type, ast.expr]]
    preconditions: list[ast.expr]  # bind params
    postconditions: list[ast.expr]  # bind params and '_' for return value

    @property
    def param_names(self) -> list[str]:
        return [x for x, _, _ in self.params]


class FunContext:
    def __init__(self, fun: FunSig, annots: dict[str, ast.expr]):
        self.fun = fun
        self.annots = annots


def load(name: str) -> ast.Name:
    return ast.Name(name, ctx=ast.Load())


def const(value: int | str | None) -> ast.Constant:
    return ast.Constant(value)


def conjunction(conjuncts: list[ast.expr]) -> ast.expr:
    match conjuncts:
        case []:
            return ast.Constant(True)
        case [cond]:
            return cond
        case _:
            return ast.BoolOp(ast.And(), conjuncts)


def assign(var: str, value: ast.expr | int) -> ast.stmt:
    if isinstance(value, int):
        value = ast.Constant(value)

    return ast.Assign([ast.Name(var, ctx=ast.Store())], value)


def apply(fun: str | ast.expr, *args: int | str | ast.expr) -> ast.Call:
    if isinstance(fun, str):
        fun = load(fun)
    exprs = []
    for arg in args:
        match arg:
            case int() as n:
                exprs += [ast.Constant(n)]
            case str() as s:
                exprs += [ast.Constant(s)]
            case ast.expr() as e:
                exprs += [e]
    return ast.Call(fun, exprs, keywords=[])


def lambda_expr(args: list[str], body: ast.expr) -> ast.Lambda:
    return ast.Lambda(ast.arguments([], [ast.arg(x) for x in args], None, [], [], None, []), body)


def apply_flat(fun: Callable, *args: int | str | ast.expr) -> ast.Call:
    return apply(ast.Attribute(load('__flat__'), fun.__name__, ctx=ast.Load()), *args)


def call_flat(fun: Callable, *args: int | str | ast.expr) -> ast.Expr:
    return ast.Expr(apply_flat(fun, *args))


def parse_expr(code: str) -> ast.expr:
    match ast.parse(code).body[0]:
        case ast.Expr(expr):
            return expr
        case _:
            raise TypeError


def canonical_cond(condition: ast.expr, binders: list[str]) -> ast.expr:
    match condition:
        case ast.Constant(str() as literal):
            return parse_expr(literal)
        case ast.Lambda(ast.arguments([], args, None, [], [], None, []), body):
            return subst(body, dict((arg.arg, load(x)) for arg, x in zip(args, binders)))
        case _:
            raise TypeError


def get_loc(node: ast.AST) -> ast.expr:
    return apply_flat(Loc, node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


class Instrumentor(ast.NodeTransformer):
    def __init__(self) -> None:
        # self._inside_body = False
        self._last_lineno = 0
        self._next_id = 0
        self._case_guards: list[ast.expr] = []
        self._functions: dict[str, FunSig] = {}

    def __call__(self, source: str, code: str) -> str:
        self._env: dict[str, Any] = {}
        exec(code, {}, self._env)

        tree = ast.parse(code)
        self._last_lineno = 0
        self._stack: list[FunContext] = []
        self.filename = source
        try:
            self.visit(tree)
        except InstrumentError as err:
            err.print()

        import_runtime = ast.parse('from flat.py import runtime as __flat__').body[0]
        set_source = ast.parse(f'__source__ = "{self.filename}"').body[0]
        tree.body.insert(0, import_runtime)
        tree.body.insert(1, set_source)
        tree.body.insert(2, call_flat(load_source_module, ast.Name('__source__')))
        tree.body.append(call_flat(run_main, load('main')))
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)

    def track_lineno(self, lineno: int) -> list[ast.stmt]:
        # assert self._inside_body
        body = []
        if lineno != self._last_lineno:
            body += [assign('__line__', lineno)]
            self._last_lineno = lineno

        return body

    def expand(self, annot: ast.expr) -> Optional[Type]:
        match eval(ast.unparse(annot), {}, self._env):
            case Type() as typ:
                return typ
            case other:
                if get_origin(other) is Literal:  # literal type
                    values = get_args(other)
                    assert len(values) > 0
                    assert all(isinstance(v, int) or isinstance(v, bool) or isinstance(v, str) for v in values)
                    return LiteralType(values)
                return None

    def fresh_name(self) -> str:
        self._next_id += 1
        return f'_{self._next_id}'

    def error(self, message: str, at: ast.AST) -> InstrumentError:
        loc = Loc(at.lineno, at.col_offset, at.end_lineno, at.end_col_offset)
        if len(self._stack) == 0:
            name = '<main>'
        else:
            name = self._stack[-1].fun.name
        return InstrumentError(message, self.filename, name, loc)

    def extract_arg(self, index: Optional[int], name: str, required: bool, from_call: ast.Call) -> Optional[ast.expr]:
        # try args
        if index is not None and len(from_call.args) > index:
            for keyword in from_call.keywords:
                if keyword.arg == name:  # conflict
                    raise self.error(f"got multiple values for argument '{name}'", keyword)
            return from_call.args[index]

        # try keywords
        for keyword in from_call.keywords:
            if keyword.arg == name:
                return keyword.value

        # not found
        if required:
            raise self.error(f"missing required positional argument: '{name}'", from_call)
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # self._inside_body = True
        body = self.track_lineno(node.lineno)
        annots = {}

        # check arg types
        params: list[Tuple[str, Optional[Type], Optional[ast.expr]]] = []
        for arg in node.args.args:
            x = arg.arg
            if arg.annotation:
                typ = self.expand(arg.annotation)
                if typ:
                    annots[x] = arg.annotation
                    body += [call_flat(assert_arg_type, load(x), len(params), node.name, arg.annotation)]
            else:
                typ = None
            params.append((x, typ, arg.annotation))

        # record default value
        defaults: dict[str, Optional[ast.expr]] = {}
        for (x, _, _), default in zip(reversed(params), reversed(node.args.defaults)):
            defaults[x] = default

        # check return type
        if node.returns:
            match self.expand(node.returns):
                case None:
                    returns = None
                case typ:
                    returns = typ, node.returns
        else:
            returns = None

        # check specifications
        preconditions: list[ast.expr] = []
        postconditions: list[ast.expr] = []
        exc_info: list[ast.Tuple] = []  # cond_var name, exc_type, loc
        processed: list[ast.expr] = []
        arg_names = [x for x, _, _ in params]
        for decorator in node.decorator_list:
            match decorator:
                case ast.Call(ast.Name('requires'), [condition]):
                    pre = canonical_cond(condition, arg_names)
                    preconditions.append(pre)
                    body += self.track_lineno(decorator.lineno)
                    body += [call_flat(assert_pre, pre,
                                       ast.List([ast.Tuple([const(x), load(x)]) for x in arg_names]), node.name)]
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('ensures'), [condition]):
                    post = canonical_cond(condition, arg_names + ['_'])
                    post.lineno = decorator.lineno
                    postconditions.append(post)
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('returns'), [value]):
                    value = canonical_cond(value, arg_names)
                    post = ast.Compare(load('_'), [ast.Eq()], [value])
                    post.lineno = decorator.lineno
                    postconditions.append(post)
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('raise_if')) as call:
                    exc_type = self.extract_arg(0, 'exc', True, call)
                    cond = canonical_cond(self.extract_arg(1, 'cond', True, call), arg_names)
                    cond_var = f'__exc_cond_{len(exc_info)}__'
                    body += [assign(cond_var, cond)]
                    exc_info.append(ast.Tuple([load(cond_var), exc_type, get_loc(decorator)]))
                    processed.append(decorator)  # to remove it

        for x in processed:
            node.decorator_list.remove(x)

        # signature done
        sig = FunSig(node.name, params, defaults, returns, preconditions, postconditions)
        self._functions[node.name] = sig

        # transform body
        if len(exc_info) > 0:  # need wrap
            body_buffer = []
        else:  # no wrap
            body_buffer = body

        self._stack.append(FunContext(sig, annots))
        for stmt in node.body:
            match self.visit(stmt):
                case ast.stmt() as s:
                    body_buffer.append(s)
                case list() as ss:
                    body_buffer += ss
        self._stack.pop()

        if len(exc_info) > 0:
            handler = apply_flat(ExpectExceptions, ast.List([t for t in exc_info]))
            with_item = ast.withitem(handler)
            with_stmt = ast.With([with_item], body_buffer, type_ignores=[])
            body.append(with_stmt)
        node.body = body
        return node

    def visit_Assign(self, node: ast.Assign) -> list[ast.stmt]:
        node.value = self.visit(node.value)
        if len(self._stack) == 0:
            return [node]

        ctx = self._stack[-1]
        body = self.track_lineno(node.lineno)
        body += [node]
        for target in node.targets:
            for var in vars_in_target(target):
                if var in ctx.annots:
                    body += [call_flat(assert_type, node.value, get_loc(node.value), ctx.annots[var])]

        return body

    def visit_AnnAssign(self, node: ast.AnnAssign) -> list[ast.stmt]:
        if node.value:
            node.value = self.visit(node.value)
        if len(self._stack) == 0:
            return [node]

        ctx = self._stack[-1]
        body = self.track_lineno(node.lineno)
        body += [node]
        match node.target:
            case ast.Name(var):
                if self.expand(node.annotation) is not None:
                    ctx.annots[var] = node.annotation
                    body += [call_flat(assert_type, node.value, get_loc(node.value), ctx.annots[var])]
            case _:
                raise TypeError

        return body

    def visit_AugAssign(self, node: ast.AugAssign):
        node.value = self.visit(node.value)
        if len(self._stack) == 0:
            return [node]

        ctx = self._stack[-1]
        body = self.track_lineno(node.lineno)
        body += [node]
        match node.target:
            case ast.Name(var):
                if var in ctx.annots:
                    body += [call_flat(assert_type, node.value, get_loc(node.value), ctx.annots[var])]

        return body

    def visit_Return(self, node: ast.Return):
        if node.value:
            node.value = self.visit(node.value)
        else:
            node.value = const(None)

        ctx = self._stack[-1]
        body = self.track_lineno(node.lineno)
        if ctx.fun.returns is None and len(ctx.fun.postconditions) == 0:  # no check, just return
            return body + [node]

        body += [assign('__return__', node.value)]
        if ctx.fun.returns:
            body += [call_flat(assert_type, load('__return__'), get_loc(node.value), ctx.fun.returns[1])]

        arg_names = [x for x in ctx.fun.param_names]
        for cond in ctx.fun.postconditions:  # note: return value is '_' in cond
            body += self.track_lineno(cond.lineno)
            body += [call_flat(assert_post, subst(cond, {'_': load('__return__')}),
                               ast.List([ast.Tuple([const(x), load(x)]) for x in arg_names]),
                               load('__return__'), get_loc(node.value), const(ctx.fun.name))]
        body += self.track_lineno(node.lineno)
        body += [ast.Return(load('__return__'))]
        return body

    def visit_Call(self, node: ast.Call):
        match node:
            case ast.Call(ast.Name('isinstance'), [obj, typ]) if self.expand(typ) is not None:
                return apply_flat(has_type, obj, typ)
            case ast.Call(ast.Name('fuzz')) as call if self._env['fuzz'] == fuzz_annot:
                fun = None
                target = self.extract_arg(0, 'target', True, call)
                match target:
                    case ast.Name(f):
                        if f in self._functions:
                            if fun is None:
                                fun = self._functions[f]
                        else:
                            raise self.error(f"target function '{f}' not found", target)
                    case _:
                        raise self.error('expect a function name', target)

                times = self.extract_arg(1, 'times', True, call)

                using: dict[str, ast.expr] = {}
                match self.extract_arg(None, 'using', False, call):
                    case None:
                        pass
                    case ast.Dict(keys, values):
                        for key, value in zip(keys, values):
                            match key:
                                case ast.Constant(str() as x):
                                    using[x] = value
                                case _:
                                    raise self.error('expect argument name', key)
                    case other:
                        raise self.error('expect dict', other)
                return apply_flat(fuzz, target, times, self._producer(fun, using))
            case _:
                return super().generic_visit(node)

    def visit_Match(self, node: ast.Match):
        node.subject = self.visit(node.subject)
        new_cases = []
        for case in node.cases:
            self._case_guards = []
            case = self.visit(case)
            if len(self._case_guards) > 0:
                cond = ast.BoolOp(ast.And(), self._case_guards)
                case.guard = cond if case.guard is None else ast.BoolOp(ast.And(), [case.guard, cond])
            new_cases.append(case)
        node.cases = new_cases

        return node

    def visit_MatchAs(self, node: ast.MatchAs):
        match node:
            case ast.MatchAs(ast.MatchClass(cls, [], [], []), x) if self.expand(cls) is not None:
                self._case_guards.append(apply_flat(has_type, load(x), cls))
                return ast.MatchAs(None, x)
            case _:
                return super().generic_visit(node)

    def visit_MatchClass(self, node: ast.MatchClass):
        match node:
            case ast.MatchClass(cls, [], [], []) if self.expand(cls) is not None:
                x = self.fresh_name()
                self._case_guards.append(apply_flat(has_type, load(x), cls))
                return ast.MatchAs(None, x)
            case _:
                return super().generic_visit(node)

    def generic_visit(self, node: ast.AST):
        if isinstance(node, ast.stmt):
            body = self.track_lineno(node.lineno)
            match super().generic_visit(node):
                case ast.stmt() as s:
                    body.append(s)
                case list() as ss:
                    body += ss
            return body

        return super().generic_visit(node)

    def _producer(self, fun: FunSig, using_producers: dict[str, ast.expr]) -> ast.expr:
        pre_conjuncts = [c for pre in fun.preconditions for c in cnf(pre)]
        convert = ISLaConvertor(self._env)

        producers: list[ast.expr] = []
        for x, typ, annot in fun.params:
            if x in using_producers:
                producers += [using_producers[x]]
            elif x in fun.defaults:  # use default value
                producers += [apply_flat(constant_generator, fun.defaults[x])]
            elif typ and typ.is_lang_type:  # synthesize an isla producer
                formulae: list[str] = []  # conjuncts that isla can solve
                test_conditions: list[ast.expr] = []  # other conjuncts: fall back to Python
                if isinstance(typ, RefinementType) and isinstance(typ.cond, PyCond):
                    for cond in cnf(typ.cond.expr):
                        match convert(cond, '_'):
                            case None:
                                test_conditions += [cond]
                            case f:
                                formulae += [f]  # type: ignore

                # pick conjuncts that could be written in the refinement position
                # i.e., it is a predicate over the param x only
                picked, pre_conjuncts = classify(lambda c: free_vars(c) & (set(fun.param_names) - {x}) == set(),
                                                 pre_conjuncts)
                for cond in picked:
                    match convert(cond, x):
                        case None:
                            test_conditions += [subst(cond, {x: load('_')})]
                        case f:
                            formulae += [f]  # type: ignore

                match formulae:
                    case []:
                        formula = const(None)
                    case [f]:
                        formula = const(f)
                    case _:
                        formula = const(' and '.join(formulae))

                assert annot is not None
                if isinstance(typ, RefinementType):
                    annot = ast.Attribute(annot, 'base', ctx=ast.Load())
                producers += [
                    apply_flat(producer,
                               apply_flat(isla_generator, annot, formula),
                               lambda_expr(['_'], conjunction(test_conditions)))
                ]
            elif isinstance(typ, LiteralType):
                if len(typ.values) == 1:
                    producers += [apply_flat(constant_generator, typ.values[0])]
                else:
                    producers += [apply_flat(choice_generator, ast.List([ast.Constant(v) for v in typ.values]))]
            else:
                raise TypeError(f'must specify producer for param {x}, specified are {using_producers}')

        return apply_flat(product_producer, ast.List(producers),
                          lambda_expr(fun.param_names, conjunction(pre_conjuncts)))


def vars_in_target(expr: ast.expr) -> list[str]:
    match expr:
        case ast.Name(x):
            return [x]
        case ast.Tuple(es):
            return [x for e in es for x in vars_in_target(e)]
        case _:
            return []
