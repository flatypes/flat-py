import ast
import os
import sys
from argparse import ArgumentParser

from flat.py.checker import check
from flat.py.diagnostics import Issuer


def check_path(path: str, out_dir: str) -> None:
    if not os.path.exists(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    issuer = Issuer()
    os.makedirs(out_dir, exist_ok=True)
    if os.path.isfile(path):
        process_file(path, issuer, out_dir)
    else:
        for entry in os.listdir(path):
            entry_path = os.path.join(path, entry)
            if os.path.isfile(entry_path) and entry_path.endswith('.py'):
                process_file(entry_path, issuer, out_dir)
    if issuer.has_diagnostics:
        print(issuer.pretty(), file=sys.stderr)


def process_file(file_path: str, issuer: Issuer, out_dir: str) -> None:
    with open(file_path) as f:
        source = f.read()
    tree = ast.parse(source, filename=file_path)
    out_tree = check(tree, issuer)
    if not issuer.has_errors:
        ast.fix_missing_locations(out_tree)
        out_source = ast.unparse(out_tree)
        base_name = os.path.basename(file_path)
        out_path = os.path.join(out_dir, base_name)
        with open(out_path, 'w') as f:
            f.write(out_source)
        print(f"File processed: {file_path} -> {out_path}")


if __name__ == '__main__':
    parser = ArgumentParser(prog='flat.py')
    parser.add_argument('INPUT_FILE', help='input files')
    parser.add_argument('-o', '--output-dir', default='examples/out', help='output folder')

    args = parser.parse_args()
    check_path(args.INPUT_FILE, args.output_dir)
