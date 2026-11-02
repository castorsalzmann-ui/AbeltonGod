"""Not collected by a normal run (no ``test_`` prefix). ``test_leak_guard.py`` runs it in a
subprocess: the first test leaves a handled exception in its thread on purpose."""

from __future__ import annotations

import ctypes
import sys


def test_leaks_a_handled_exception() -> None:
    ctypes.pythonapi.PyErr_SetHandledException.argtypes = [ctypes.py_object]
    ctypes.pythonapi.PyErr_SetHandledException(ValueError("planted leak"))
    assert sys.exception() is not None


def test_after_one() -> None:
    assert True


def test_after_two() -> None:
    assert True
