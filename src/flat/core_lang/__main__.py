import os
import sys

from flat.core_lang.executor import Executor
from flat.core_lang.instrumentor import Instrumentor
from flat.core_lang.parser import parse_program
from flat.errors import Error


def compile_source(file_path: str):
    if not os.path.exists(file_path):
        print(f'Error: file not found: {file_path}')
        sys.exit(1)

    with open(file_path) as f:
        inp = f.read()
    filename = os.path.abspath(file_path)
    try:
        program = parse_program(inp, filename)
        instr = Instrumentor(filename, program)
        instrumented, types = instr()
        execute = Executor(instrumented, types)
        execute()
    except Error as err:
        err.print()


def print_usage():
    print('Usage: python -m flat.core_lang FILE')
    sys.exit(1)


if len(sys.argv) != 2:
    print_usage()
compile_source(sys.argv[1])
