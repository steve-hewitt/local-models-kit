"""Run with: python -m pytest test_calc.py -q   (or: python test_calc.py)"""
from calc import add, mul, div


def test_add():
    assert add(2, 3) == 5


def test_mul():
    assert mul(2, 3) == 6
    assert mul(-4, 5) == -20
    assert mul(0, 99) == 0


def test_div():
    assert div(10, 2) == 5


if __name__ == "__main__":
    test_add()
    test_mul()
    test_div()
    print("all tests passed")
