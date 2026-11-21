"""Bad inputs must stop safely, with a message an operator can act on, and
must leave nothing behind: no workpaper, no run-log entry."""

from datetime import date
from decimal import Decimal as D

from ar_handoff import runner
from ar_handoff.runlog import read_runs

from conftest import AS_OF, SAMPLE, write_csv

GOOD_LINE = "INV-1,C1,Test Customer,2026-10-01,2026-10-31,100.00\n"


def blocked(report, name):
    statuses = {c.name: c for c in report.checks}
    assert report.status == "BLOCK"
    assert not report.can_run
    assert statuses[name].status == "BLOCK", report.checks
    return statuses[name].message


def assert_nothing_written(settings, outcome):
    assert outcome.exit_code == runner.EXIT_BLOCKED
    assert outcome.workpaper is None
    assert read_runs(settings.output_dir) == []
    assert not settings.output_dir.exists() or not any(settings.output_dir.rglob("*.xlsx"))


def test_schema_break_seeded_file(settings):
    path = SAMPLE / "bad_schema" / "AR_Open_Items_2026-10-31.csv"
    msg = blocked(runner.check(settings, path, AS_OF, None), "Required columns present")
    assert "due_date" in msg and "open_amount" in msg and "escalate" in msg
    assert_nothing_written(settings, runner.run(settings, path, AS_OF, None, "x"))


def test_duplicate_id_seeded_file(settings):
    path = SAMPLE / "bad_duplicate_id" / "AR_Open_Items_2026-10-31.csv"
    msg = blocked(runner.check(settings, path, AS_OF, None),
                  "Invoice IDs present and unique")
    assert "INV-10004" in msg
    assert_nothing_written(settings, runner.run(settings, path, AS_OF, None, "x"))


def test_wrong_period_seeded_file(settings):
    path = SAMPLE / "wrong_date" / "AR_Open_Items_2026-09-30.csv"
    msg = blocked(runner.check(settings, path, AS_OF, None),
                  "File name matches as-of date")
    assert "AR_Open_Items_2026-10-31.csv" in msg
    # Picking the matching as-of date instead exposes October invoices in a
    # September file, which also blocks.
    report = runner.check(settings, path, date(2026, 9, 30), None)
    blocked(report, "Invoices dated on or before as-of date")


def test_bad_amount(tmp_settings):
    # A thousands separator (quoted, as Excel writes it) and a stray letter.
    path = write_csv(tmp_settings.approved_root,
                     GOOD_LINE
                     + 'INV-2,C1,Test Customer,2026-10-01,2026-10-31,"1,250.00"\n'
                     + "INV-3,C1,Test Customer,2026-10-01,2026-10-31,12.3x\n")
    msg = blocked(runner.check(tmp_settings, path, AS_OF, None), "Amounts are numbers")
    assert "line 3" in msg and "1,250.00" in msg
    assert "line 4" in msg and "12.3x" in msg


def test_bad_date(tmp_settings):
    path = write_csv(tmp_settings.approved_root,
                     GOOD_LINE + "INV-2,C1,Test Customer,31/10/2026,2026-10-31,5.00\n")
    msg = blocked(runner.check(tmp_settings, path, AS_OF, None), "Dates are valid")
    assert "line 3" in msg and "31/10/2026" in msg


def test_blank_invoice_id(tmp_settings):
    path = write_csv(tmp_settings.approved_root,
                     GOOD_LINE + ",C1,Test Customer,2026-10-01,2026-10-31,5.00\n")
    msg = blocked(runner.check(tmp_settings, path, AS_OF, None),
                  "Invoice IDs present and unique")
    assert "line 3" in msg


def test_header_only_file(tmp_settings):
    path = write_csv(tmp_settings.approved_root, "")
    blocked(runner.check(tmp_settings, path, AS_OF, None), "File has data")


def test_zero_byte_file(tmp_settings):
    path = tmp_settings.approved_root / "AR_Open_Items_2026-10-31.csv"
    path.write_bytes(b"")
    blocked(runner.check(tmp_settings, path, AS_OF, None), "Required columns present")


def test_missing_file(tmp_settings):
    path = tmp_settings.approved_root / "AR_Open_Items_2026-10-31.csv"
    blocked(runner.check(tmp_settings, path, AS_OF, None), "File found")


def test_outside_approved_folder(tmp_settings, tmp_path):
    elsewhere = tmp_path / "desktop"
    elsewhere.mkdir()
    path = write_csv(elsewhere, GOOD_LINE)
    msg = blocked(runner.check(tmp_settings, path, AS_OF, None), "Approved location")
    assert "approved input folder" in msg
    # A path that climbs out with ".." is caught too.
    sneaky = tmp_settings.approved_root / ".." / "desktop" / path.name
    blocked(runner.check(tmp_settings, sneaky, AS_OF, None), "Approved location")


def test_future_invoice(tmp_settings):
    path = write_csv(tmp_settings.approved_root,
                     GOOD_LINE + "INV-2,C1,Test Customer,2026-11-02,2026-12-02,5.00\n")
    msg = blocked(runner.check(tmp_settings, path, AS_OF, None),
                  "Invoices dated on or before as-of date")
    assert "INV-2" in msg


def test_operator_typed_values():
    assert runner.parse_amount("60,490.75") == D("60490.75")
    assert runner.parse_amount("  ") is None
    for bad in ("sixty", "NaN", "inf"):
        try:
            runner.parse_amount(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} should be rejected")
    try:
        runner.parse_as_of("10/31/2026")
    except ValueError:
        pass
    else:
        raise AssertionError("US-style date should be rejected")


def test_every_message_is_actionable(settings):
    """Every BLOCK message must say something more than 'failed'."""
    path = SAMPLE / "bad_duplicate_id" / "AR_Open_Items_2026-10-31.csv"
    stops = [c for c in runner.check(settings, path, AS_OF, None).checks
             if c.status == "BLOCK"]
    assert stops
    for c in stops:
        assert len(c.message) > 40, c
