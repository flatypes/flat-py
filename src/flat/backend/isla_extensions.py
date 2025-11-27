from isla.derivation_tree import DerivationTree
from isla.language import StructuralPredicate
from isla.type_defs import Path

from flat.selectors import children_labelled_with


def ebnf_direct_child(tree: DerivationTree, path: Path, parent_path: Path) -> bool:
    """
    Test if the node a direct child of another node in EBNF.
    :param tree: the full derivation tree
    :param path: the path of the testing node.
    :param parent_path: the path of the parent node.
    """
    node = tree.get_subtree(path)
    children = children_labelled_with(tree.get_subtree(parent_path), node.root_nonterminal()[1:-1])
    return node in children


EBNF_DIRECT_CHILD = StructuralPredicate('ebnf_direct_child', 2, ebnf_direct_child)


def ebnf_kth_child(tree: DerivationTree, path: Path, parent_path: Path, k: str | int) -> bool:
    """
    Test if the node is the k-th direct child (with the same type) of another node in EBNF.
    :param tree: the full derivation tree
    :param path: the path of the testing node.
    :param parent_path: the path of the parent node.
    :param k: the position, starting at 1.
    """
    node = tree.get_subtree(path)
    children = children_labelled_with(tree.get_subtree(parent_path), node.root_nonterminal()[1:-1])
    if len(children) >= int(k):
        return node == children[int(k) - 1]
    return False


EBNF_KTH_CHILD = StructuralPredicate('ebnf_kth_child', 3, ebnf_kth_child)
