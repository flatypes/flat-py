from dataclasses import Field
from typing import TypeAliasType, get_origin, Literal, get_args

from flat.py import fuzz as fuzz_annot
from flat.py.annot_eval import AnnotEvaluator
from flat.py.ast_factory import *
from flat.py.rewrite import cnf, ISLaConvertor, subst
from flat.py.runtime import *
from flat.typing import *


@dataclass(frozen=True)
class FunSig:
    """Only interesting types are specified."""
    name: str
    params: list[Tuple[str, Optional[Type]]]
    defaults: dict[str, ast.expr]
    returns: Optional[Type]
    preconditions: list[ast.expr]  # bind params
    postconditions: list[ast.expr]  # bind params and '_' for return value

    @property
    def param_names(self) -> list[str]:
        return [x for x, _, _ in self.params]


class FunContext:
    def __init__(self, fun: FunSig):
        self.fun = fun
        self.types: dict[str, Type] = {x: t for x, t in fun.params if t is not None}


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
            return subst(body, dict((arg.arg, ast.Name(x)) for arg, x in zip(args, binders)))
        case _:
            raise TypeError


def get_loc(node: ast.AST) -> ast.expr:
    return mk_call_flat(Loc, node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def to_type(obj: Any) -> Optional[Type]:
    """Try to convert an object to a FLAT type."""
    match obj:
        case Type() as t:
            return t
        case TypeAliasType() as ta:
            return to_type(ta.__value__)
        case type():
            if hasattr(obj, '__dataclass_fields__'):  # data class
                fields: dict[str, Field] = getattr(obj, '__dataclass_fields__')
                ts = {}
                for x, f in fields.items():
                    t = to_type(f.type)
                    if t:
                        ts[x] = t
                    else:
                        return None
                return RecordType(obj, ts)

            if get_origin(obj) is Literal:  # literal type
                values = get_args(obj)
                assert len(values) > 0
                assert all(isinstance(v, str) for v in values)
                return LangType.from_literals(values)

            return None


def synth_producer(typ: Type, env: dict[str, Any]) -> ast.expr:
    match typ:
        case LangType(g):
            assert isinstance(g, CFG)
            return mk_call_flat(ISLaProducer, to_expr(g))
        case ListType(t):
            return mk_call_flat(ListProducer, synth_producer(t, env))
        case TupleType(ts):
            return mk_call_flat(TupleProducer, ast.List(synth_producer(t, env) for t in ts))
        case RecordType(k, ts):
            return mk_call_flat(RecordProducer, to_expr(k),
                                ast.List(synth_producer(t, env) for t in ts.values()))
        case RefinedType(LangType(g), e):
            assert isinstance(e, ast.Lambda)
            convert = ISLaConvertor(env)
            formulae: list[str] = []  # conjuncts that isla can solve
            test_conditions: list[ast.expr] = []  # other conjuncts: fall back to Python
            for cond in cnf(e):
                match convert(cond, '_'):
                    case None:
                        test_conditions += [cond]
                    case f:
                        formulae += [f]  # type: ignore

            match formulae:
                case []:
                    formula = None
                case [f]:
                    formula = f
                case _:
                    formula = ' and '.join(formulae)

            isla_producer = mk_call_flat(ISLaProducer, to_expr(g), formula)
            if len(test_conditions) == 0:
                return isla_producer
            return mk_call_flat(FilterProducer, isla_producer, mk_and(test_conditions))
        case RefinedType(t, p):
            assert isinstance(p, ast.Lambda)
            return mk_call_flat(FilterProducer, synth_producer(t, env), p)

    raise TypeError(f"cannot generate producer for type '{typ}'")


class Instrumentor(ast.NodeTransformer):
    def __init__(self) -> None:
        # self._inside_body = False
        self._last_lineno = 0
        self._next_id = 0
        self._case_guards: list[ast.expr] = []
        self._functions: dict[str, FunSig] = {}

    def __call__(self, source: str, code: str) -> str:
        tree = ast.parse(code)
        evaluator = AnnotEvaluator()
        evaluator.visit(tree)
        self._env = evaluator.env
        
        self._last_lineno = 0
        self._stack: list[FunContext] = []
        self.filename = source
        try:
            self.visit(tree)
        except InstrumentError as err:
            err.print()

        import_flat = ast.parse('import flat.py.runtime').body[0]
        set_source = ast.parse(f'__source__ = "{self.filename}"').body[0]
        tree.body.insert(0, import_flat)
        tree.body.insert(1, set_source)
        tree.body.insert(2, mk_invoke_flat(load_source_module, ast.Name('__source__')))
        tree.body.append(mk_invoke_flat(run_main, ast.Name('main')))
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)

    def track_lineno(self, lineno: int) -> list[ast.stmt]:
        # assert self._inside_body
        body = []
        if lineno != self._last_lineno:
            body += [mk_assign('__line__', lineno)]
            self._last_lineno = lineno

        return body

    def expand(self, annot: ast.expr) -> Optional[Type]:
        obj = eval(ast.unparse(annot), self._env)
        return to_type(obj)

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

    def extract_arg(self, index: Optional[int], name: str, required: bool,
                    from_call: ast.Call) -> Optional[ast.expr]:
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
        params: list[Tuple[str, Optional[Type]]] = []
        for arg in node.args.args:
            x = arg.arg
            if arg.annotation:
                t = self.expand(arg.annotation)
                if t:
                    annots[x] = arg.annotation
                    body += [mk_invoke_flat(assert_arg_type, ast.Name(x), len(params), node.name,
                                            to_expr(t))]
            else:
                t = None
            params.append((x, t))

        # record default value
        defaults: dict[str, Optional[ast.expr]] = {}
        for (x, _), default in zip(reversed(params), reversed(node.args.defaults)):
            defaults[x] = default

        # check return type
        if node.returns:
            match self.expand(node.returns):
                case None:
                    returns: Optional[Type] = None
                case t:
                    returns = t
        else:
            returns = None

        # check specifications
        preconditions: list[ast.expr] = []
        postconditions: list[ast.expr] = []
        exc_info: list[ast.Tuple] = []  # cond_var name, exc_type, loc
        processed: list[ast.expr] = []
        arg_names = [x for x, _ in params]
        for decorator in node.decorator_list:
            match decorator:
                case ast.Call(ast.Name('requires'), [condition]):
                    pre = canonical_cond(condition, arg_names)
                    preconditions.append(pre)
                    body += self.track_lineno(decorator.lineno)
                    body += [mk_invoke_flat(assert_pre, pre,
                                            ast.List([ast.Tuple([ast.Constant(x), ast.Name(x)]) for x in arg_names]),
                                            node.name)]
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('ensures'), [condition]):
                    post = canonical_cond(condition, arg_names + ['_'])
                    post.lineno = decorator.lineno
                    postconditions.append(post)
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('returns'), [value]):
                    value = canonical_cond(value, arg_names)
                    post = ast.Compare(ast.Name('_'), [ast.Eq()], [value])
                    post.lineno = decorator.lineno
                    postconditions.append(post)
                    processed.append(decorator)  # to remove it
                case ast.Call(ast.Name('raise_if')) as call:
                    exc_type = self.extract_arg(0, 'exc', True, call)
                    cond = canonical_cond(self.extract_arg(1, 'cond', True, call), arg_names)
                    cond_var = f'__exc_cond_{len(exc_info)}__'
                    body += [mk_assign(cond_var, cond)]
                    exc_info.append(ast.Tuple([ast.Name(cond_var), exc_type, get_loc(decorator)]))
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

        self._stack.append(FunContext(sig))
        for stmt in node.body:
            match self.visit(stmt):
                case ast.stmt() as s:
                    body_buffer.append(s)
                case list() as ss:
                    body_buffer += ss
        self._stack.pop()

        if len(exc_info) > 0:
            handler = mk_call_flat(ExpectExceptions, ast.List([t for t in exc_info]))
            with_item = ast.withitem(handler)
            with_stmt = ast.With([with_item], body_buffer)
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
                if var in ctx.types:
                    body += [mk_invoke_flat(assert_type, node.value, get_loc(node.value),
                                            to_expr(ctx.types[var]))]

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
                t = self.expand(node.annotation)
                if t:
                    ctx.types[var] = t
                    body += [mk_invoke_flat(assert_type, node.value, get_loc(node.value), to_expr(t))]
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
                if var in ctx.types:
                    body += [mk_invoke_flat(assert_type, node.value, get_loc(node.value),
                                            to_expr(ctx.types[var]))]

        return body

    def visit_Return(self, node: ast.Return):
        if node.value:
            node.value = self.visit(node.value)
        else:
            node.value = ast.Constant(None)

        ctx = self._stack[-1]
        body = self.track_lineno(node.lineno)
        if ctx.fun.returns is None and len(ctx.fun.postconditions) == 0:  # no check, just return
            return body + [node]

        body += [mk_assign('__return__', node.value)]
        if ctx.fun.returns:
            body += [mk_invoke_flat(assert_type, ast.Name('__return__'), get_loc(node.value), ctx.fun.returns[1])]

        arg_names = [x for x in ctx.fun.param_names]
        for cond in ctx.fun.postconditions:  # note: return value is '_' in cond
            body += self.track_lineno(cond.lineno)
            body += [mk_invoke_flat(assert_post, subst(cond, {'_': ast.Name('__return__')}),
                                    ast.List([ast.Tuple([ast.Constant(x), ast.Name(x)]) for x in arg_names]),
                                    ast.Name('__return__'), get_loc(node.value), ast.Constant(ctx.fun.name))]
        body += self.track_lineno(node.lineno)
        body += [ast.Return(ast.Name('__return__'))]
        return body

    def visit_Call(self, node: ast.Call):
        match node:
            case ast.Call(ast.Name('isinstance'), [obj, typ]) if self.expand(typ) is not None:
                return mk_call_flat(has_type, obj, typ)
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
                return mk_call_flat(fuzz_test, target, times, self._producer(fun, using))
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
                self._case_guards.append(mk_call_flat(has_type, ast.Name(x), cls))
                return ast.MatchAs(None, x)
            case _:
                return super().generic_visit(node)

    def visit_MatchClass(self, node: ast.MatchClass):
        match node:
            case ast.MatchClass(cls, [], [], []) if self.expand(cls) is not None:
                x = self.fresh_name()
                self._case_guards.append(mk_call_flat(has_type, ast.Name(x), cls))
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
        # pre_conjuncts = [c for pre in fun.preconditions for c in cnf(pre)]
        producers: list[ast.expr] = []
        for x, t in fun.params:
            if x in using_producers:
                producers += [using_producers[x]]
            elif x in fun.defaults:  # use default value
                producers += [mk_call_flat(ConstProducer, fun.defaults[x])]
            elif t:
                producers += [synth_producer(t, self._env)]
            else:
                assert t is None
                raise TypeError(f'must specify producer for param `{x}`')

        return mk_call_flat(TupleProducer, ast.List(producers))


def vars_in_target(expr: ast.expr) -> list[str]:
    match expr:
        case ast.Name(x):
            return [x]
        case ast.Tuple(es):
            return [x for e in es for x in vars_in_target(e)]
        case _:
            return []
