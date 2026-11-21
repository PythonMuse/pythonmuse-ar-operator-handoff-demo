"""Both operator interfaces are thin: they call runner.check() and runner.run()
and nothing else, so they cannot disagree about the accounting."""

import ast
from pathlib import Path

import pytest

from ar_handoff import launcher, runner
from ar_handoff.runlog import read_runs

from conftest import GOOD, ROOT, SAMPLE

SRC = ROOT / "src" / "ar_handoff"
LOGIC_MODULES = {"engine", "validate", "workpaper", "config", "runlog"}


@pytest.mark.parametrize("module", ["launcher.py", "desktop.py"])
def test_interfaces_import_no_accounting_logic(module):
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            imported.add(node.module or "")
            imported.update(a.name for a in node.names if node.module is None)
    assert not imported & LOGIC_MODULES, imported


def base_args(tmp_path, path=GOOD, control="60490.75"):
    return ["--as-of", "2026-10-31", "--input", str(path), "--control-total", control,
            "--prepared-by", "Demo Operator", "--output", str(tmp_path / "out"),
            "--approved-root", str(SAMPLE)]


def test_terminal_good_file(tmp_path, capsys):
    code = launcher.main(base_args(tmp_path) + ["--yes"])
    out = capsys.readouterr().out
    assert code == runner.EXIT_OK
    assert "CHECKS PASSED - READY FOR REVIEW" in out
    assert "60,490.75" in out
    assert "exceptions to review 6" in out
    assert "does not mean the accounting is correct" in out


def test_terminal_bad_file_stops_with_clear_message(tmp_path, capsys):
    bad = SAMPLE / "bad_schema" / "AR_Open_Items_2026-10-31.csv"
    code = launcher.main(base_args(tmp_path, bad) + ["--yes"])
    out = capsys.readouterr().out
    assert code == runner.EXIT_BLOCKED
    assert "[STOP] Required columns present" in out
    assert "Nothing was run" in out
    assert read_runs(tmp_path / "out") == []


def test_terminal_operator_can_cancel(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    code = launcher.main(base_args(tmp_path))
    assert code == runner.EXIT_CANCELLED
    assert "Nothing was run" in capsys.readouterr().out
    assert read_runs(tmp_path / "out") == []


def test_terminal_guided_prompts(tmp_path, capsys, monkeypatch):
    answers = iter(["2026-10-31", str(GOOD), "60,490.75", "Demo Operator", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    code = launcher.main(["--output", str(tmp_path / "out"),
                          "--approved-root", str(SAMPLE)])
    assert code == runner.EXIT_OK


def test_terminal_rejects_bad_date(tmp_path, capsys):
    args = base_args(tmp_path)
    args[1] = "31/10/2026"
    assert launcher.main(args + ["--yes"]) == runner.EXIT_BLOCKED


def test_last_month_end():
    from datetime import date
    assert launcher.last_month_end(date(2026, 11, 21)) == date(2026, 10, 31)
    assert launcher.last_month_end(date(2028, 3, 1)) == date(2028, 2, 29)


def test_desktop_app_check_then_run(tmp_path):
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
        assert str(app.run_btn["state"]) == "disabled"

        # Bad file: Run stays off, nothing is written.
        app.as_of.set("2026-10-31")
        app.input_path.set(str(SAMPLE / "bad_duplicate_id" / "AR_Open_Items_2026-10-31.csv"))
        app.control.set("60,490.75")
        app.prepared_by.set("Demo Operator")
        assert not app.on_check().can_run
        assert str(app.run_btn["state"]) == "disabled"
        assert app.on_run() is None

        # Good file: Run switches on after a check, and off again if a field changes.
        app.input_path.set(str(GOOD))
        assert app.on_check().can_run
        assert str(app.run_btn["state"]) == "normal"
        app.control.set("60490.75")
        assert str(app.run_btn["state"]) == "disabled"
        app.on_check()
        outcome = app.on_run()
        assert outcome.exit_code == runner.EXIT_OK
        assert outcome.workpaper.is_file()
        assert "READY FOR REVIEW" in app.panel.get("1.0", "end")
    finally:
        root.destroy()
