import ast

from flat.py.diagnostics import Issuer
from flat.py.semantics import *
from flat.py.type_analysis import analyze_type
from flat.py.ast_helpers import *

def instrument(file_path: str, issuer: Issuer) -> ast.AST:
    ctx = Context(file_path, issuer)
    instrumentor = Instrumentor(ctx)
    with open(file_path, 'r') as f:
        source = f.read()
    tree = ast.parse(source, filename=file_path)
    return instrumentor.visit(tree)

lib: dict[str, dict[str, Def]] = {
    'flat.py': { 'lang': TypeConstrDef('flat.py.lang'),
                 'refine': TypeConstrDef('flat.py.refine') },
    'typing': { 'Any': TypeDef(AnyType()),
                'Literal': TypeConstrDef('typing.Literal'),
                'Union': TypeConstrDef('typing.Union'), 'Optional': TypeConstrDef('typing.Optional'),
                'Tuple': TypeConstrDef('tuple'), 'List': TypeConstrDef('list'),
                'Set': TypeConstrDef('set'), 'Dict': TypeConstrDef('dict') }
}

class Instrumentor(ast.NodeTransformer):
    ctx: Context

    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx

    # Function
    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        # Resolve signature
        args = self._resolve_arguments(node.args)
        arg_ids = [x for x, _ in args]
        return_type = analyze_type(node.returns, self.ctx) if node.returns else AnyType()
        contracts = [c for d in node.decorator_list for c in self._resolve_decorator(d)]
        fun_sig = FunDef(arg_ids, return_type, contracts)

        # Check argument types
        body: list[ast.stmt] = []
        for x, arg in args:
            match arg.kind:
                case 'arg':
                    body += self._check_type(x, arg.typ)
                case 'vararg':
                    y = self.ctx.fresh()
                    checks = self._check_type(y, arg.typ)
                    if len(checks) > 0:
                        body += [ast.For(mk_name(y), mk_name(x), checks, [])]
                case 'kwarg':
                    y = self.ctx.fresh()
                    checks = self._check_type(y, arg.typ)
                    if len(checks) > 0:
                        body += [ast.For(mk_name(y), mk_call_method(mk_name(x), 'values'), checks, [])]
        
        # Check pre-conditions
        for contract in contracts:
            match contract:
                case PreCond(p):
                    body += [mk_rt('check_pre', ast.Call(p, [mk_name(x) for x in arg_ids], []))]

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
            typ = analyze_type(arg.annotation, self.ctx) if arg.annotation else AnyType()
            default = node.defaults[i - num_non_default] if i >= num_non_default else None
            args += [(arg.arg, ArgDef(typ, 'arg', default))]
        if node.vararg:
            typ = analyze_type(node.vararg.annotation, self.ctx) if node.vararg.annotation else AnyType()
            args += [(node.vararg.arg, ArgDef(typ, 'vararg', None))]
        for arg, default in zip(node.kwonlyargs, node.kw_defaults):
            typ = analyze_type(arg.annotation, self.ctx) if arg.annotation else AnyType()
            args += [(arg.arg, ArgDef(typ, 'arg', default))]
        if node.kwarg:
            typ = analyze_type(node.kwarg.annotation, self.ctx) if node.kwarg.annotation else AnyType()
            args += [(node.kwarg.arg, ArgDef(typ, 'kwarg', None))]
        return args

    def _resolve_decorator(self, node: ast.expr) -> list[Contract]:
        raise NotImplementedError

    def _check_type(self, name: str, typ: Type) -> list[ast.stmt]:
        match typ:
            case AnyType():
                return []
            case _:
                return [mk_rt('check_type', mk_name(name), typ.ast)]
    
    # Return
    def visit_Return(self, node: ast.Return) -> list[ast.stmt]:
        fun = self.ctx.owner()
        assert fun is not None, "'return' outside function"
        
        # Store return value
        body: list[ast.stmt] = []
        return_value = node.value if node.value else ast.Constant(None)
        body += [mk_assign('__return__', return_value)]
        body += self._check_type('__return__', fun.return_type) # Check return type
        
        # Check post-conditions
        xs = fun.args + ['__return__']
        for contract in fun.contracts:
            match contract:
                case PostCond(p): # Assume: input arguments are immutable
                    body += [mk_rt('check_post', ast.Call(p, [mk_name(x) for x in xs], []))]
        
        # Done
        body += [ast.Return(mk_name('__return__'))]
        return body
    
    # Import
    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        known = lib[node.module] if node.module in lib else {}
        for alias in node.names:
            name = alias.asname or alias.name
            match self.ctx.get(name):
                case None:
                    d = known.get(alias.name, UnknownDef())
                    self.ctx[name] = d
                case _:
                    self.ctx.error(f"Name '{name}' is already defined", alias)
        
        return node
    
    # Global & Nonlocal

    def visit_Global(self, node: ast.Global) -> ast.Global:
        for id in node.names:
            match self.ctx.lookup_global(id):
                case None: # create a new global variable
                    self.ctx.create_global_var(id)
                case d:
                    self.ctx[id] = d

        return node
    
    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Nonlocal:
        for id in node.names:
            match self.ctx.lookup_global(id):
                case None:
                    self.ctx.error(f"No binding for nonlocal '{id}' found", node)
                case d:
                    self.ctx[id] = d

        return node
    
    # Declaration & Assignment

    def visit_TypeAlias(self, node: ast.TypeAlias) -> ast.TypeAlias:
        if len(node.type_params) == 0:
            self._check_type_alias(node.name, node.value)
        
        return node

    def _check_type_alias(self, target: ast.Name, value: ast.expr) -> None:
        d = TypeDef(analyze_type(value, self.ctx))
        match self.ctx.get(target.id):
            case None:
                self.ctx[target.id] = d
            case _: 
                self.ctx.error(f"Name '{target.id}' is already defined", target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> list[ast.stmt]:
        match node.target, node.annotation:
            case ast.Name(), ast.Name('type') if node.value: # type alias
                self._check_type_alias(node.target, node.value)
                return [node]
            case ast.Name(x), annot: # variable declaration
                body: list[ast.stmt] = [node]
                d = VarDef(analyze_type(annot, self.ctx))
                if node.value:
                    body += self._check_type(x, d.typ)
                match self.ctx.get(x):
                    case None:
                        self.ctx[x] = d
                    case _:
                        self.ctx.error(f"Name '{x}' is already defined", node)
                return body
            case _:  # do not support other targets for now
                self.ctx.warn("Type annotation is not supported for this left-value", node.target)
                return [node]

    def visit_Assign(self, node: ast.Assign) -> list[ast.stmt]:
        xs = [x for e in node.targets for x in get_left_vars(e)]
        # Declare variables that are new
        for x in xs:
            if self.ctx.get(x) is None:
                self.ctx[x] = VarDef(AnyType())
        # Type check
        body: list[ast.stmt] = [node]
        for x in xs:
            match self.ctx[x]:
                case VarDef(typ):
                    body += self._check_type(x, typ)
                case _:
                    self.ctx.error(f"Name '{x}' is not a variable", node)
        
        return body
    
    def visit_AugAssign(self, node: ast.AugAssign) -> list[ast.stmt]:
        body: list[ast.stmt] = [node]
        match node.target:
            case ast.Name(x):
                match self.ctx.lookup(x):
                    case None:
                        self.ctx.error(f"Name '{x}' is not defined", node.target)
                    case VarDef(typ):
                        body += self._check_type(x, typ)
                    case _:
                        self.ctx.error(f"Name '{x}' is not a variable", node.target)

        return body
