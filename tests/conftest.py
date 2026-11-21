from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ar_handoff import runner

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
GOOD = SAMPLE / "AR_Open_Items_2026-10-31.csv"
AS_OF = date(2026, 10, 31)
FIXED_NOW = datetime(2026, 11, 3, 14, 30, tzinfo=timezone.utc)
HEADER = "invoice_id,customer_id,customer_name,invoice_date,due_date,open_amount\n"


@pytest.fixture
def settings(tmp_path):
    """Approved rules, the real sample_data folder, and a fresh output folder."""
    return runner.load_settings(runner.DEFAULT_RULES, tmp_path / "output",
                                approved_root=SAMPLE)


@pytest.fixture
def tmp_settings(tmp_path):
    """Same rules, but the approved input folder is a temporary folder, so a
    test can write its own deliberately broken file."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return runner.load_settings(runner.DEFAULT_RULES, tmp_path / "output",
                                approved_root=inbox)


def write_csv(folder: Path, body: str, as_of: str = "2026-10-31",
              header: str = HEADER) -> Path:
    path = folder / f"AR_Open_Items_{as_of}.csv"
    path.write_text(header + body, encoding="utf-8")
    return path
