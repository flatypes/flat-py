from flat.lang.diagnostics import Diagnostic, Location, Level

## Type analysis

class UndefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Undefined name: {id}")

class InvalidType(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg="Invalid type")

class ArityMismatch(Diagnostic):
    def __init__(self, id: str, expected: str, actual: int, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, 
                         msg=f"Type constructor '{id}' expects {expected} argument(s), got {actual}")

class InvalidLiteral(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg="Invalid literal value for 'typing.Literal'")

class InvalidFormat(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Invalid grammar format")

## Instrumentation

class RedefinedName(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Name '{id}' is already defined")

class UndefinedNonlocal(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Nonlocal name '{id}' is not defined in any enclosing scope")

class NotAssignable(Diagnostic):
    def __init__(self, id: str, loc: Location) -> None:
        super().__init__(level=Level.ERROR, loc=loc, msg=f"Name '{id}' is not assignable")

class UnsupportedFeature(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg="Unsupported feature")

class IgnoredAnnot(Diagnostic):
    def __init__(self, loc: Location) -> None:
        super().__init__(level=Level.WARN, loc=loc, msg="Type annotation is ignored")