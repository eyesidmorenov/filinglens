"""Exceptions raised by the module."""


class IndexCompatibilityError(RuntimeError):
    """The index does not exist or its mapping is not the one the team loader creates."""
