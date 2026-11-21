"""Repeat runs: same input, same answer; nothing is overwritten; an edited or
re-exported file for a period that already has a run is caught."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from ar_handoff import runner
from ar_handoff.config import sha256_of_file
from ar_handoff.runlog import read_runs
from ar_handoff.workpaper import RunInfo, write_workpaper

from conftest import AS_OF, FIXED_NOW, GOOD, SAMPLE

TAMPERED = SAMPLE / "tampered" / "AR_Open_Items_2026-10-31.csv"
CONTROL = D("60490.75")


def sheet_values(path, name):
    return [r for r in load_workbook(path)[name].iter_rows(values_only=True)]


def test_same_input_same_figures_no_overwrite(settings):
    first = runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    first_hash = sha256_of_file(first.workpaper)
    second = runner.run(settings, GOOD, AS_OF, CONTROL, "Op",
                        now=FIXED_NOW + timedelta(hours=1))

    assert first.workpaper != second.workpaper
    assert second.run_id == "2026-10-31-run02"
    assert sha256_of_file(first.workpaper) == first_hash  # untouched
    for sheet in ("Exceptions", "Reconciliation", "Detail", "By Customer"):
        assert sheet_values(first.workpaper, sheet) == sheet_values(second.workpaper, sheet)
    # Summary differs only in its run label (row 2).
    s1, s2 = sheet_values(first.workpaper, "Summary"), sheet_values(second.workpaper, "Summary")
    assert s1[2:] == s2[2:]

    log = read_runs(settings.output_dir)
    assert [r["run_id"] for r in log] == ["2026-10-31-run01", "2026-10-31-run02"]
    assert log[1]["note"] == "Repeat of 2026-10-31-run01 (identical input file)"
    assert log[0]["input_sha256"] == log[1]["input_sha256"] == sha256_of_file(GOOD)
    assert log[0]["workpaper_sha256"] == first_hash


def test_tampered_file_is_blocked_after_a_run(settings):
    runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    report = runner.check(settings, TAMPERED, AS_OF, CONTROL)
    checks = {c.name: c for c in report.checks}
    assert checks["Input unchanged since earlier run"].status == "BLOCK"
    assert "2026-10-31-run01" in checks["Input unchanged since earlier run"].message
    out = runner.run(settings, TAMPERED, AS_OF, CONTROL, "Op")
    assert out.exit_code == runner.EXIT_BLOCKED
    assert len(read_runs(settings.output_dir)) == 1


def test_tampered_file_alone_still_fails_reconciliation(settings):
    # Without an earlier run there is nothing to compare the fingerprint to,
    # but the control total still catches the edit: 2,300.00 became 230.00,
    # so the file is 2,070.00 short of the GL balance.
    out = runner.run(settings, TAMPERED, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_DIFFERENCE
    assert out.recon.difference == D("-2070.00")


def test_corrected_export_is_allowed_and_recorded(settings):
    runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    reason = "Re-export approved by AR reviewer, ticket 1234"
    out = runner.run(settings, TAMPERED, AS_OF, D("58420.75"), "Op",
                     corrected_reason=reason, now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_OK
    assert out.run_id == "2026-10-31-run02"
    assert read_runs(settings.output_dir)[-1]["note"] == f"Corrected export: {reason}"
    info = {r[0]: r[1] for r in sheet_values(out.workpaper, "Run Info")[3:]}
    assert info["Note"] == f"Corrected export: {reason}"


def test_workpaper_never_overwrites(settings):
    out = runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    before = sha256_of_file(out.workpaper)
    info = RunInfo("x", "t", "p", "s", "v", "a", "h", "c")
    with pytest.raises(FileExistsError):
        write_workpaper(out.workpaper, out.result, out.recon, out.report, info)
    assert sha256_of_file(out.workpaper) == before


def test_missing_run_log_still_never_overwrites(settings):
    # If someone deletes the run log, numbering restarts at run01, but the
    # existing run01 workpaper is protected rather than replaced.
    out = runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    (settings.output_dir / "run_log.csv").unlink()
    with pytest.raises(FileExistsError):
        runner.run(settings, GOOD, AS_OF, CONTROL, "Op", now=FIXED_NOW)
    assert out.workpaper.is_file()
