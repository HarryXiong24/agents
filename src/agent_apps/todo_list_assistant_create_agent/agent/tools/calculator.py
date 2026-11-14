"""Perform arithmetic with explicit operations and finite-number checks."""

import math
from typing import Literal

from langchain_core.tools import tool

from ..errors import InputValueError


@tool
def calculate(
    a: float, b: float, operation: Literal["add", "subtract", "multiply", "divide"]
) -> str:
    """Add, subtract, multiply, or divide two numbers, including todo estimates.

    a is the first number; b is the second number.
    operation must be add, subtract, multiply, or divide.
    Example: seven 45-minute tasks use a=45, b=7, operation="multiply".
    Perform one operation per call; use the result in subsequent calls as needed.
    Nonfinite values, division by zero and numeric overflow are input errors.
    """
    print(f"Tool: Calculating {a} {operation} {b}.")
    if not math.isfinite(a) or not math.isfinite(b):
        raise InputValueError("Enter finite numbers.")

    # Explicit branches keep the code readable without evaluating generated code.
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    else:
        if b == 0:
            raise InputValueError("The divisor must not be zero.")
        result = a / b

    if not math.isfinite(result):
        raise InputValueError("The result is outside the supported numeric range.")
    return str(result)
