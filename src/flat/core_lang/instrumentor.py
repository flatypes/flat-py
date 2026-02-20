from typing import Any

from flat.core_lang.ast import *
from flat.core_lang.cond import CoreCond
from flat.core_lang.errors import *
from flat.core_lang.typer import Typer
from flat.errors import Redefined, Undefined
from flat.pos import NoPos
from flat.typing import *


@dataclass(frozen=True)
class FunSig:
    name: str
    params: list[Tuple[str, Type]]
    returns: Optional[Type]
    preconditions: list[Expr]  # bind params
    postconditions: list[Expr]  # bind params and '_' for return value

    @property
    def param_names(self) -> list[str]:
        return [x for x, _ in self.params]

    @property
    def param_types(self) -> list[Type]:
        return [t for _, t in self.params]


class FunContext:
    def __init__(self, fun: FunSig, annots: dict[str, Type]):
        self.fun = fun
        self.vars = annots


class Instrumentor:
    def __init__(self, filename: str, program: Program):
        self.typer = Typer(filename)
        self.program = program
        self._methods: dict[str, FunSig] = {}
        self._next_counter: int = 0
        self._runtime_errors: dict[str, Error] = {}

    def __call__(self) -> Tuple[Program, dict[str, Any]]:
        body = []
        for tree in self.program:
            body += self.visit_def(tree)
        return body, self.typer.get_types() | self._runtime_errors

    def frame_from_pos(self, pos: Pos) -> FrameSummary:
        return self.typer.frame_from_pos(pos)

    def visit_def(self, tree: Def) -> list[Def]:
        match tree:
            case LangDef() as lang:
                self.typer.check_and_define_lang(lang)
                return []
            case MethodDef(ident, params, returns, specs, body) as m:
                if ident.name in self._methods:
                    raise Redefined('method', ident.name, self.frame_from_pos(ident.pos))

                scope: dict[str, Type] = {}
                # check params
                method_params: list[Tuple[str, Type]] = []
                for param_ident, type_annot in params:
                    if any([x == param_ident.name for x, _ in method_params]):
                        raise Redefined('param', param_ident.name, self.frame_from_pos(param_ident.pos))

                    typ = self.typer.expand(type_annot)
                    method_params.append((param_ident.name, typ))
                    scope[param_ident.name] = typ

                # check pre-conditions
                preconditions: list[Expr] = []
                for spec in specs:
                    match spec:
                        case MethodPreSpec(cond):
                            self.typer.ensure_bool(cond, scope)
                            preconditions.append(cond)

                # check return param
                if returns:
                    return_typ = self.typer.expand(returns)
                    scope['_'] = return_typ
                else:
                    return_typ = None

                # check post-conditions
                postconditions: list[Expr] = []
                for spec in specs:
                    match spec:
                        case MethodPostSpec(cond):
                            self.typer.ensure_bool(cond, scope)
                            postconditions.append(cond)

                # build method info
                sig = FunSig(ident.name, method_params, return_typ, preconditions, postconditions)
                self._methods[ident.name] = sig

                # check body
                new_body = []
                for stmt in body:
                    new_body += self.visit_stmt(stmt, FunContext(sig, scope))
                return [MethodDef(ident, params, returns, [], new_body)]
            case _:
                raise NotImplementedError

    def visit_stmt(self, stmt: Stmt, ctx: FunContext) -> list[Stmt]:
        match stmt:
            case Declare(Ident(name, pos), type_annot):
                if name in ctx.vars:
                    raise Redefined('var', name, self.frame_from_pos(pos))

                ctx.vars[name] = self.typer.expand(type_annot)
                return [stmt]

            case Assign(Ident(name, pos), value):
                if name not in ctx.vars:
                    raise Undefined('param', name, self.frame_from_pos(pos))

                typ = ctx.vars[name]
                check = self.check_type(value, name, typ, ctx.vars)
                return [stmt] + check

            case Call(Ident(name, pos), args) as node:
                if name not in self._methods:
                    raise Undefined('method', name, self.frame_from_pos(pos))

                m = self._methods[name]
                # evaluate args and check their types
                body: list[Stmt] = []
                new_args = []
                if len(args) != len(m.params):
                    raise ArityMismatch(len(m.params), len(args), pos)
                for arg, t in zip(args, m.param_types):
                    x = self.fresh_name()
                    body += [Assign(Ident(x, arg.pos), arg)]
                    body += self.check_type(arg, x, t, ctx.vars)
                    new_args.append(Var(Ident(x, arg.pos)))
                # check pre
                mappings = dict(zip(m.param_names, new_args))
                for cond in m.preconditions:
                    # trigger = ([x.name for x in new_args],
                    #            lambda vs: PreconditionViolated(method.name, zip(m.param_names, vs),
                    #                                            stmt.pos, cond.pos))
                    # body += [Assert(subst_expr(cond, mappings), trigger)]
                    err_name = self.visit_error(PreconditionViolated(m.name,
                                                                     self.frame_from_pos(cond.pos),
                                                                     self.frame_from_pos(pos)))
                    body += [Assert(subst_expr(cond, mappings), err_name)]
                # call
                body += [Call(Ident(name, pos), new_args, var=node.var)]
                # record return type
                if node.var:
                    assert m.returns is not None
                    ctx.vars[node.var.name] = m.returns

                return body

            case Assert(cond):
                self.typer.ensure_bool(cond, ctx.vars)
                err_name = self.visit_error(AssertionViolated(self.frame_from_pos(cond.pos)))
                return [Assert(cond, err_name)]

            case Return(None):
                if ctx.fun.returns is not None:
                    raise TypeError
                    # self.issuer.error(TypeMismatch(pretty_tree(this_m.return_type), 'unit', stmt.pos))
                return [stmt]

            case Return(value):
                if ctx.fun.returns is None:
                    raise TypeError
                    # self.issuer.error(TypeMismatch('unit', pretty_tree(this_m.return_type), value.pos))
                    # return [stmt]

                assert value is not None
                body = [Assign(Ident('_', value.pos), value)]  # evaluate return value
                body += self.check_type(value, '_', ctx.fun.returns, ctx.vars)  # check type
                # check post condition
                return_value = Var(Ident('_', NoPos))
                # mappings = {this_m.return_param_name: return_value}
                for cond in ctx.fun.postconditions:
                    #     trigger = (this_m.param_names + [return_var],
                    #                lambda vs: PostconditionViolated(zip(this_m.param_names, vs[:-1]),
                    #                                                 (this_m.return_param_name, vs[-1]),
                    #                                                 value.pos, cond.pos))
                    err_name = self.visit_error(PostconditionViolated(ctx.fun.name,
                                                                      self.frame_from_pos(cond.pos),
                                                                      self.frame_from_pos(value.pos)))
                    body += [Assert(cond, err_name)]
                # return
                body += [Return(return_value)]
                return body

            case If(cond, then_body, else_body):
                self.typer.ensure_bool(cond, ctx.vars)

                new_then = []
                for stmt in then_body:
                    new_then += self.visit_stmt(stmt, ctx)

                new_else = []
                for stmt in else_body:
                    new_else += self.visit_stmt(stmt, ctx)

                return [If(cond, new_then, new_else)]

            case While(cond, body):
                self.typer.ensure_bool(cond, ctx.vars)

                new_body = []
                for stmt in body:
                    new_body += self.visit_stmt(stmt, ctx)

                return [While(cond, new_body)]

            case _:
                raise NotImplementedError

    def check_type(self, value: Expr, alias: str, against: Type, ctx: dict[str, Type]) -> list[Stmt]:
        self.typer.ensure(value, get_base_type(against), ctx)
        match against:
            case LangType(grammar):
                err_name = self.visit_error(SyntaxViolated(grammar.name, self.frame_from_pos(value.pos)))
                return [Assert(InLang(Var(Ident(alias, NoPos)), Ident(grammar.name, NoPos), NoPos), err_name)]
            case RefinementType(_, CoreCond(cond)):
                err_name = self.visit_error(
                    SemanticViolated(self.frame_from_pos(cond.pos), self.frame_from_pos(value.pos)))
                return [Assert(subst_expr(cond, {'_': Var(Ident(alias, NoPos))}), err_name)]
            case _:
                return []

    def fresh_name(self) -> str:
        self._next_counter += 1
        return f'_{self._next_counter}'

    def visit_error(self, error: Error) -> str:
        name = self.fresh_name()
        self._runtime_errors[name] = error
        return name
