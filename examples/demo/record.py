from dataclasses import dataclass
from flat.py import fuzz, lang
from flat.py.utils import print_fuzz_report

type A = lang('A', 'start: "a"+;')
type B = lang('B', 'start: "b"+;')

@dataclass
class Record:
    a_plus: A
    b_plus: B

def show_record(record: Record) -> str:
    return record.a_plus + ',' + record.b_plus

def main():
    report = fuzz(show_record, times=10)
    print_fuzz_report(report)