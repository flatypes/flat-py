from traceback import FrameSummary
from traceback import StackSummary
from typing import Optional


class Error(RuntimeError):
    summary: str
    details: list[str]

    def __init__(self, summary: str, details: Optional[list[str]] = None):
        self.summary = summary
        if details:
            self.details = details
        else:
            self.details = []

    def get_stack_frame(self) -> list[FrameSummary]:
        return []

    def __str__(self) -> str:
        return self.summary + '\n' + '\n'.join(['  ' + msg for msg in self.details])

    def print(self) -> None:
        stack_summary = StackSummary.from_list(self.get_stack_frame())
        print('Traceback (most recent call last):', flush=True)
        for line in stack_summary.format():
            print(line, end='', flush=True)
        print(str(self), flush=True)
        print('')


class ParsingError(Error):
    def __init__(self, expected: list[str], frame: FrameSummary):
        if len(expected) == 1:
            msg = expected[0]
        else:
            msg = f"one of {', '.join(expected)}"
        super().__init__(f'Parsing error: expect {msg}')
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class Undefined(Error):
    def __init__(self, kind: str, name: str, frame: FrameSummary):
        super().__init__(f'Undefined {kind}: {name}')
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class Redefined(Error):
    def __init__(self, kind: str, name: str, frame: FrameSummary):
        super().__init__(f'Redefined {kind}: {name}')
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class MissingStartRule(Error):
    def __init__(self):
        super().__init__('Missing start rule')


class UnusedRule(Error):
    def __init__(self, name: str, frame: FrameSummary):
        super().__init__(f'Rule {name} is defined but not used', ['Hint: you may delete this rule'])
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]
