import sys


def is_nuitka() -> bool:
    """Check if running in a Nuitka compiled environment.

    Nuitka sets __compiled__ as a global variable in compiled modules.
    This is the recommended way to detect Nuitka according to official docs.

    Returns:
        bool: True if running under Nuitka, False otherwise.
    """
    return "__compiled__" in globals()
