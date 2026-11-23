"""A tiny, independent evaluator for the three kinds of formula the workpaper uses.

openpyxl writes formulas but does not calculate them (Excel does that when the
file is opened), so a test can't just read the answer back. This module follows
the formula text itself, so the tests can check what Excel *will* show:

    =SUM(B8:B13)        add a range of cells
    =Summary!B14        point at a cell on another sheet
    =B4-B5              subtract one cell from another
"""

from __future__ import annotations

import re
from decimal import Decimal

from openpyxl.utils import range_boundaries

RANGE = re.compile(r"^SUM\(([A-Z]+\d+:[A-Z]+\d+)\)$")
REF = re.compile(r"^(?:(\w+)!)?([A-Z]+\d+)$")
DIFF = re.compile(r"^([A-Z]+\d+)-([A-Z]+\d+)$")


def is_formula(value) -> bool:
    return isinstance(value, str) and value.startswith("=")


def value_of(wb, sheet: str, coord: str) -> Decimal:
    """The number Excel will show in this cell."""
    raw = wb[sheet][coord].value
    if not is_formula(raw):
        return Decimal(str(raw)) if raw not in (None, "") else Decimal("0")
    expr = raw[1:]
    m = RANGE.match(expr)
    if m:
        c1, r1, c2, r2 = range_boundaries(m.group(1))
        return sum((value_of(wb, sheet, wb[sheet].cell(row=r, column=c).coordinate)
                    for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)),
                   Decimal("0"))
    m = DIFF.match(expr)
    if m:
        return value_of(wb, sheet, m.group(1)) - value_of(wb, sheet, m.group(2))
    m = REF.match(expr)
    if m:
        return value_of(wb, m.group(1) or sheet, m.group(2))
    raise ValueError(f"Formula not supported by the test evaluator: {raw}")
