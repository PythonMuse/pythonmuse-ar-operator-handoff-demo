"""The input contract: what blocks a run, and what only warns.

BLOCK = stop. Nothing runs until the file is fixed or replaced.
WARN  = the run may continue; the item is listed for the operator to read.
PASS  = the check found nothing.

A PASS on every line means the configured checks passed. It does not mean the
accounting is correct; that judgment belongs to the reviewer.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import Rules, sha256_of_file

PASS, WARN, BLOCK = "PASS", "WARN", "BLOCK"


@dataclass
class Check:
    name: str
    status: str
    message: str


@dataclass
class Row:
    line: int  # line number in the file (the header is line 1)
    invoice_id: str
    customer_id: str
    customer_name: str
    invoice_date: date
    due_date: date | None
    open_amount: Decimal


@dataclass
class ValidationReport:
    input_path: Path
    as_of: date
    checks: list[Check] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    input_sha256: str | None = None
    repeat_of: str | None = None       # run_id of an identical earlier run
    corrected_reason: str | None = None

    def add(self, name: str, status: str, message: str) -> None:
        self.checks.append(Check(name, status, message))

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        if BLOCK in statuses:
            return BLOCK
        if WARN in statuses:
            return WARN
        return PASS

    @property
    def can_run(self) -> bool:
        return self.status != BLOCK


def _lines(items, limit=5) -> str:
    items = list(items)
    shown = ", ".join(str(i) for i in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def validate_input(input_path, as_of: date, rules: Rules, approved_root: Path,
                   control_total: Decimal | None, prior_runs: list[dict] | None = None,
                   corrected_reason: str | None = None) -> ValidationReport:
    path = Path(input_path)
    report = ValidationReport(input_path=path, as_of=as_of)
    as_of_iso = as_of.isoformat()

    # 1. Approved location. Resolve first so "..\" tricks don't get through.
    try:
        inside = path.resolve().is_relative_to(Path(approved_root).resolve())
    except OSError:
        inside = False
    if not inside:
        report.add("Approved location", BLOCK,
                   f"The file must be saved in the approved input folder "
                   f"({approved_root}). Move it there and try again.")
        return report
    report.add("Approved location", PASS, "File is in the approved input folder.")

    # 2. File exists.
    if not path.is_file():
        report.add("File found", BLOCK, f"No file at {path}.")
        return report
    report.add("File found", PASS, path.name)
    report.input_sha256 = sha256_of_file(path)

    # 3. File name follows the convention for this as-of date.
    expected = rules.expected_file_name(as_of_iso)
    if path.name != expected:
        report.add("File name matches as-of date", BLOCK,
                   f"Expected '{expected}' for as-of date {as_of_iso}, "
                   f"got '{path.name}'. Check that you picked this period's export.")
    else:
        report.add("File name matches as-of date", PASS, expected)

    # 4. Columns.
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            raw_rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        report.add("File readable", BLOCK, f"Could not read the file as CSV: {exc}")
        return report

    missing = [c for c in rules.required_columns if c not in header]
    if missing:
        extra = [c for c in header if c not in rules.required_columns]
        hint = f" Unexpected columns: {', '.join(extra)}." if extra else ""
        report.add("Required columns present", BLOCK,
                   f"Missing: {', '.join(missing)}.{hint} The export format may "
                   f"have changed. Stop and escalate to the maintainer.")
        return report
    report.add("Required columns present", PASS, ", ".join(rules.required_columns))

    # 5. Data rows.
    if not raw_rows:
        report.add("File has data", BLOCK, "The file has a header but no data rows.")
        return report
    report.add("File has data", PASS, f"{len(raw_rows)} rows.")

    # 6-9. Row-level checks: collect every problem before reporting.
    blank_ids, bad_amounts, bad_dates, future, no_due, credits = [], [], [], [], [], []
    ids = Counter()
    parsed: list[Row] = []
    for i, r in enumerate(raw_rows, start=2):
        inv = (r.get("invoice_id") or "").strip()
        if not inv:
            blank_ids.append(i)
        ids[inv] += 1
        amount_text = (r.get("open_amount") or "").strip()
        try:
            amount = Decimal(amount_text)
            if not amount.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            bad_amounts.append(f"line {i} ('{amount_text}')")
            amount = None
        inv_date = _parse_date((r.get("invoice_date") or "").strip())
        if inv_date is None:
            bad_dates.append(f"line {i} invoice_date '{r.get('invoice_date')}'")
        due_text = (r.get("due_date") or "").strip()
        due = None
        if due_text:
            due = _parse_date(due_text)
            if due is None:
                bad_dates.append(f"line {i} due_date '{due_text}'")
        else:
            no_due.append(inv or f"line {i}")
        if inv_date and inv_date > as_of:
            future.append(inv or f"line {i}")
        if amount is not None and amount < 0:
            credits.append(inv or f"line {i}")
        if amount is not None and inv_date is not None and (due or not due_text):
            parsed.append(Row(i, inv, (r.get("customer_id") or "").strip(),
                              (r.get("customer_name") or "").strip(),
                              inv_date, due, amount))

    dupes = sorted(k for k, n in ids.items() if n > 1 and k)
    if blank_ids or dupes:
        parts = []
        if blank_ids:
            parts.append(f"blank invoice_id on {_lines(f'line {n}' for n in blank_ids)}")
        if dupes:
            parts.append(f"duplicated: {_lines(dupes)}")
        text = "; ".join(parts)
        report.add("Invoice IDs present and unique", BLOCK,
                   text[0].upper() + text[1:] + ". Totals can't be trusted "
                   "until each invoice appears exactly once.")
    else:
        report.add("Invoice IDs present and unique", PASS, f"{len(ids)} unique IDs.")

    if bad_amounts:
        report.add("Amounts are numbers", BLOCK,
                   f"Not a plain number: {_lines(bad_amounts)}. Use digits and a "
                   f"decimal point only (no commas or currency symbols).")
    else:
        report.add("Amounts are numbers", PASS, "All open_amount values are numbers.")

    if bad_dates:
        report.add("Dates are valid", BLOCK,
                   f"Not a YYYY-MM-DD date: {_lines(bad_dates)}.")
    else:
        report.add("Dates are valid", PASS, "All dates are YYYY-MM-DD.")

    if future:
        report.add("Invoices dated on or before as-of date", BLOCK,
                   f"Dated after {as_of_iso}: {_lines(future)}. This may be the "
                   f"wrong period's export.")
    else:
        report.add("Invoices dated on or before as-of date", PASS,
                   f"No invoice is dated after {as_of_iso}.")

    if no_due:
        report.add("Due dates present", WARN,
                   f"No due date: {_lines(no_due)}. These can't be aged and will "
                   f"be listed as exceptions.")
    else:
        report.add("Due dates present", PASS, "Every line has a due date.")

    if credits:
        report.add("Credit balances", WARN,
                   f"Credit balance: {_lines(credits)}. Listed as exceptions; "
                   f"confirm each one is real (unapplied cash, credit memo).")
    else:
        report.add("Credit balances", PASS, "No credit balances.")

    # 10. Same as-of date, different file? Never silently replace evidence.
    earlier = [r for r in (prior_runs or []) if r.get("as_of") == as_of_iso]
    if earlier:
        same = [r for r in earlier if r.get("input_sha256") == report.input_sha256]
        if same:
            report.repeat_of = same[0]["run_id"]
            report.add("Input unchanged since earlier run", PASS,
                       f"Identical to the file used in {same[0]['run_id']} "
                       f"(repeat run).")
        elif corrected_reason:
            report.corrected_reason = corrected_reason
            report.add("Input unchanged since earlier run", WARN,
                       f"Differs from the file used in {earlier[-1]['run_id']}. "
                       f"Running as a corrected export: {corrected_reason}")
        else:
            report.add("Input unchanged since earlier run", BLOCK,
                       f"This file differs from the one used in "
                       f"{earlier[-1]['run_id']} for {as_of_iso}. It may have been "
                       f"edited or re-exported. Stop and escalate; only an approved "
                       f"corrected export may be run.")
    else:
        report.add("Input unchanged since earlier run", PASS,
                   f"First run for {as_of_iso}.")

    # 11. Control total.
    if control_total is None:
        report.add("Control total entered", WARN,
                   "No AR control balance entered, so the run can't reconcile. "
                   "Enter the general ledger AR balance if you have it.")
    else:
        report.add("Control total entered", PASS, f"{control_total:,.2f}")

    report.rows = parsed if report.can_run else []
    return report
