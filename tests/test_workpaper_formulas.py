"""Totals in the workpaper are live Excel formulas, and they add up to the
hand-calculated answers (see test_known_answers for how those were derived)."""

from decimal import Decimal as D

from openpyxl import load_workbook

from ar_handoff import runner

from conftest import AS_OF, FIXED_NOW, GOOD
from formula_eval import is_formula, value_of

CONTROL = D("60490.75")


def _run(settings, control=CONTROL):
    out = runner.run(settings, GOOD, AS_OF, control, "Op", now=FIXED_NOW)
    return load_workbook(out.workpaper)


def _find_row(ws, label, col=1):
    for row in ws.iter_rows():
        if row[col - 1].value == label:
            return row[col - 1].row
    raise AssertionError(f"No row labelled {label!r} on {ws.title}")


def test_summary_total_is_a_formula_that_adds_up(settings):
    wb = _run(settings)
    ws = wb["Summary"]
    r = _find_row(ws, "Total")
    assert ws.cell(row=r, column=2).value == f"=SUM(B8:B{r - 1})"
    assert ws.cell(row=r, column=3).value == f"=SUM(C8:C{r - 1})"
    assert value_of(wb, "Summary", f"B{r}") == D("60490.75")
    assert value_of(wb, "Summary", f"C{r}") == D("15")      # lines in the file
    # The six bucket amounts are the calculation script's answers, hand-checked.
    assert [value_of(wb, "Summary", f"B{i}") for i in range(8, r)] == [
        D("27750.00"), D("14000.00"), D("7350.50"),
        D("6575.25"), D("4175.00"), D("640.00")]


def test_reconciliation_follows_the_summary_and_subtracts_in_a_formula(settings):
    wb = _run(settings)
    ws = wb["Reconciliation"]
    assert ws["B4"].value.startswith("=Summary!B")
    assert ws["B6"].value == "=B4-B5"
    assert value_of(wb, "Reconciliation", "B4") == D("60490.75")
    assert value_of(wb, "Reconciliation", "B6") == D("0.00")


def test_reconciliation_difference_still_shows_a_break(settings):
    # GL balance 640.00 higher than the file: 60,490.75 - 61,130.75 = -640.00
    wb = _run(settings, control=D("61130.75"))
    assert value_of(wb, "Reconciliation", "B6") == D("-640.00")


def test_no_control_balance_means_no_difference_formula(settings):
    wb = _run(settings, control=None)
    ws = wb["Reconciliation"]
    assert ws["B5"].value == "Not entered"
    assert ws["B6"].value == "n/a"      # nothing to subtract, so no formula


def test_by_customer_totals_are_formulas_and_tie_to_the_summary(settings):
    wb = _run(settings)
    ws = wb["By Customer"]
    bottom = _find_row(ws, "Total")
    first = 4
    last_col = ws.max_column                      # the "Total" column
    # Every customer total and every bottom-row total is a formula.
    for r in range(first, bottom + 1):
        assert is_formula(ws.cell(row=r, column=last_col).value)
    assert all(is_formula(ws.cell(row=bottom, column=c).value)
               for c in range(3, last_col + 1))
    grand = value_of(wb, "By Customer", ws.cell(row=bottom, column=last_col).coordinate)
    assert grand == D("60490.75")
    # Down the Total column equals across the bottom row.
    down = sum(value_of(wb, "By Customer", ws.cell(row=r, column=last_col).coordinate)
               for r in range(first, bottom))
    across = sum(value_of(wb, "By Customer", ws.cell(row=bottom, column=c).coordinate)
                 for c in range(3, last_col))
    assert down == across == grand
