"""Tiny module with one deliberate bug. See TASK.md."""


def add(a, b):
    return a + b


def mul(a, b):
    # BUG: this adds instead of multiplying.
    return a + b


def div(a, b):
    if b == 0:
        raise ValueError("division by zero")
    return a / b
