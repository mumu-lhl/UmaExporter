import sys
import os


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


def normalize_outfit_id(outfit_id: str) -> str:
    """Normalize outfit ID. If it starts with '90' and is 6 digits, move '90' to the end.
    Example: '901071' -> '107190'
    """
    if outfit_id and len(outfit_id) == 6 and outfit_id.startswith("90"):
        return outfit_id[2:] + outfit_id[:2]
    return outfit_id
