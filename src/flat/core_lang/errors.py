from traceback import FrameSummary

from flat.errors import Error


class ArityMismatch(Error):
    def __init__(self, expected: int, actual: int, frame: FrameSummary):
        super().__init__('Arity mismatch',
                         [f'expect:    {expected} argument(s)',
                          f'but given: {actual}'])

        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class TypeMismatch(Error):
    def __init__(self, expected: str, actual: str, frame: FrameSummary):
        super().__init__('Type mismatch',
                         [f'expect:    {expected}',
                          f'but found: {actual}'])
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


# runtime
class AssertionViolated(Error):
    def __init__(self, frame: FrameSummary):
        super().__init__(f'Assertion violated')
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class SyntaxViolated(Error):
    def __init__(self, expected: str, frame: FrameSummary):
        super().__init__(f'Syntax requirement violated: expect lang {expected}')
        self._frame = frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._frame]


class SemanticViolated(Error):
    def __init__(self, cond_frame: FrameSummary, value_frame: FrameSummary):
        super().__init__(f'Semantic constraint violated')
        self._cond_frame = cond_frame
        self._value_frame = value_frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._value_frame, self._cond_frame]


class PreconditionViolated(Error):
    def __init__(self, method: str, cond_frame: FrameSummary, call_frame: FrameSummary):
        """
        Constructor.
        :param method: method name.
        :param args: a list of formal argument names and their pretty-printed values.
        :param at: the position of the call statement where violation occurred.
        :param cond_pos: the position of the precondition.
        """
        # details = ['inputs:'] + [f'  {name} = {value}' for name, value in args]
        super().__init__(f'Precondition of method {method} violated')
        self._cond_frame = cond_frame
        self._call_frame = call_frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._call_frame, self._cond_frame]


class PostconditionViolated(Error):
    def __init__(self, method: str, cond_frame: FrameSummary, return_frame: FrameSummary):
        """
        Constructor.
        :param args: a list of formal argument names and their pretty-printed values.
        :param returns: the return param name and its pretty-printed value.
        :param at: the position of the return statement where violation occurred.
        :param cond_pos: the position of the postcondition.
        """
        # details = ['inputs:'] + [f'  {name} = {value}' for name, value in args] + [
        #     f'outputs:', f'  {returns[0]} = {returns[1]}']
        super().__init__(f'Postcondition of method {method} violated')
        self._cond_frame = cond_frame
        self._return_frame = return_frame

    def get_stack_frame(self) -> list[FrameSummary]:
        return [self._return_frame, self._cond_frame]
