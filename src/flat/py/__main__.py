import argparse
import os
import sys

from flat.errors import Error
from flat.py.instrumentor import Instrumentor


def instrument(file_path: str, out_dir: str):
    if not os.path.exists(file_path):
        print(f'Error: file not found: {file_path}')
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)

    with open(file_path) as f:
        code = f.read()
    instrumentor = Instrumentor()
    output = instrumentor(os.path.abspath(file_path), code)

    base_name = os.path.basename(file_path)
    with open(os.path.join(out_dir, base_name), 'w') as f:
        f.write(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='flat.py')
    parser.add_argument('INPUT_FILE', help='input files')
    parser.add_argument('-o', '--output-dir', default='examples/out', help='output folder')

    args = parser.parse_args()
    try:
        instrument(args.INPUT_FILE, args.output_dir)
    except Error as err:
        err.print()
