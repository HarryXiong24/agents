"""Mark explicit input/data validation separately from unexpected program errors."""


class InputValueError(ValueError):
    """A known invalid value that a user or model can correct."""


class InputTypeError(TypeError):
    """A known invalid input type; still a TypeError for direct Python callers."""
