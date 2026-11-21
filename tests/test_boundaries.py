"""Boundary cases: the days and amounts where a rule switches on or off.
Expected answers come from the rules file: buckets top out at 0/30/60/90
days, an exception needs MORE than 90 days, and a customer review needs a
total MORE than 25,000.00."""

from datetime import date
from decimal import Decimal as D

import pytest

from ar_handoff import runner
from ar_handoff.engine import EX_CUSTOMER, age, bucket_for, reconcile
from ar_handoff.validate import Row

AS_OF = date(2026, 10, 31)


def row(inv, due, amount, cid="C1", line=2):
    return Row(line, inv, cid, f"Customer {cid}", date(2026, 6, 1), due, D(amount))


@pytest.mark.parametrize("days,label", [
    (-15, "Current"), (0, "Current"), (1, "1-30"), (30, "1-30"), (31, "31-60"),
    (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "Over 90"), (400, "Over 90"),
])
def test_bucket_edges(settings, days, label):
    assert bucket_for(days, settings.rules.buckets) == label


def test_ninety_versus_ninety_one(settings):
    rows = [row("A", date(2026, 8, 2), "10.00"),   # 90 days
            row("B", date(2026, 8, 1), "10.00")]   # 91 days
    r = age(rows, AS_OF, settings.rules)
    assert [ln.days_past_due for ln in r.lines] == [90, 91]
    assert [ln.flagged for ln in r.lines] == [False, True]


def test_customer_threshold_is_strictly_above(settings):
    at = age([row("A", AS_OF, "25000.00", cid="C1")], AS_OF, settings.rules)
    above = age([row("A", AS_OF, "25000.01", cid="C1")], AS_OF, settings.rules)
    assert not [e for e in at.exceptions if e.kind == EX_CUSTOMER]
    assert [e.reference for e in above.exceptions if e.kind == EX_CUSTOMER] == ["C1"]


def test_credit_reduces_its_bucket(settings):
    r = age([row("A", date(2026, 10, 10), "500.00"),
             row("B", date(2026, 10, 10), "-200.00")], AS_OF, settings.rules)
    assert r.bucket_totals["1-30"] == D("300.00")
    assert r.total == D("300.00")


def test_zero_balance_is_flagged_and_changes_nothing(settings):
    r = age([row("A", AS_OF, "100.00"), row("B", AS_OF, "0.00")], AS_OF, settings.rules)
    assert r.total == D("100.00")
    assert [ln.flagged for ln in r.lines] == [False, True]


def test_month_end_leap_year(settings):
    # 2028 is a leap year: 2028-02-29 to 2028-03-31 is 31 days.
    r = age([row("A", date(2028, 2, 29), "1.00")], date(2028, 3, 31), settings.rules)
    assert r.lines[0].days_past_due == 31
    assert r.lines[0].bucket == "31-60"


def test_tolerance_is_exact(settings):
    assert reconcile(D("100.00"), D("100.00"), D("0.00")).status == "Reconciled"
    assert reconcile(D("100.00"), D("99.99"), D("0.00")).status == "Difference"
    assert reconcile(D("100.00"), D("99.99"), D("0.01")).status == "Reconciled"


def test_control_total_with_commas_from_a_person():
    assert runner.parse_amount("60,490.75") == D("60490.75")
