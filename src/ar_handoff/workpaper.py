"""Write the Excel workpaper: results, evidence, and run metadata.

Sheets: Summary, Exceptions, Reconciliation, Validation, Detail, By Customer,
Run Info. The Run Info sheet records the as-of date, the input file's SHA-256
fingerprint, the rules version and fingerprint, and the code version, so a
reviewer can tell exactly what produced the numbers.

Totals and the reconciliation difference are written as live Excel formulas
(for example =SUM(B8:B13)), not pasted values, so a reviewer can click a total
and see how it was built. Excel calculates them when the file is opened.

A workpaper is never overwritten. If the target file already exists, writing
stops with an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .engine import AgingResult, Reconciliation
from .validate import ValidationReport

DEEP_NAVY = "002639"
MIDNIGHT_TEAL = "003144"
BRIGHT_TEAL = "3ABFB9"
GOLDEN_YELLOW = "FFD75E"
OCEAN_TEAL = "005F6F"
SOFT_SAGE = "91BE8E"
SEA_GREEN = "2BA19A"
ALERT_RED = "E05252"
ROW_TINT = "EDF5F5"
WARN_FILL = "FFF8E1"

MONEY = '#,##0.00_);(#,##0.00)'
GREEN_CHECK_NOTE = ("A green check means the configured checks passed. It does not "
                    "mean the accounting is correct. That judgment is the reviewer's.")


@dataclass
class RunInfo:
    run_id: str
    run_timestamp_utc: str
    prepared_by: str
    status: str
    rules_version: str
    rules_approved_by: str
    rules_sha256: str
    code_version: str
    note: str = ""


def _fill(hex_color):
    return PatternFill("solid", start_color=hex_color, end_color=hex_color)


def _header(ws, row, values):
    for c, v in enumerate(values, start=1):
        cell = ws.cell(row=row, column=c, value=v)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _fill(DEEP_NAVY)
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def _title(ws, text, subtitle=None):
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14, color=DEEP_NAVY)
    if subtitle:
        ws["A2"] = subtitle
        ws["A2"].font = Font(italic=True, color=OCEAN_TEAL)


def _widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _band(ws, first_row, last_row, ncols):
    for r in range(first_row, last_row + 1):
        if (r - first_row) % 2 == 1:
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).fill = _fill(ROW_TINT)


def _total_row(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = _fill(MIDNIGHT_TEAL)
        cell.font = Font(bold=True, color=GOLDEN_YELLOW)


def write_workpaper(path: Path, result: AgingResult, recon: Reconciliation,
                    report: ValidationReport, info: RunInfo) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Workpaper already exists, not overwriting: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    as_of = result.as_of.isoformat()

    # --- Summary -----------------------------------------------------------
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_properties.tabColor = BRIGHT_TEAL
    _title(ws, f"AR Aging Review as of {as_of}", f"Run {info.run_id}")
    ws["A4"] = "Run status"
    ws["B4"] = info.status
    ws["A4"].font = Font(bold=True, color=DEEP_NAVY)
    ok = info.status.startswith("CHECKS PASSED")
    ws["B4"].font = Font(bold=True, color="FFFFFF")
    ws["B4"].fill = _fill(SEA_GREEN if ok else ALERT_RED)
    ws["A5"] = GREEN_CHECK_NOTE
    ws["A5"].font = Font(italic=True, color=OCEAN_TEAL)
    _header(ws, 7, ["Aging bucket", "Open amount", "Lines"])
    r = 8
    for label in result.bucket_labels:
        n = sum(1 for ln in result.lines if ln.bucket == label)
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=result.bucket_totals[label]).number_format = MONEY
        ws.cell(row=r, column=3, value=n)
        r += 1
    _band(ws, 8, r - 1, 3)
    # Totals are live Excel formulas, not pasted values, so a reviewer can click
    # a total and see exactly which cells it adds up.
    ws.cell(row=r, column=1, value="Total")
    ws.cell(row=r, column=2, value=f"=SUM(B8:B{r - 1})").number_format = MONEY
    ws.cell(row=r, column=3, value=f"=SUM(C8:C{r - 1})")
    _total_row(ws, r, 3)
    summary_total_row = r
    r += 2
    for label, value in [("Customers", result.customer_count),
                         ("Exceptions to review", len(result.exceptions)),
                         ("Reconciliation", recon.status)]:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True, color=DEEP_NAVY)
        ws.cell(row=r, column=2, value=value)
        r += 1
    _widths(ws, [26, 52, 10])

    # --- Exceptions ----------------------------------------------------------
    ws = wb.create_sheet("Exceptions")
    ws.sheet_properties.tabColor = GOLDEN_YELLOW
    _title(ws, "Exceptions to review",
           "Each item needs a disposition from the operator and a reviewer note.")
    cols = ["#", "Exception", "Reference", "Customer", "Amount", "Detail",
            "Disposition (operator)", "Reviewer notes"]
    _header(ws, 4, cols)
    for i, ex in enumerate(result.exceptions, start=1):
        row = 4 + i
        values = [i, ex.kind, ex.reference, ex.customer, ex.amount, ex.detail, "", ""]
        for c, v in enumerate(values, start=1):
            ws.cell(row=row, column=c, value=v)
        ws.cell(row=row, column=5).number_format = MONEY
    _band(ws, 5, 4 + len(result.exceptions), len(cols))
    _widths(ws, [5, 36, 12, 26, 14, 48, 26, 26])

    # --- Reconciliation ------------------------------------------------------
    ws = wb.create_sheet("Reconciliation")
    ws.sheet_properties.tabColor = OCEAN_TEAL
    _title(ws, "Reconciliation to the AR control balance")
    _header(ws, 3, ["Item", "Value"])
    # The aging total points at the Summary total, and the difference is a
    # formula, so the reviewer can follow both. The control balance is typed
    # in by the operator from the general ledger: it comes from outside.
    rows = [
        ("AR aging total (this workpaper)", f"=Summary!B{summary_total_row}"),
        ("AR control balance (general ledger, entered by operator)",
         recon.control_total if recon.control_total is not None else "Not entered"),
        ("Difference (aging total minus control balance)",
         "=B4-B5" if recon.control_total is not None else "n/a"),
        ("Tolerance (from the rules file)", recon.tolerance),
        ("Result", recon.status),
        ("Lines in input file", result.row_count),
        ("Customers", result.customer_count),
    ]
    for i, (k, v) in enumerate(rows, start=4):
        ws.cell(row=i, column=1, value=k)
        cell = ws.cell(row=i, column=2, value=v)
        if i in (4, 5, 6, 7) and v not in ("Not entered", "n/a"):
            cell.number_format = MONEY
    _band(ws, 4, 3 + len(rows), 2)
    _widths(ws, [58, 22])

    # --- Validation ----------------------------------------------------------
    ws = wb.create_sheet("Validation")
    ws.sheet_properties.tabColor = SOFT_SAGE
    _title(ws, "Input validation results", GREEN_CHECK_NOTE)
    _header(ws, 4, ["Check", "Result", "Message"])
    for i, chk in enumerate(report.checks, start=5):
        ws.cell(row=i, column=1, value=chk.name)
        cell = ws.cell(row=i, column=2, value=chk.status)
        ws.cell(row=i, column=3, value=chk.message)
        if chk.status == "WARN":
            cell.fill = _fill(WARN_FILL)
            cell.font = Font(bold=True, color=DEEP_NAVY)
        elif chk.status == "PASS":
            cell.font = Font(bold=True, color=SEA_GREEN)
        else:
            cell.font = Font(bold=True, color=ALERT_RED)
    _widths(ws, [38, 10, 100])

    # --- Detail --------------------------------------------------------------
    ws = wb.create_sheet("Detail")
    ws.sheet_properties.tabColor = BRIGHT_TEAL
    _title(ws, "Every line, aged",
           "Use this sheet to spot-check unflagged items, not just the exceptions.")
    cols = ["File line", "Invoice", "Customer ID", "Customer", "Invoice date",
            "Due date", "Days past due", "Bucket", "Open amount", "Flagged"]
    _header(ws, 4, cols)
    for i, ln in enumerate(result.lines, start=5):
        row = ln.row
        values = [row.line, row.invoice_id, row.customer_id, row.customer_name,
                  row.invoice_date.isoformat(),
                  row.due_date.isoformat() if row.due_date else "",
                  ln.days_past_due if ln.days_past_due is not None else "",
                  ln.bucket, row.open_amount, "Yes" if ln.flagged else ""]
        for c, v in enumerate(values, start=1):
            ws.cell(row=i, column=c, value=v)
        ws.cell(row=i, column=9).number_format = MONEY
    _band(ws, 5, 4 + len(result.lines), len(cols))
    _widths(ws, [9, 12, 12, 26, 13, 13, 13, 12, 14, 9])

    # --- By Customer -----------------------------------------------------------
    ws = wb.create_sheet("By Customer")
    ws.sheet_properties.tabColor = GOLDEN_YELLOW
    _title(ws, "Aging by customer")
    cols = ["Customer ID", "Customer"] + result.bucket_labels + ["Total"]
    _header(ws, 3, cols)
    r = 4
    n_buckets = len(result.bucket_labels)
    first_bucket_col = get_column_letter(3)
    last_bucket_col = get_column_letter(2 + n_buckets)
    for cid in sorted(result.customer_totals):
        # Customer total = a formula across that customer's bucket amounts.
        values = ([cid, result.customer_names[cid]]
                  + [result.customer_buckets[cid][lb] for lb in result.bucket_labels]
                  + [f"=SUM({first_bucket_col}{r}:{last_bucket_col}{r})"])
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            if c > 2:
                cell.number_format = MONEY
        r += 1
    _band(ws, 4, r - 1, len(cols))
    # Bottom row = a formula down each column.
    totals = ["Total", ""] + [
        f"=SUM({get_column_letter(c)}4:{get_column_letter(c)}{r - 1})"
        for c in range(3, len(cols) + 1)]
    for c, v in enumerate(totals, start=1):
        cell = ws.cell(row=r, column=c, value=v)
        if c > 2:
            cell.number_format = MONEY
    _total_row(ws, r, len(cols))
    _widths(ws, [12, 26] + [13] * (len(cols) - 2))

    # --- Run Info --------------------------------------------------------------
    ws = wb.create_sheet("Run Info")
    ws.sheet_properties.tabColor = OCEAN_TEAL
    _title(ws, "Run information and sign-off")
    _header(ws, 3, ["Field", "Value"])
    rows = [
        ("Run ID", info.run_id),
        ("Run timestamp (UTC)", info.run_timestamp_utc),
        ("As-of date", as_of),
        ("Prepared by (operator)", info.prepared_by),
        ("Input file", report.input_path.name),
        ("Input file SHA-256", report.input_sha256),
        ("Input lines", result.row_count),
        ("Rules version", info.rules_version),
        ("Rules approved by", info.rules_approved_by),
        ("Rules file SHA-256", info.rules_sha256),
        ("Code version", info.code_version),
        ("Run status", info.status),
        ("Note", info.note),
        ("Reviewed by", ""),
        ("Review date", ""),
        ("Reviewer conclusion", ""),
    ]
    for i, (k, v) in enumerate(rows, start=4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True, color=DEEP_NAVY)
        ws.cell(row=i, column=2, value=v)
    _band(ws, 4, 3 + len(rows), 2)
    _widths(ws, [26, 70])

    wb.save(path)
