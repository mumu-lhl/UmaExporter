import sys


def is_nuitka() -> bool:
    """Check if running in a Nuitka compiled environment.

    Returns:
        bool: True if running under Nuitka, False otherwise.
    """
    return (
        "__compiled__" in globals()
        or hasattr(sys, "nuitka_version")
        or os.environ.get("NUITKA_BINARY_NAME") is not None
    )
