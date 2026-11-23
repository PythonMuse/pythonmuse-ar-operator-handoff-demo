"""Hardening: the things that go wrong around a run, not in the accounting.

- Text from the input file or the operator never becomes a live formula.
- If the output can't be written, the operator gets a message, not a crash,
  and nothing is left half-done.
- A broken rules file gives the maintainer a clear message.
- The version number is the same everywhere it is written.
"""

import csv
import sys
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from ar_handoff import __version__, launcher, runner
from ar_handoff.config import RulesError, load_rules
from ar_handoff.runlog import read_runs

from conftest import AS_OF, FIXED_NOW, GOOD, ROOT, SAMPLE, write_csv

EVIL_NAME = '=HYPERLINK("http://example.invalid","Click me")'
EVIL_ID = "=1+1"


# --- Text never becomes a formula ---------------------------------------------

def test_input_text_stays_text_in_the_workpaper(tmp_settings):
    path = write_csv(tmp_settings.approved_root,
                     f'INV-1,{EVIL_ID},"{EVIL_NAME.replace(chr(34), 2 * chr(34))}",'
                     f"2026-10-01,2026-10-31,100.00\n")
    out = runner.run(tmp_settings, path, AS_OF, D("100.00"), "=SUM(A1:A9)",
                     now=FIXED_NOW)
    assert out.exit_code == runner.EXIT_OK
    wb = load_workbook(out.workpaper)

    found = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value in (EVIL_NAME, EVIL_ID, "=SUM(A1:A9)"):
                    assert cell.data_type == "s", (ws.title, cell.coordinate)
                    found += 1
    # The customer name and customer ID on Detail and By Customer, and
    # "Prepared by" on Run Info.
    assert found >= 5

    # The workpaper's own formulas are still live.
    assert wb["Summary"]["B14"].data_type == "f"
    assert wb["Reconciliation"]["B6"].value == "=B4-B5"


def test_operator_text_is_escaped_in_the_run_log(settings):
    runner.run(settings, GOOD, AS_OF, D("60490.75"), "=cmd|' /C calc'!A0",
               now=FIXED_NOW)
    row = read_runs(settings.output_dir)[-1]
    assert row["prepared_by"] == "'=cmd|' /C calc'!A0"
    assert row["aging_total"] == "60490.75"


def test_negative_difference_is_not_escaped_in_the_run_log(settings):
    runner.run(settings, GOOD, AS_OF, D("61130.75"), "Op", now=FIXED_NOW)
    assert read_runs(settings.output_dir)[-1]["difference"] == "-640.00"


# --- Output that can't be written ---------------------------------------------

def _break_log(settings):
    """Make the run log unwritable on every OS: put a folder where the file goes."""
    (settings.output_dir / "run_log.csv").mkdir(parents=True)


def test_unwritable_log_stops_cleanly_and_writes_nothing(settings):
    _break_log(settings)
    with pytest.raises(runner.RunError, match="close it and try again"):
        runner.run(settings, GOOD, AS_OF, D("60490.75"), "Op", now=FIXED_NOW)
    assert not list(settings.output_dir.rglob("*.xlsx"))


def test_log_failure_after_saving_removes_the_workpaper(settings, monkeypatch):
    def locked(*_a, **_k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(runner, "append_run", locked)
    with pytest.raises(runner.RunError, match="Nothing was written"):
        runner.run(settings, GOOD, AS_OF, D("60490.75"), "Op", now=FIXED_NOW)
    assert not list(settings.output_dir.rglob("*.xlsx"))
    # ...so the next run isn't blocked by an orphan run01.
    monkeypatch.undo()
    out = runner.run(settings, GOOD, AS_OF, D("60490.75"), "Op", now=FIXED_NOW)
    assert out.run_id == "2026-10-31-run01"


def test_unreadable_input_is_a_stop_not_a_crash(settings, monkeypatch):
    import ar_handoff.validate as validate

    def locked(_path):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(validate, "sha256_of_file", locked)
    report = runner.check(settings, GOOD, AS_OF, None)
    assert not report.can_run
    assert report.checks[-1].name == "File readable"
    assert "close it" in report.checks[-1].message


def _args(tmp_path):
    return ["--as-of", "2026-10-31", "--input", str(GOOD), "--control-total",
            "60490.75", "--prepared-by", "Op", "--output", str(tmp_path / "out"),
            "--approved-root", str(SAMPLE)]


def test_terminal_reports_write_failure_without_traceback(tmp_path, capsys):
    (tmp_path / "out" / "run_log.csv").mkdir(parents=True)
    code = launcher.main(_args(tmp_path) + ["--yes"])
    out = capsys.readouterr().out
    assert code == runner.EXIT_ERROR
    assert "STOP: Could not use the run log" in out
    assert "Traceback" not in out


def test_terminal_unattended_without_answers_cancels(tmp_path, capsys, monkeypatch):
    def no_one_there(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_one_there)
    code = launcher.main(["--output", str(tmp_path / "out"),
                          "--approved-root", str(SAMPLE)])
    assert code == runner.EXIT_CANCELLED
    assert "Nothing was run" in capsys.readouterr().out
    assert read_runs(tmp_path / "out") == []


def test_desktop_shows_write_failure_in_the_window(tmp_path):
    tk = pytest.importorskip("tkinter")
    from ar_handoff.desktop import ARReviewApp
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for Tkinter")
    root.withdraw()
    try:
        settings = runner.load_settings(runner.DEFAULT_RULES, tmp_path / "out",
                                        approved_root=SAMPLE)
        app = ARReviewApp(root, settings)
        app.as_of.set("2026-10-31")
        app.input_path.set(str(GOOD))
        app.control.set("60490.75")
        assert app.on_check().can_run
        _break_log(settings)
        assert app.on_run() is None
        panel = app.panel.get("1.0", "end")
        assert "STOP" in panel and "Could not use the run log" in panel
        assert str(app.run_btn["state"]) == "disabled"
    finally:
        root.destroy()


# --- Broken rules files -------------------------------------------------------

RULES_TEXT = (ROOT / "config" / "rules.example.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("old, new, expected", [
    ('  - label: "Over 90"\n    max_days: null', '  - "Over 90"', "label and max_days"),
    ("    max_days: 30", "    max_days: true", "whole-number max_days"),
    ("  days_past_due: 90", "  days_past_due: yes", "days_past_due"),
])
def test_broken_rules_give_a_clear_message(tmp_path, old, new, expected):
    assert old in RULES_TEXT
    path = tmp_path / "rules.yaml"
    path.write_text(RULES_TEXT.replace(old, new), encoding="utf-8")
    with pytest.raises(RulesError, match=expected):
        load_rules(path)


def test_thresholds_must_be_a_mapping(tmp_path):
    text = RULES_TEXT.split("exception_thresholds:")[0] + "exception_thresholds: 90\n"
    path = tmp_path / "rules.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RulesError, match="exception_thresholds"):
        load_rules(path)


# --- One version number -------------------------------------------------------

@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib needs Python 3.11+")
def test_version_matches_pyproject():
    import tomllib
    with open(ROOT / "pyproject.toml", "rb") as f:
        assert tomllib.load(f)["project"]["version"] == __version__


def test_example_run_log_matches_the_example_workpaper():
    from ar_handoff.config import sha256_of_file
    folder = ROOT / "examples" / "expected_output"
    with open(folder / "run_log.csv", newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    workpaper = folder / row["workpaper_file"].split("/")[-1]
    assert sha256_of_file(workpaper) == row["workpaper_sha256"]
    assert row["code_version"] == __version__
