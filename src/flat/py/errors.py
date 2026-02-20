from dataclasses import dataclass
from traceback import FrameSummary, walk_tb
from typing import Tuple

from flat.errors import Error


@dataclass
class Loc:
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int


class InstrumentError(Error):
    def __init__(self, message: str, filename: str, name: str, loc: Loc):
        super().__init__(f'TypeError: {message}')
        self.filename = filename
        self.name = name
        self.loc = loc

    def get_stack_frame(self) -> list[FrameSummary]:
        frame = FrameSummary(self.filename, self.loc.lineno, self.name,
                             end_lineno=self.loc.end_lineno,
                             colno=self.loc.col_offset, end_colno=self.loc.end_col_offset)
        return [frame]


def _extract_stack(exc: Exception, drop: int = 0) -> list[FrameSummary]:
    stack = list(walk_tb(exc.__traceback__))
    if drop > 0:
        stack = stack[:-drop]

    summaries = []
    for frame, lineno in stack:
        if '__line__' in frame.f_locals:
            source = frame.f_globals['__source__']
            line = frame.f_locals['__line__']
        else:
            source = frame.f_code.co_filename
            line = lineno

        summaries.append(FrameSummary(source, line, frame.f_code.co_name))

    return summaries


class TypeMismatch(Error):
    def __init__(self, expected: str, actual: str, loc: Loc):
        super().__init__('Type mismatch',
                         [f'expect:    {expected}', f'but found: {actual}'])
        self.loc = loc

    def get_stack_frame(self) -> list[FrameSummary]:
        # Stack: frame of this fun, frame of the target fun, ...
        summaries = _extract_stack(self, 1)
        assert summaries[-1].lineno == self.loc.lineno
        summaries[-1].colno = self.loc.col_offset
        summaries[-1].end_lineno = self.loc.end_lineno
        summaries[-1].end_colno = self.loc.end_col_offset
        return summaries


class ArgTypeMismatch(Error):
    def __init__(self, expected: str, actual: str, k: int, of_method: str):
        super().__init__(f'Type mismatch for argument {k} of method {of_method}',
                         [f'expected type:    {expected}', f'actual value: {actual}'])

    def get_stack_frame(self) -> list[FrameSummary]:
        # Stack: frame of this fun, frame of the callee, frame of the caller, ...
        return _extract_stack(self, 2)


class PreconditionViolated(Error):
    def __init__(self, method: str, args: list[Tuple[str, str]]):
        details = ['inputs:'] + [f'  {name} = {value}' for name, value in args]
        super().__init__(f'Precondition of method {method} violated', details)

    def get_stack_frame(self) -> list[FrameSummary]:
        # Stack: frame of this fun, frame of the callee, frame of the caller, ...
        return _extract_stack(self, 1)


class PostconditionViolated(Error):
    def __init__(self, method: str, args: list[Tuple[str, str]], return_value: str, return_value_loc: Loc):
        details = ['inputs:'] + [f'  {name} = {value}' for name, value in args] + [
            f'outputs:', f'  {return_value}']
        super().__init__(f'Postcondition of method {method} violated', details)
        self.loc = return_value_loc

    def get_stack_frame(self) -> list[FrameSummary]:
        # Stack: frame of this fun, frame of the target fun, ...
        summaries = _extract_stack(self, 1)
        return_frame = FrameSummary(summaries[-1].filename, self.loc.lineno, summaries[-1].name,
                                    end_lineno=self.loc.end_lineno,
                                    colno=self.loc.col_offset, end_colno=self.loc.end_col_offset)
        summaries.insert(-1, return_frame)
        return summaries


class NoExpectedException(Error):
    def __init__(self, exc_type: type[BaseException], loc: Loc):
        super().__init__(f'No expected exception was raised: {exc_type.__name__}', [])
        self.loc = loc

    def get_stack_frame(self) -> list[FrameSummary]:
        summaries = _extract_stack(self, 2)
        raise_frame = FrameSummary(summaries[-1].filename, self.loc.lineno, summaries[-1].name,
                                   end_lineno=self.loc.end_lineno,
                                   colno=self.loc.col_offset, end_colno=self.loc.end_col_offset)
        summaries.append(raise_frame)
        return summaries
