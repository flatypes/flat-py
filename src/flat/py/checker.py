import ast
from typing import Sequence

from flat.py.analyzer import analyze
from flat.py.ast_helpers import *
from flat.py.compile_time import *
from flat.py.diagnostics import *
from flat.py.runtime import SOURCE, LINENO, get_range

__all__ = ['check']


def check(tree: ast.Module, issuer: Issuer,
          *, file_path: str = '<module>', with_lineno: bool = True) -> ast.Module:
    """Check a Python module (AST) and instrument runtime type checks."""
    checker = Checker(Context(file_path, issuer), with_lineno=with_lineno)
    return checker.visit(tree)


lib: dict[str, dict[str, Def]] = {
    'flat.py': {'lang': TypeConstrDef('flat.py.lang'), 'refine': TypeConstrDef('flat.py.refine'),
                'types': AnnDef('flat.py.types'), 'requires': AnnDef('flat.py.requires'),
                'ensures': AnnDef('flat.py.ensures'), 'returns': AnnDef('flat.py.returns'), },
    'typing': {'Any': TypeDef(AnyType()),
               'Literal': TypeConstrDef('typing.Literal'),
               'Union': TypeConstrDef('typing.Union'), 'Optional': TypeConstrDef('typing.Optional'),
               'Tuple': TypeConstrDef('tuple'), 'List': TypeConstrDef('list'),
               'Set': TypeConstrDef('set'), 'Dict': TypeConstrDef('dict')}
}


class Checker(ast.NodeTransformer):
    """Runtime checks instrumentor."""

    def __init__(self, ctx: Context, *, rt: str = 'rt', with_lineno: bool = True) -> None:
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
        raise NotImplementedError

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Resolve signature
        args = self._resolve_arguments(node.args)
        arg_names = [x for x, _ in args]
        return_type = analyze(node.returns, self.ctx) if node.returns else AnyType()
        contracts, other_decorators = self._resolve_decorators(node.decorator_list)
        fun = FunDef(arg_names, return_type, contracts)

        # Pre-check: argument types
        body: list[ast.stmt] = []
        position = 0
        for x, arg in args:
            match arg.kind:
                case 'posonly':
                    self._check_arg_type(x, arg.typ, body, position=position, default=arg.default)
                    position += 1
                case 'normal':
                    self._check_arg_type(x, arg.typ, body, position=position, keyword=x, default=arg.default)
                    position += 1
                case '*':
                    # __position__ = position
                    # for __arg__ in x:
                    #    rt.check_arg_type(__arg__, arg.typ, position=__position__)
                    #    __position__ += 1
                    body.append(mk_assign('__position__', ast.Constant(position)))
                    vararg_body: list[ast.stmt] = []
                    self._check_arg_type('__arg__', arg.typ, vararg_body, position=ast.Name('__position__'))
                    body.append(mk_foreach('__arg__', ast.Name(x), vararg_body))
                case 'kwonly':
                    self._check_arg_type(x, arg.typ, body, keyword=x, default=arg.default)
                case '**':
                    # for __keyword__ in x:
                    #    rt.check_arg_type(x[__keyword__], arg.typ, keyword=__keyword__)
                    kwarg_body: list[ast.stmt] = []
                    self._check_arg_type(ast.Subscript(ast.Name(x), ast.Name('__keyword__')), arg.typ, kwarg_body,
                                         keyword=ast.Name('__keyword__'))
                    body.append(mk_foreach('__keyword__', ast.Name(x), kwarg_body))

        # Pre-check: contracts
        for contract in contracts:
            match contract:
                case Require(cond, cond_loc):
                    self._check_pre(cond, cond_loc, body)

        # Check body
        self.ctx.push(fun, defs=dict(args))
        self._check_body(node.body, body)
        self.ctx.pop()
        return ast.FunctionDef(node.name, erase_arguments_ann(node.args), body, list(other_decorators), None, None, [])

    def _resolve_arguments(self, node: ast.arguments) -> Sequence[tuple[str, ArgDef]]:
        args: list[tuple[str, ArgDef]] = []

        i = 0
        default_start = len(node.posonlyargs) + len(node.args) - len(node.defaults)
        for arg in node.posonlyargs:  # position-only arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - default_start] if i >= default_start else None
            args.append((arg.arg, ArgDef(typ, 'posonly', default)))
            i += 1

        for arg in node.args:  # normal arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - default_start] if i >= default_start else None
            args.append((arg.arg, ArgDef(typ, 'normal', default)))
            i += 1

        if node.vararg:  # variadic positional argument *arg
            typ = analyze(node.vararg.annotation, self.ctx) if node.vararg.annotation else AnyType()
            args.append((node.vararg.arg, ArgDef(typ, '*', None)))

        for arg, default in zip(node.kwonlyargs, node.kw_defaults):  # keyword-only arguments
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            args.append((arg.arg, ArgDef(typ, 'kwonly', default)))

        if node.kwarg:  # variadic keyword argument **kwarg
            typ = analyze(node.kwarg.annotation, self.ctx) if node.kwarg.annotation else AnyType()
            args.append((node.kwarg.arg, ArgDef(typ, '**', None)))

        return args

    def _resolve_decorators(self, decorators: Sequence[ast.expr]) -> tuple[Sequence[Contract], Sequence[ast.expr]]:
        contracts: list[Contract] = []
        others: list[ast.expr] = []
        for decorator in decorators:
            match decorator:
                case ast.Call(ast.Name(f), args, _):
                    match self.ctx.lookup(f):
                        case AnnDef('flat.py.types'):
                            raise NotImplementedError
                        case AnnDef('flat.py.requires'):
                            for arg in args:
                                contracts.append(Require(to_expr(arg), arg))
                        case AnnDef('flat.py.ensures'):
                            for arg in args:
                                contracts.append(Ensure(to_expr(arg), arg))
                        case AnnDef('flat.py.returns'):
                            if len(args) == 1:
                                arg = args[0]
                                contracts.append(Ensure(mk_eq(ast.Name('_'), to_expr(arg)), decorator))
                            else:
                                self.ctx.issue(ArityMismatch("annotation 'returns'", 1, len(args),
                                                             self.ctx.get_loc(decorator)))
                        case _:
                            others.append(decorator)
                case _:
                    others.append(decorator)

        return contracts, others

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
            default = ast.Constant(None)
        else:
            default = self._mk_range(default)
        body.append(ast.Expr(mk_call(f'{self.rt}.check_arg_type', actual, expected.ast,
                                     position, keyword, default)))

    def _mk_range(self, node: ast.AST) -> ast.expr:
        node_range = get_range(node)
        return mk_call(f'{self.rt}.Range', node_range.lineno, node_range.end_lineno,
                       node_range.col_offset, node_range.end_col_offset)

    def _check_pre(self, cond: ast.expr, cond_tree: ast.expr, body: list[ast.stmt]) -> None:
        body.append(ast.Expr(mk_call(f'{self.rt}.check_pre', cond, self._mk_range(cond_tree))))

    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        fun = self.ctx.owner()
        assert fun is not None, "'return' outside function"

        # Post-check: return type
        body: list[ast.stmt] = []
        return_value = node.value if node.value else ast.Constant(None)
        body.append(mk_assign('_', return_value))
        self._check_type('_', fun.return_type, node.value, body)

        # Post-check: contracts
        for contract in fun.contracts:
            match contract:
                case Ensure(cond, cond_loc):  # Assume: input arguments are immutable
                    self._check_post(cond, cond_loc, node, body)

        # Done
        body.append(ast.Return(ast.Name('_')))
        return body

    def _check_type(self, actual: str | ast.expr, expected: Type, actual_tree: ast.expr, body: list[ast.stmt]) -> None:
        match expected:
            case AnyType():
                pass
            case _:
                if isinstance(actual, str):
                    actual = ast.Name(actual)
                elif not pure(actual):
                    x = self.ctx.fresh()
                    body.append(mk_assign(x, actual))
                    actual = ast.Name(x)
                body.append(ast.Expr(mk_call(f'{self.rt}.check_type', actual, expected.ast,
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
                    self.ctx.issue(RedefinedName(x, self.ctx.get_loc(alias)))

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
                    self.ctx.issue(UndefinedNonlocal(name, self.ctx.get_loc(node)))
                case d:
                    self.ctx[name] = d

        return node

    def visit_TypeAlias(self, node: ast.TypeAlias) -> ast.TypeAlias:
        if len(node.type_params) == 0:
            self._check_type_alias(node.name, node.value)

        return node

    def _check_type_alias(self, target: ast.Name, value: ast.expr) -> None:
        d = TypeDef(analyze(value, self.ctx))
        match self.ctx.get(target.id):
            case None:
                self.ctx[target.id] = d
            case _:
                self.ctx.issue(RedefinedName(target.id, self.ctx.get_loc(target)))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> list[ast.stmt]:
        body: list[ast.stmt] = [node]
        match node.target, node.annotation:
            case ast.Name(), ast.Name('type') if node.value:  # type alias
                self._check_type_alias(node.target, node.value)
                return body
            case ast.Name(x), a:  # variable declaration
                d = VarDef(analyze(a, self.ctx))
                if x not in self.ctx:
                    self.ctx[x] = d
                    if node.value:  # assignment
                        self._check_type(x, d.typ, node.value, body)
                else:
                    self.ctx.issue(RedefinedName(x, self.ctx.get_loc(node.target)))
            case e, a:  # ignore annotation and regard it as assignment
                # self.ctx.issue(IgnoredAnnot(self.ctx.get_loc(node.annotation)))
                if node.value:
                    self._check_left_value(e, body)
        return body

    def _check_left_value(self, value: ast.expr, body: list[ast.stmt]) -> Type | None:
        match value:
            case ast.Name(x):
                match self.ctx.lookup(x):
                    case None:
                        self.ctx.issue(UndefinedName(x, self.ctx.get_loc(value)))
                        return None
                    case VarDef(tx):
                        self._check_type(x, tx, value, body)
                        return tx
                    case _:
                        self.ctx.issue(NotAssignable(x, self.ctx.get_loc(value)))
                        return None
            case ast.Attribute(e, x):
                t = self._check_left_value(e, body)
                if t:
                    match t:
                        case ClassType(_, fs) if x in fs:
                            self._check_type(value, fs[x], value, body)
                            return fs[x]
                return None
            case ast.Subscript(e, ek):
                t = self._check_left_value(e, body)
                if t:
                    match t:
                        case ListType(te):
                            ts = t if isinstance(ek, ast.Slice) else te
                            self._check_type(value, ts, value, body)
                            return ts
                        case DictType(tk, tv):
                            self._check_type(ek, tk, value, body)
                            self._check_type(value, tv, value, body)
                            return tv
                return None
            case _:
                return None

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
                self._check_left_value(e, body)
        return body

    def visit_AugAssign(self, node: ast.AugAssign) -> list[ast.stmt]:
        body: list[ast.stmt] = [node]
        self._check_left_value(node.target, body)
        return body
