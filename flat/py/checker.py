import ast

from flat.py.analyzer import analyze
from flat.py.ast_helpers import *
from flat.py.compile_time import *
from flat.py.diagnostics import *

__all__ = ['check']


def check(tree: ast.Module, issuer: Issuer, *, file_path: str = '<module>') -> ast.Module:
    """Check a Python module (AST) and instrument runtime type checks."""
    instrumentor = Instrumentor(Context(file_path, issuer))
    return instrumentor.visit(tree)


lib: dict[str, dict[str, Def]] = {
    'flat.py': {'lang': TypeConstrDef('flat.py.lang'),
                'refine': TypeConstrDef('flat.py.refine')},
    'typing': {'Any': TypeDef(AnyType()),
               'Literal': TypeConstrDef('typing.Literal'),
               'Union': TypeConstrDef('typing.Union'), 'Optional': TypeConstrDef('typing.Optional'),
               'Tuple': TypeConstrDef('tuple'), 'List': TypeConstrDef('list'),
               'Set': TypeConstrDef('set'), 'Dict': TypeConstrDef('dict')}
}


class Instrumentor(ast.NodeTransformer):
    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx

    # Class & Function Definitions

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        raise NotImplementedError

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Resolve signature
        args = self._resolve_arguments(node.args)
        arg_ids = [x for x, _ in args]
        return_type = analyze(node.returns, self.ctx) if node.returns else AnyType()
        contracts = [c for d in node.decorator_list for c in self._resolve_decorator(d)]
        fun_sig = FunDef(arg_ids, return_type, contracts)

        # Check argument types
        body: list[ast.stmt] = []
        for x, arg in args:
            match arg.kind:
                case 'arg':
                    self._check_type(ast.Name(x), arg.typ, body)
                case 'vararg':
                    self._check_type(ast.Name(x), SeqType(arg.typ), body)
                case 'kwarg':
                    self._check_type(ast.Attribute(ast.Name(x), 'values'), SeqType(arg.typ), body)

        # Check pre-conditions
        for contract in contracts:
            match contract:
                case PreCond(p):
                    body += [ast.Expr(mk_call_rt('check_pre', mk_call(p, *(ast.Name(x) for x in arg_ids))))]

        # Set up function context and check body
        self.ctx.push(fun_sig, defs=dict(args))
        for stmt in node.body:
            new_stmts: ast.stmt | list[ast.stmt] = self.visit(stmt)
            if isinstance(new_stmts, ast.stmt):
                new_stmts = [new_stmts]
            body += new_stmts
        self.ctx.pop()

        # Done
        node.body = body
        return node

    def _resolve_arguments(self, node: ast.arguments) -> list[tuple[str, ArgDef]]:
        args: list[tuple[str, ArgDef]] = []
        pos_args = node.posonlyargs + node.args
        num_non_default = len(pos_args) - len(node.defaults)
        for arg, i in zip(pos_args, range(len(pos_args))):
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - num_non_default] if i >= num_non_default else None
            args += [(arg.arg, ArgDef(typ, 'arg', default))]
        if node.vararg:
            typ = analyze(node.vararg.annotation, self.ctx) if node.vararg.annotation else AnyType()
            args += [(node.vararg.arg, ArgDef(typ, 'vararg', None))]
        for arg, default in zip(node.kwonlyargs, node.kw_defaults):
            typ = analyze(arg.annotation, self.ctx) if arg.annotation else AnyType()
            args += [(arg.arg, ArgDef(typ, 'arg', default))]
        if node.kwarg:
            typ = analyze(node.kwarg.annotation, self.ctx) if node.kwarg.annotation else AnyType()
            args += [(node.kwarg.arg, ArgDef(typ, 'kwarg', None))]
        return args

    def _resolve_decorator(self, node: ast.expr) -> list[Contract]:
        raise NotImplementedError

    def _check_type(self, value: str | ast.expr, typ: Type, body: list[ast.stmt]) -> None:
        match typ:
            case AnyType():
                pass
            case _:
                if isinstance(value, str):
                    value = ast.Name(value)
                if not pure(value):
                    x = self.ctx.fresh()
                    body.append(mk_assign(x, value))
                    value = ast.Name(x)
                body.append(ast.Expr(mk_call_rt('check_type', value, typ.ast)))

    # Return Statements
    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        fun = self.ctx.owner()
        assert fun is not None, "'return' outside function"

        # Store return value
        body: list[ast.stmt] = []
        return_value = node.value if node.value else ast.Constant(None)
        body += [mk_assign('__return__', return_value)]
        self._check_type(ast.Name('__return__'), fun.return_type, body)  # Check return type

        # Check post-conditions
        xs = [*fun.args, '__return__']
        for contract in fun.contracts:
            match contract:
                case PostCond(p):  # Assume: input arguments are immutable
                    body += [ast.Expr(mk_call_rt('check_post', mk_call(p, *(ast.Name(x) for x in xs))))]

        # Done
        body += [ast.Return(ast.Name('__return__'))]
        return body

    # Import Statements
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

    # Global & Nonlocal

    def visit_Global(self, node: ast.Global) -> ast.Global:
        for id in node.names:
            match self.ctx.lookup_global(id):
                case None:  # create a new global variable
                    self.ctx.create_global_var(id)
                case d:
                    self.ctx[id] = d

        return node

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Nonlocal:
        for id in node.names:
            match self.ctx.lookup_nonlocal(id):
                case None:
                    self.ctx.issue(UndefinedNonlocal(id, self.ctx.get_loc(node)))
                case d:
                    self.ctx[id] = d

        return node

    # Declaration & Assignment

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
                        self._check_type(ast.Name(x), d.typ, body)
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
                        self._check_type(ast.Name(x), tx, body)
                        return tx
                    case _:
                        self.ctx.issue(NotAssignable(x, self.ctx.get_loc(value)))
                        return None
            case ast.Attribute(e, x):
                t = self._check_left_value(e, body)
                if t:
                    match t:
                        case ClassType(_, fs) if x in fs:
                            self._check_type(value, fs[x], body)
                            return fs[x]
                return None
            case ast.Subscript(e, ek):
                t = self._check_left_value(e, body)
                if t:
                    match t:
                        case ListType(te):
                            ts = t if isinstance(ek, ast.Slice) else te
                            self._check_type(value, ts, body)
                            return ts
                        case DictType(tk, tv):
                            self._check_type(ek, tk, body)
                            self._check_type(value, tv, body)
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
