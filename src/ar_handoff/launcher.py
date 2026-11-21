"""Guided terminal launcher for the AR aging review. Deliberately thin.

It asks for the as-of date, the input file, the AR control balance, and the
operator's name; shows the validation results; asks for confirmation; and
calls runner.run(). No accounting logic lives here.

Every prompt can also be given as an option, so the same launcher works in a
scheduled or scripted setting. --corrected-export is for the maintainer, after
a reviewer approves re-running a period with a corrected file.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from . import __version__
from . import runner

TAG = {"PASS": "[ OK ]", "WARN": "[WARN]", "BLOCK": "[STOP]"}


def last_month_end(today: date | None = None) -> date:
    today = today or date.today()
    return today.replace(day=1) - timedelta(days=1)


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or (default or "")


def print_checks(report) -> None:
    print()
    print("Validation")
    print("-" * 70)
    for c in report.checks:
        print(f"{TAG[c.status]} {c.name}")
        print(f"       {c.message}")
    print("-" * 70)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="AR aging review (guided launcher)")
    p.add_argument("--as-of", help="as-of date, YYYY-MM-DD")
    p.add_argument("--input", help="path to the AR open-items CSV")
    p.add_argument("--control-total", help="AR control balance from the general ledger")
    p.add_argument("--prepared-by", help="operator name for the workpaper")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p.add_argument("--rules", default=str(runner.DEFAULT_RULES))
    p.add_argument("--output", default=str(runner.DEFAULT_OUTPUT))
    p.add_argument("--approved-root", help=argparse.SUPPRESS)
    p.add_argument("--corrected-export", metavar="REASON",
                   help="maintainer only: run a corrected export for a period "
                        "that already has a run, recording the reason")
    args = p.parse_args(argv)

    try:
        settings = runner.load_settings(args.rules, args.output, args.approved_root)
    except Exception as exc:  # a broken rules file is a maintainer problem
        print(f"Cannot start: {exc}\nEscalate to the maintainer.")
        return runner.EXIT_ERROR

    print(f"AR Aging Review  |  workflow v{__version__}  |  rules {settings.rules.version}")
    print(f"Approved input folder: {settings.approved_root}")
    print()

    try:
        as_of = runner.parse_as_of(
            args.as_of or ask("As-of date (YYYY-MM-DD)", last_month_end().isoformat()))
        expected = settings.rules.expected_file_name(as_of.isoformat())
        input_path = Path(args.input or ask(
            "Input file", str(settings.approved_root / expected)))
        control_total = runner.parse_amount(
            args.control_total if args.control_total is not None
            else ask("AR control balance from the general ledger (blank if none)"))
        prepared_by = args.prepared_by or ask("Your name (for the workpaper)")
    except ValueError as exc:
        print(f"\n{exc}\nNothing was run.")
        return runner.EXIT_BLOCKED

    report = runner.check(settings, input_path, as_of, control_total,
                          args.corrected_export)
    print_checks(report)
    if not report.can_run:
        print("STOP: fix the items marked [STOP], or escalate. Nothing was run.")
        return runner.EXIT_BLOCKED
    if report.status == "WARN":
        print("Read the [WARN] items. They will appear on the Exceptions sheet.")

    if not args.yes:
        if ask("Run the analysis now? (y/n)", "n").lower() not in ("y", "yes"):
            print("Cancelled. Nothing was run.")
            return runner.EXIT_CANCELLED

    outcome = runner.run(settings, input_path, as_of, control_total, prepared_by,
                         args.corrected_export)
    if outcome.workpaper is None:  # the file changed between check and run
        print_checks(outcome.report)
        print("STOP: the file changed after it was checked. Nothing was run.")
        return outcome.exit_code

    r, rec = outcome.result, outcome.recon
    print()
    print(f"Run {outcome.run_id}: {outcome.status}")
    print(f"  Aging total      {r.total:>14,.2f}")
    if rec.control_total is not None:
        print(f"  Control balance  {rec.control_total:>14,.2f}")
        print(f"  Difference       {rec.difference:>14,.2f}")
    print(f"  Lines {r.row_count}, customers {r.customer_count}, "
          f"exceptions to review {len(r.exceptions)}")
    print(f"  Workpaper: {outcome.workpaper}")
    print()
    print(runner.GREEN_CHECK_NOTE)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
