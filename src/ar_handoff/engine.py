"""The aging calculation and the reconciliation. No interface code here.

Given validated rows, an as-of date, and the approved rules, this module:
- ages each line by days past due on the as-of date,
- totals each aging bucket, each customer, and the whole file,
- lists exceptions using the thresholds in the rules file,
- reconciles the aging total to the AR control balance.

It does not decide anything about collection, reserves, or write-offs. It
lists items for a person to look at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .config import Bucket, Rules
from .validate import Row

NO_DUE_DATE = "No due date"
ZERO = Decimal("0.00")

# Professional labels: these end up in a workpaper.
EX_CREDIT = "Credit balance"
EX_MISSING_DUE = "Missing due date"
EX_ZERO = "Zero balance line"
EX_CUSTOMER = "Customer balance above review threshold"


def ex_past_due_label(days: int) -> str:
    return f"Over {days} days past due"


@dataclass
class AgedLine:
    row: Row
    days_past_due: int | None
    bucket: str
    flagged: bool = False


@dataclass
class ExceptionItem:
    kind: str
    reference: str       # invoice ID, or customer ID for customer-level items
    customer: str
    amount: Decimal
    detail: str


@dataclass
class AgingResult:
    as_of: date
    bucket_labels: list[str]
    lines: list[AgedLine]
    bucket_totals: dict[str, Decimal]
    total: Decimal
    row_count: int
    customer_count: int
    customer_totals: dict[str, Decimal]           # customer_id -> total
    customer_names: dict[str, str]
    customer_buckets: dict[str, dict[str, Decimal]]
    exceptions: list[ExceptionItem] = field(default_factory=list)


@dataclass
class Reconciliation:
    status: str                 # "Reconciled" | "Difference" | "Not performed"
    aging_total: Decimal
    control_total: Decimal | None
    difference: Decimal | None  # aging total minus control total
    tolerance: Decimal


def bucket_for(days_past_due: int, buckets: tuple[Bucket, ...]) -> str:
    for b in buckets:
        if b.max_days is None or days_past_due <= b.max_days:
            return b.label
    raise AssertionError("unreachable: the last bucket has no upper limit")


def age(rows: list[Row], as_of: date, rules: Rules) -> AgingResult:
    labels = [b.label for b in rules.buckets] + [NO_DUE_DATE]
    bucket_totals = {label: ZERO for label in labels}
    customer_totals: dict[str, Decimal] = {}
    customer_names: dict[str, str] = {}
    customer_buckets: dict[str, dict[str, Decimal]] = {}
    lines: list[AgedLine] = []
    exceptions: list[ExceptionItem] = []
    threshold = rules.days_past_due_threshold

    for row in rows:
        if row.due_date is None:
            days, label = None, NO_DUE_DATE
        else:
            days = (as_of - row.due_date).days
            label = bucket_for(days, rules.buckets)
        line = AgedLine(row, days, label)
        lines.append(line)

        bucket_totals[label] += row.open_amount
        cid = row.customer_id
        customer_names.setdefault(cid, row.customer_name)
        customer_totals[cid] = customer_totals.get(cid, ZERO) + row.open_amount
        cb = customer_buckets.setdefault(cid, {lb: ZERO for lb in labels})
        cb[label] += row.open_amount

        def flag(kind, detail):
            line.flagged = True
            exceptions.append(ExceptionItem(kind, row.invoice_id, row.customer_name,
                                            row.open_amount, detail))

        if days is not None and days > threshold:
            flag(ex_past_due_label(threshold), f"{days} days past due")
        if row.due_date is None:
            flag(EX_MISSING_DUE, "No due date in the export; not aged")
        if row.open_amount < 0:
            flag(EX_CREDIT, "Negative open amount")
        if row.open_amount == 0:
            flag(EX_ZERO, "Zero open amount on an open-items report")

    for cid, total in customer_totals.items():
        if total > rules.customer_balance_threshold:
            exceptions.append(ExceptionItem(
                EX_CUSTOMER, cid, customer_names[cid], total,
                f"Customer total {total:,.2f} is above the review threshold of "
                f"{rules.customer_balance_threshold:,.2f}"))

    total = sum((r.open_amount for r in rows), ZERO)
    return AgingResult(
        as_of=as_of, bucket_labels=labels, lines=lines,
        bucket_totals=bucket_totals, total=total, row_count=len(rows),
        customer_count=len(customer_totals), customer_totals=customer_totals,
        customer_names=customer_names, customer_buckets=customer_buckets,
        exceptions=exceptions)


def reconcile(aging_total: Decimal, control_total: Decimal | None,
              tolerance: Decimal) -> Reconciliation:
    if control_total is None:
        return Reconciliation("Not performed", aging_total, None, None, tolerance)
    difference = aging_total - control_total
    status = "Reconciled" if abs(difference) <= tolerance else "Difference"
    return Reconciliation(status, aging_total, control_total, difference, tolerance)
