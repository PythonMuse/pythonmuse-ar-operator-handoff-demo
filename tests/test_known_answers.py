"""Known answers for sample_data/AR_Open_Items_2026-10-31.csv.

Every expected figure below was calculated BY HAND from the sample file before
these assertions were written. The code is checked against these numbers, not
against whatever it happened to produce.

As-of date 2026-10-31. Days past due = as-of date minus due date.

Line  Invoice    Customer  Due date     Days  Bucket       Amount
  2   INV-10001  C001      2026-11-15    -15  Current     1,250.00
  3   INV-10002  C001      2026-10-01     30  1-30        2,400.00
  4   INV-10003  C002      2026-10-31      0  Current     8,000.00
  5   INV-10004  C002      2026-09-30     31  31-60       3,150.50
  6   INV-10005  C003      2026-09-01     60  31-60       4,200.00
  7   INV-10006  C003      2026-08-31     61  61-90         975.25
  8   INV-10007  C004      2026-08-02     90  61-90       5,600.00  (exactly 90: NOT flagged)
  9   INV-10008  C004      2026-08-01     91  Over 90     1,875.00  flagged
 10   INV-10009  C005      2026-07-03    120  Over 90     2,300.00  flagged
 11   INV-10010  C005      (blank)         -  No due date   640.00  flagged
 12   INV-10011  C006      2026-11-04     -4  Current    18,500.00
 13   INV-10012  C006      2026-10-15     16  1-30        9,800.00
 14   CM-20001   C007      2026-10-10     21  1-30       -1,200.00  flagged (credit)
 15   INV-10014  C007      2026-10-25      6  1-30        3,000.00
 16   INV-10015  C003      2026-10-10     21  1-30            0.00  flagged (zero)

Bucket totals
  Current      1,250.00 + 8,000.00 + 18,500.00                     = 27,750.00
  1-30         2,400.00 + 9,800.00 - 1,200.00 + 3,000.00 + 0.00    = 14,000.00
  31-60        3,150.50 + 4,200.00                                 =  7,350.50
  61-90          975.25 + 5,600.00                                 =  6,575.25
  Over 90      1,875.00 + 2,300.00                                 =  4,175.00
  No due date    640.00                                            =    640.00
  Total                                                            = 60,490.75

Customer totals: C001 3,650.00; C002 11,150.50; C003 5,175.25; C004 7,475.00;
C005 2,940.00; C006 28,300.00 (above the 25,000.00 review threshold);
C007 1,800.00. Sum 60,490.75. 15 lines, 7 customers, 6 exceptions.
"""

from decimal import Decimal as D

from openpyxl import load_workbook

from formula_eval import value_of

from ar_handoff import runner
from ar_handoff.config import sha256_of_file
from ar_handoff.engine import age

from conftest import AS_OF, FIXED_NOW, GOOD

EXPECTED_BUCKETS = {
    "Current": D("27750.00"), "1-30": D("14000.00"), "31-60": D("7350.50"),
    "61-90": D("6575.25"), "Over 90": D("4175.00"), "No due date": D("640.00"),
}
EXPECTED_TOTAL = D("60490.75")
EXPECTED_CUSTOMERS = {
    "C001": D("3650.00"), "C002": D("11150.50"), "C003": D("5175.25"),
    "C004": D("7475.00"), "C005": D("2940.00"), "C006": D("28300.00"),
    "C007": D("1800.00"),
}
EXPECTED_EXCEPTIONS = {
    ("Over 90 days past due", "INV-10008"),
    ("Over 90 days past due", "INV-10009"),
    ("Missing due date", "INV-10010"),
    ("Credit balance", "CM-20001"),
    ("Zero balance line", "INV-10015"),
    ("Customer balance above review threshold", "C006"),
}


def _result(settings):
    report = runner.check(settings, GOOD, AS_OF, EXPECTED_TOTAL)
    assert report.can_run
    return age(report.rows, AS_OF, settings.rules)


def test_bucket_totals(settings):
    assert _result(settings).bucket_totals == EXPECTED_BUCKETS


def test_total_and_counts(settings):
    r = _result(settings)
    assert r.total == EXPECTED_TOTAL
    assert sum(r.bucket_totals.values()) == EXPECTED_TOTAL
    assert r.row_count == 15
    assert r.customer_count == 7


def test_customer_totals(settings):
    assert _result(settings).customer_totals == EXPECTED_CUSTOMERS


def test_exceptions(settings):
    r = _result(settings)
    assert {(e.kind, e.reference) for e in r.exceptions} == EXPECTED_EXCEPTIONS
    flagged = {ln.row.invoice_id for ln in r.lines if ln.flagged}
    assert flagged == {"INV-10008", "INV-10009", "INV-10010", "CM-20001", "INV-10015"}
    assert "INV-10007" not in flagged  # exactly 90 days: the spot-check candidate


def test_validation_warns_but_allows_run(settings):
    report = runner.check(settings, GOOD, AS_OF, EXPECTED_TOTAL)
    assert report.status == "WARN"
    warned = {c.name for c in report.checks if c.status == "WARN"}
    assert warned == {"Due dates present", "Credit balances"}


def test_full_run_reconciles_and_writes_workpaper(settings):
    out = runner.run(settings, GOOD, AS_OF, EXPECTED_TOTAL, "Demo Operator",
                     now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_OK
    assert out.status == runner.STATUS_READY
    assert out.recon.status == "Reconciled"
    assert out.recon.difference == D("0.00")
    assert out.run_id == "2026-10-31-run01"
    assert out.workpaper.is_file()

    wb = load_workbook(out.workpaper)
    assert wb.sheetnames == ["Summary", "Exceptions", "Reconciliation",
                             "Validation", "Detail", "By Customer", "Run Info"]
    summary = {row[0].value: row[1].coordinate for row in wb["Summary"].iter_rows()
               if row[0].value}
    # The Total cell is a live formula; evaluate it the way Excel will.
    assert value_of(wb, "Summary", summary["Total"]) == EXPECTED_TOTAL
    assert value_of(wb, "Summary", summary["Over 90"]) == D("4175.00")
    info = {row[0]: row[1] for row in wb["Run Info"].iter_rows(min_row=4, values_only=True)}
    assert info["Input file SHA-256"] == sha256_of_file(GOOD)
    assert info["Rules version"] == "2026.10-1"
    assert info["Rules file SHA-256"] == settings.rules.sha256
    assert info["Run timestamp (UTC)"] == "2026-11-03T14:30:00Z"
    assert info["As-of date"] == "2026-10-31"
    assert info["Prepared by (operator)"] == "Demo Operator"
    # Six exception rows, each waiting for a disposition.
    ex_rows = [r for r in wb["Exceptions"].iter_rows(min_row=5, values_only=True) if r[0]]
    assert len(ex_rows) == 6
    assert all(r[6] in (None, "") for r in ex_rows)


def test_reconciliation_difference_stops(settings):
    # A GL balance 640.00 higher than the file: difference = 60,490.75 - 61,130.75
    out = runner.run(settings, GOOD, AS_OF, D("61130.75"), "Demo Operator",
                     now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_DIFFERENCE
    assert out.status == runner.STATUS_DIFFERENCE
    assert out.recon.difference == D("-640.00")
    assert out.workpaper.is_file()  # the failed attempt is still evidence


def test_no_control_total_is_flagged(settings):
    out = runner.run(settings, GOOD, AS_OF, None, "Demo Operator", now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_NO_CONTROL
    assert out.status == runner.STATUS_NO_CONTROL
    assert out.recon.status == "Not performed"
