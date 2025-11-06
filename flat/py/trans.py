import ast

from flat.py.type_trees import *
from flat.py.type_analysis import TypeAnalyzer

module_items: dict[str, dict[str, str]] = {
    'flat.py': {'lang': 'flat.py.lang', 'refine': 'flat.py.refine'},
    'typing': {'Any': 'typing.Any', 'Literal': 'typing.Literal', 'Union': 'typing.Union', 'Optional': 'typing.Optional', 'Tuple': 'tuple', 'List': 'list', 'Set': 'set', 'Dict': 'dict'}
}

class Instrumentor(ast.NodeTransformer):
    def __init__(self) -> None:
        self._imports: dict[str, str] = {}
        self._aliases: dict[str, Type] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        return super().visit_FunctionDef(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if node.module in module_items:
            items = module_items[node.module]
            for alias in node.names:
                if alias.name in items:
                    name = alias.asname or alias.name
                    self._imports[name] = items[alias.name]

        return node

    def visit_TypeAlias(self, node: ast.TypeAlias) -> ast.AST:
        typ = self._check_type_alias(node.name.id, node.value)
        if typ:
            return ast.Assign([node.name], typ.ast)
        
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        match node.target, node.annotation:
            case ast.Name() as target, ast.Name('type'):
                # my_type: type = ...
                typ = self._check_type_alias(target.id, node.value)
                if typ:
                    node = ast.Assign([target], typ.ast)
        return node
    
    def _check_type_alias(self, name: str, value: ast.expr) -> Type | None:
        if name in self._aliases:
            raise NameError(f"Type alias '{name}' is already defined.")
        typ = self._eval_type(value)
        if not isinstance(typ, AnyType):
            self._aliases[name] = typ
            return typ
        return None
    