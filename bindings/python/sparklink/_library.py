"""Explicit independent application and Native library identities."""
import ctypes
import os

def load_library(stem, environment):
    path=os.environ.get(environment)
    # An explicit override either loads exactly that object or fails. Never
    # silently fall back to an installed/older library after an invalid path.
    # Runtime packages contain the ABI major, while the unversioned link is
    # a development/link-editor input. Python does not require that package.
    return ctypes.CDLL(path if path is not None else f"lib{stem}.so.0", use_errno=True)
