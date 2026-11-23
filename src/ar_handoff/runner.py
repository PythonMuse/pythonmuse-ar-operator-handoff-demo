"""Check, then run. The only module the operator interfaces call.

Both the terminal launcher and the desktop app go through these two functions,
so they cannot drift apart: same validation, same engine, same workpaper.
run() validates again before calculating, because the file may have changed
between the operator's "Check" and "Run".

If the output can't be written (the run log is open in Excel, say), run()
raises RunError with a message an operator can act on, and leaves nothing
half-done: a workpaper is only kept if its run-log line was written too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import __version__
from .config import Rules, load_rules, sha256_of_file
from .engine import AgingResult, Reconciliation, age, reconcile
from .runlog import append_run, log_path, read_runs, runs_for
from .validate import ValidationReport, validate_input
from .workpaper import GREEN_CHECK_NOTE, RunInfo, write_workpaper

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = PROJECT_ROOT / "config" / "rules.example.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "output"

STATUS_READY = "CHECKS PASSED - READY FOR REVIEW"
STATUS_DIFFERENCE = "RECONCILIATION DIFFERENCE - STOP AND ESCALATE"
STATUS_NO_CONTROL = "NO CONTROL TOTAL - RECONCILE BEFORE REVIEW"
STATUS_BLOCKED = "BLOCKED - NOTHING WAS RUN"

EXIT_OK, EXIT_ERROR, EXIT_BLOCKED, EXIT_DIFFERENCE, EXIT_NO_CONTROL, EXIT_CANCELLED = (
    0, 1, 2, 3, 4, 5)

__all__ = ["GREEN_CHECK_NOTE", "Settings", "RunOutcome", "RunError", "check", "run",
           "parse_as_of", "parse_amount", "load_settings"]


class RunError(OSError):
    """The output could not be read or written. The message says what to do."""


def _why(exc: OSError) -> str:
    return exc.strerror or str(exc)


def _log_unavailable(settings: Settings, exc: OSError) -> RunError:
    return RunError(
        f"Could not use the run log ({log_path(settings.output_dir)}): {_why(exc)}. "
        f"If it is open in Excel or another program, close it and try again. "
        f"Nothing was written.")


@dataclass
class Settings:
    rules: Rules
    approved_root: Path
    output_dir: Path


@dataclass
class RunOutcome:
    report: ValidationReport
    status: str
    exit_code: int
    result: AgingResult | None = None
    recon: Reconciliation | None = None
    run_id: str | None = None
    workpaper: Path | None = None


def load_settings(rules_path=DEFAULT_RULES, output_dir=DEFAULT_OUTPUT,
                  approved_root=None) -> Settings:
    rules = load_rules(rules_path)
    root = Path(approved_root) if approved_root else PROJECT_ROOT / rules.approved_input_folder
    return Settings(rules, root, Path(output_dir))


def parse_as_of(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a date in YYYY-MM-DD form.") from exc


def parse_amount(text: str | None) -> Decimal | None:
    """Blank means 'not entered'. Commas are allowed here (a person typed it)."""
    if text is None or not str(text).strip():
        return None
    try:
        value = Decimal(str(text).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"'{text}' is not an amount.") from exc
    if not value.is_finite():
        raise ValueError(f"'{text}' is not an amount.")
    return value


def check(settings: Settings, input_path, as_of: date, control_total: Decimal | None,
          corrected_reason: str | None = None) -> ValidationReport:
    try:
        prior_runs = read_runs(settings.output_dir)
    except OSError as exc:
        raise _log_unavailable(settings, exc) from exc
    return validate_input(input_path, as_of, settings.rules, settings.approved_root,
                          control_total, prior_runs, corrected_reason)


def run(settings: Settings, input_path, as_of: date, control_total: Decimal | None,
        prepared_by: str, corrected_reason: str | None = None,
        now: datetime | None = None) -> RunOutcome:
    report = check(settings, input_path, as_of, control_total, corrected_reason)
    if not report.can_run:
        return RunOutcome(report, STATUS_BLOCKED, EXIT_BLOCKED)

    rules = settings.rules
    result = age(report.rows, as_of, rules)
    recon = reconcile(result.total, control_total, rules.reconciliation_tolerance)
    if recon.status == "Reconciled":
        status, code = STATUS_READY, EXIT_OK
    elif recon.status == "Difference":
        status, code = STATUS_DIFFERENCE, EXIT_DIFFERENCE
    else:
        status, code = STATUS_NO_CONTROL, EXIT_NO_CONTROL

    as_of_iso = as_of.isoformat()
    try:
        n = len(runs_for(settings.output_dir, as_of_iso)) + 1
    except OSError as exc:
        raise _log_unavailable(settings, exc) from exc
    run_id = f"{as_of_iso}-run{n:02d}"
    target = settings.output_dir / as_of_iso / f"AR_Aging_Workpaper_{run_id}.xlsx"
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    notes = []
    if report.repeat_of:
        notes.append(f"Repeat of {report.repeat_of} (identical input file)")
    if report.corrected_reason:
        notes.append(f"Corrected export: {report.corrected_reason}")
    note = "; ".join(notes)

    info = RunInfo(run_id=run_id, run_timestamp_utc=stamp,
                   prepared_by=prepared_by.strip() or "(not entered)",
                   status=status, rules_version=rules.version,
                   rules_approved_by=rules.approved_by, rules_sha256=rules.sha256,
                   code_version=__version__, note=note)

    # Before writing any evidence, make sure the run log can take a new line.
    # (On Windows, a log that is open in Excel can't be written to.)
    log = log_path(settings.output_dir)
    if log.is_file():
        try:
            with open(log, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise _log_unavailable(settings, exc) from exc

    try:
        write_workpaper(target, result, recon, report, info)
    except FileExistsError as exc:
        # The run log doesn't list this run, but its workpaper exists: the log
        # was edited, replaced, or deleted. Never overwrite evidence.
        raise RunError(
            f"A workpaper for {run_id} already exists ({target}), but the run log "
            f"doesn't list it. Nothing was written. Escalate to the maintainer: "
            f"the run log may have been edited or deleted.") from exc
    except OSError as exc:
        target.unlink(missing_ok=True)  # it didn't exist before; drop any partial file
        raise RunError(
            f"Could not save the workpaper ({target}): {_why(exc)}. "
            f"Nothing was written.") from exc

    try:
        append_run(settings.output_dir, {
            "run_id": run_id, "run_timestamp_utc": stamp, "as_of": as_of_iso,
            "prepared_by": info.prepared_by, "input_file": report.input_path.name,
            "input_sha256": report.input_sha256, "rows": result.row_count,
            "aging_total": f"{result.total:.2f}",
            "control_total": "" if control_total is None else f"{control_total:.2f}",
            "difference": "" if recon.difference is None else f"{recon.difference:.2f}",
            "status": status, "rules_version": rules.version,
            "rules_sha256": rules.sha256, "code_version": __version__,
            "workpaper_file": target.relative_to(settings.output_dir).as_posix(),
            "workpaper_sha256": sha256_of_file(target), "note": note,
        })
    except OSError as exc:
        # A workpaper the log doesn't list would block every later run for this
        # period, so take it back out.
        target.unlink(missing_ok=True)
        raise _log_unavailable(settings, exc) from exc
    return RunOutcome(report, status, code, result, recon, run_id, target)
