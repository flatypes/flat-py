import ast
from typing import Sequence

from flat.py.analyzer import analyze
from flat.py.ast_helpers import *
from flat.py.compile_time import *
from flat.py.runtime import SOURCE, LINENO
from flat.py.shared import get_range

__all__ = ['check']


def check(tree: ast.Module, issuer: Issuer,
          *, file_path: str = '<module>', with_lineno: bool = True) -> ast.Module:
    """Check a Python module (AST) and instrument runtime type checks."""
    checker = Checker(Context(file_path, issuer), with_lineno=with_lineno)
    return checker.visit(tree)


lib: dict[str, dict[str, Def]] = {
    'flat.py': {'lang': TypeConstrDef('flat.py.lang'), 'refine': TypeConstrDef('flat.py.refine'),
                'types': AnnDef('flat.py.types'), 'requires': AnnDef('flat.py.requires'),
                'ensures': AnnDef('flat.py.ensures'), 'returns': AnnDef('flat.py.returns'),
                'fuzz': AnnDef('flat.py.fuzz')},
    'typing': {'Any': TypeDef(AnyType()),
               'Literal': TypeConstrDef('typing.Literal'),
               'Union': TypeConstrDef('typing.Union'), 'Optional': TypeConstrDef('typing.Optional'),
               'Tuple': TypeConstrDef('tuple'), 'List': TypeConstrDef('list'),
               'Set': TypeConstrDef('set'), 'Dict': TypeConstrDef('dict')}
}


class Checker(ast.NodeTransformer):
    """Runtime checks instrumentor."""

    def __init__(self, ctx: Context, *, rt: str = 'rt', with_lineno: bool) -> None:
        super().__init__()
        self.ctx = ctx
        self.rt = rt
        self.with_lineno = with_lineno

    def visit_Module(self, node: ast.Module) -> ast.Module:
        body: list[ast.stmt] = [mk_import_from('flat.py', 'runtime', as_name=self.rt)]
        if self.with_lineno:
            body.append(mk_assign(SOURCE, ast.Constant(self.ctx.file_path)))
        self._check_body(node.body, body)
        return ast.Module(body, type_ignores=node.type_ignores)

    def _check_body(self, stmts: list[ast.stmt], body: list[ast.stmt]) -> None:
        for stmt in stmts:
            if self.with_lineno and hasattr(stmt, 'lineno'):
                body.append(mk_assign(LINENO, ast.Constant(getattr(stmt, 'lineno'))))

            out = self.visit(stmt)
            if isinstance(out, ast.stmt):
                body.append(out)
            elif isinstance(out, list):
                body += out
            else:
                raise TypeError(f"Invalid output {type(out)}")

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        body: list[ast.stmt] = []
        for stmt in node.body:
            out = self.visit(stmt)
            if isinstance(out, ast.stmt):
                body.append(out)
            elif isinstance(out, list):
                body += out
            else:
                raise TypeError(f"Invalid output {type(out)}")

        return ast.ClassDef(node.name, node.bases, node.keywords, body, node.decorator_list, node.type_params)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Resolve signature
        params = self._resolve_params(node.args)
        return_type = analyze(node.returns, self.ctx) if node.returns else AnyType()
        contracts, other_decorators = self._resolve_decorators(node.decorator_list)
        fun = FunDef(params, node.args, return_type, contracts)
        self.ctx[node.name] = fun

        # Pre-check: argument types
        body: list[ast.stmt] = []
        position = 0
        for param in params.pos_only:
            self._check_arg_type(param.name, param.typ, body, position=position, default=param.default)
            position += 1
        for param in params.ordinary:
            self._check_arg_type(param.name, param.typ, body, position=position, keyword=param.name,
                                 default=param.default)
            position += 1
        if params.pos_variadic:  # *args
            # __position__ = position
            # for __arg__ in args:
            #    rt.check_arg_type(__arg__, arg.typ, position=__position__)
            #    __position__ += 1
            body.append(mk_assign('__position__', ast.Constant(position)))
            vararg_body: list[ast.stmt] = []
            self._check_arg_type('__arg__', params.pos_variadic.typ, vararg_body,
                                 position=ast.Name('__position__'))
            body.append(mk_foreach('__arg__', ast.Name(params.pos_variadic.name), vararg_body))
        for param in params.kw_only:
            self._check_arg_type(param.name, param.typ, body, keyword=param.name, default=param.default)
        if params.kw_variadic:  # **kwargs
            # for __keyword__ in kwargs:
            #    rt.check_arg_type(kwargs[__keyword__], arg.typ, keyword=__keyword__)
            kwarg_body: list[ast.stmt] = []
            self._check_arg_type(ast.Subscript(ast.Name(params.kw_variadic.name), ast.Name('__keyword__')),
                                 params.kw_variadic.typ, kwarg_body, keyword=ast.Name('__keyword__'))
            body.append(mk_foreach('__keyword__', ast.Name(params.kw_variadic.name), kwarg_body))

        # Pre-check: contracts
        for contract in contracts:
            match contract:
                case Require(cond, cond_loc):
                    self._check_pre(cond, cond_loc, body)

        # Check body
        self.ctx.push(fun, defs=params.vars)
        self._check_body(node.body, body)
        self.ctx.pop()
        return ast.FunctionDef(node.name, erase_ann(node.args), body, list(other_decorators), None, None, [])

    def _resolve_params(self, node: ast.arguments) -> Params:
        i = 0
        default_start = len(node.posonlyargs) + len(node.args) - len(node.defaults)
        pos_only: list[Param] = []
        for arg in node.posonlyargs:  # position-only arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - default_start] if i >= default_start else None
            pos_only.append(Param(arg.arg, typ, default))
            i += 1

        ordinary: list[Param] = []
        for arg in node.args:  # ordinary arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - default_start] if i >= default_start else None
            ordinary.append(Param(arg.arg, typ, default))
            i += 1

        pos_variadic: Param | None = None
        if node.vararg:  # variadic positional argument *arg
            typ = analyze(node.vararg.annotation, self.ctx) if node.vararg.annotation else AnyType()
            pos_variadic = Param(node.vararg.arg, typ)

        kw_only: list[Param] = []
        for arg, default in zip(node.kwonlyargs, node.kw_defaults):  # keyword-only arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            kw_only.append(Param(arg.arg, typ, default))

        kw_variadic: Param | None = None
        if node.kwarg:  # variadic keyword argument **kwarg
            typ = analyze(node.kwarg.annotation, self.ctx) if node.kwarg.annotation else AnyType()
            kw_variadic = Param(node.kwarg.arg, typ)

        return Params(pos_only, ordinary, pos_variadic, kw_only, kw_variadic)

    def _resolve_decorators(self, decorators: Sequence[ast.expr]) -> tuple[Sequence[Contract], Sequence[ast.expr]]:
        contracts: list[Contract] = []
        others: list[ast.expr] = []
        for decorator in decorators:
            match decorator:
                case ast.Call(ast.Name(name), _, _):
                    match self.ctx.lookup(name):
                        case AnnDef(annot):
                            contracts += self._resolve_contract(annot, decorator)
                        case _:
                            others.append(decorator)
                case _:
                    others.append(decorator)

        return contracts, others

    def _resolve_contract(self, annot: str, call: ast.Call) -> Sequence[Contract]:
        match annot:
            case 'flat.py.requires' | 'flat.py.ensures':
                contracts: list[Contract] = []
                for arg in call.args:
                    match arg:
                        case ast.Constant(str() as s):
                            cond = ast.parse(s, mode='eval').body
                            contract = Require(cond, arg) if annot == 'flat.py.requires' else Ensure(cond, arg)
                            contracts.append(contract)
                        case _:
                            self.ctx.issue(InvalidArg(annot, 'condition (a string literal)',
                                                      self.ctx.file_path, get_range(arg)))
                return contracts

            case 'flat.py.returns':
                if len(call.args) != 1:
                    self.ctx.issue(ArityMismatch(annot, 1, len(call.args),
                                                 self.ctx.file_path, get_range(call.func)))
                    return []

                arg = call.args[0]
                match arg:
                    case ast.Constant(str() as s):
                        value = ast.parse(s, mode='eval').body
                        return [Ensure(mk_eq(ast.Name('_'), value), call)]
                    case _:
                        self.ctx.issue(InvalidArg(annot, 'return value (a string literal)',
                                                  self.ctx.file_path, get_range(arg)))
                        return []

            case _:
                raise NameError(f"Unknown contract annotation '{annot}'")

    def _check_arg_type(self, actual: str | ast.expr, expected: Type, body: list[ast.stmt],
                        *, position: int | ast.Name | None = None, keyword: str | ast.Name | None = None,
                        default: ast.expr | None = None) -> None:
        if isinstance(expected, AnyType):
            return

        if isinstance(actual, str):
            actual = ast.Name(actual)
        if isinstance(position, (int, None)):
            position = ast.Constant(position)
        if isinstance(keyword, (str, None)):
            keyword = ast.Constant(keyword)
        if default is None:
            default = none_tree
        else:
            default = self._mk_range(default)
        body.append(ast.Expr(mk_call(f'{self.rt}.check_arg_type', actual, expected.to_runtime(self.rt),
                                     position, keyword, default)))

    def _mk_range(self, node: ast.AST) -> ast.expr:
        return mk_runtime(get_range(node), self.rt)

    def _check_pre(self, cond: ast.expr, cond_tree: ast.expr, body: list[ast.stmt]) -> None:
        body.append(ast.Expr(mk_call(f'{self.rt}.check_pre', cond, self._mk_range(cond_tree))))

    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        fun = self.ctx.owner()
        assert fun is not None, "'return' outside function"

        # Post-check: return type
        body: list[ast.stmt] = []
        return_value = node.value if node.value else none_tree
        body.append(mk_assign('_', return_value))
        self._check_type('_', fun.return_type, node.value if node.value else node, body)

        # Post-check: contracts
        for contract in fun.contracts:
            match contract:
                case Ensure(cond, cond_loc):  # Assume: input arguments are immutable
                    self._check_post(cond, cond_loc, node, body)

        # Done
        body.append(ast.Return(ast.Name('_')))
        return body

    def _check_type(self, actual: str | ast.expr, expected: Type, actual_tree: ast.AST, body: list[ast.stmt]) -> None:
        match expected:
            case AnyType():
                pass
            case _:
                if isinstance(actual, str):
                    actual = ast.Name(actual)
                elif not is_pure(actual):
                    x = self.ctx.fresh()
                    body.append(mk_assign(x, actual))
                    actual = ast.Name(x)
                body.append(ast.Expr(mk_call(f'{self.rt}.check_type', actual, expected.to_runtime(self.rt),
                                             self._mk_range(actual_tree))))

    def _check_post(self, cond: ast.expr, cond_tree: ast.expr, return_tree: ast.stmt, body: list[ast.stmt]) -> None:
        body.append(ast.Expr(mk_call(f'{self.rt}.check_post', cond, self._mk_range(cond_tree),
                                     self._mk_range(return_tree))))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        known = lib[node.module] if node.module in lib else {}
        for alias in node.names:
            x = alias.asname or alias.name
            match self.ctx.get(x):
                case None:
                    d = known.get(alias.name, UnknownDef())
                    self.ctx[x] = d
                case _:
                    self.ctx.issue(RedefinedName(self.ctx.file_path, get_range(alias)))

        return node

    def visit_Global(self, node: ast.Global) -> ast.Global:
        for name in node.names:
            match self.ctx.lookup_global(name):
                case None:  # create a new global variable
                    self.ctx.create_global_var(name)
                case d:
                    self.ctx[name] = d

        return node

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Nonlocal:
        for name in node.names:
            match self.ctx.lookup_nonlocal(name):
                case None:
                    self.ctx.issue(UndefinedNonlocal(self.ctx.file_path, get_range(node)))
                case d:
                    self.ctx[name] = d

        return node

    def visit_TypeAlias(self, node: ast.TypeAlias) -> ast.TypeAlias:
        if len(node.type_params) == 0:
            self._define_type(node.name, node.value)

        return node

    def _define_type(self, target: ast.Name, value: ast.expr) -> None:
        d = TypeDef(analyze(value, self.ctx))
        match self.ctx.get(target.id):
            case None:
                self.ctx[target.id] = d
            case _:
                self.ctx.issue(RedefinedName(self.ctx.file_path, get_range(target)))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> list[ast.stmt]:
        match node.target:
            case ast.Name(x):
                match node.annotation:
                    case ast.Name('type') if node.value:  # type alias
                        self._define_type(node.target, node.value)
                        return [node]
                    case _:  # variable declaration
                        d = VarDef(analyze(node.annotation, self.ctx))
                        if x not in self.ctx:
                            self.ctx[x] = d
                            body: list[ast.stmt] = []
                            if node.value:  # assignment
                                body.append(mk_assign(x, node.value))
                                self._check_type(x, d.typ, node.value, body)
                            return body
                        else:
                            self.ctx.issue(RedefinedName(self.ctx.file_path, get_range(node.target)))
                            return []
            case _:
                self.ctx.issue(InvalidTarget("illegal target for annotation assignment",
                                             self.ctx.file_path, get_range(node.target)))
                return []

    def visit_Assign(self, node: ast.Assign) -> list[ast.stmt]:
        body: list[ast.stmt] = [node]
        for target in node.targets:
            es = get_left_values(target)
            # Declare variables that are new
            for e in es:
                match e:
                    case ast.Name(x) if x not in self.ctx:
                        self.ctx[x] = VarDef(AnyType())
            # Check each left value
            for e in es:
                self._check_target_type(e, body)
        return body

    def _check_target_type(self, target: ast.expr, body: list[ast.stmt]) -> Type | None:
        match target:
            case ast.Name(x):
                match self.ctx.lookup(x):
                    case VarDef(tx):
                        self._check_type(x, tx, target, body)
                        return tx
                    case TypeDef() | TypeConstrDef() | AnnDef():
                        self.ctx.issue(InvalidTarget("not assignable", self.ctx.file_path, get_range(target)))

                return None

            case ast.Attribute(e, x):
                t = self._check_target_type(e, body)
                if t:
                    match t:
                        case ClassType(_, fs) if x in fs:
                            self._check_type(target, fs[x], target, body)
                            return fs[x]

                return None

            case ast.Subscript(e, ek):
                t = self._check_target_type(e, body)
                if t:
                    match t:
                        case ListType(te):
                            ts = t if isinstance(ek, ast.Slice) else te
                            self._check_type(target, ts, target, body)
                            return ts
                        case DictType(tk, tv):
                            self._check_type(ek, tk, target, body)
                            self._check_type(target, tv, target, body)
                            return tv

                return None

            case _:
                return None

    def visit_AugAssign(self, node: ast.AugAssign) -> list[ast.stmt]:
        body: list[ast.stmt] = [node]
        self._check_target_type(node.target, body)
        return body

    def visit_Expr(self, node: ast.Expr) -> list[ast.stmt]:
        match node.value:
            case ast.Call(ast.Name(name), _, _):
                match self.ctx.lookup(name):
                    case AnnDef('flat.py.fuzz'):
                        fuzz_call = self._resolve_fuzz(node.value)
                        return [ast.Expr(fuzz_call)]

        return [node]

    def _resolve_fuzz(self, call: ast.Call) -> ast.expr:
        if len(call.args) != 1:
            self.ctx.issue(ArityMismatch('flat.py.fuzz', 1, len(call.args),
                                         self.ctx.file_path, get_range(call.func)))
            return none_tree

        arg = call.args[0]
        match arg:
            case ast.Name(name):
                match self.ctx.lookup(name):
                    case FunDef(params, arguments, _, contracts):  # function to test
                        arg_producers: list[ast.expr] = []
                        vararg_producer: ast.expr = none_tree
                        named_producers: dict[str, ast.expr] = {}

                        if params.pos_variadic:  # all positional arguments are called positionally
                            for param in [*params.pos_only, *params.ordinary]:
                                producer = self._synth_producer(param, True, call)
                                assert producer is not None
                                arg_producers.append(producer)
                            producer = self._synth_producer(param, True, call)
                            assert producer is not None
                            vararg_producer = producer
                        else:  # only pos-only arguments are called positionally
                            for param in params.pos_only:
                                producer = self._synth_producer(param, True, call)
                                assert producer is not None
                                arg_producers.append(producer)
                            for param in params.ordinary:
                                producer = self._synth_producer(param, False, call)
                                if producer:
                                    named_producers[param.name] = producer

                        for param in params.kw_only:
                            producer = self._synth_producer(param, False, call)
                            if producer:
                                named_producers[param.name] = producer

                        kwarg_producer: ast.expr = none_tree
                        if params.kw_variadic:
                            for kw in call.keywords:
                                if kw.arg == params.kw_variadic:  # user-provided
                                    kwarg_producer = kw.value

                        num_inputs: ast.expr = ast.Constant(10)
                        for kw in call.keywords:
                            if kw.arg == 'num_inputs':
                                num_inputs = kw.value
                            elif kw.arg not in params.names:
                                self.ctx.issue(ExtraKeyword(f"unknown parameter '{kw.arg}'",
                                                            self.ctx.file_path, get_range(kw)))

                        pre_conds: list[ast.expr] = []
                        for contract in contracts:
                            match contract:
                                case Require(cond, _):
                                    pre_conds.append(cond)

                        predicate = ast.Lambda(arguments, ast.BoolOp(ast.And(), pre_conds)) if pre_conds else none_tree
                        args_producer: ast.expr = mk_call(f'{self.rt}.ArgsProducer',
                                                          ast.List(arg_producers),
                                                          vararg_producer,
                                                          ast.Dict([ast.Constant(x) for x in named_producers.keys()],
                                                                   list(named_producers.values())),
                                                          kwarg_producer,
                                                          predicate)
                        return mk_call(f'{self.rt}.fuzz', arg, num_inputs, args_producer)

        self.ctx.issue(InvalidArg('flat.py.fuzz', 'a function name',
                                  self.ctx.file_path, get_range(arg)))
        return none_tree

    def _synth_producer(self, param: Param, positional: bool, call: ast.Call) -> ast.expr | None:
        for kw in call.keywords:
            if kw.arg == param.name:  # user-provided
                return kw.value

        producer = param.typ.synth_producer(self.rt)
        if producer:  # type-guided synthesized
            return producer

        if param.default:  # use default value
            if positional:
                return mk_call(f'{self.rt}.ChoiceProducer', ast.List([param.default]))
            else:  # we do not have to pass this argument anyway
                return None

        self.ctx.issue(MissingKeyword(f"no producer given for argument '{param.name}'",
                                      self.ctx.file_path, get_range(call.func)))
        return none_tree
