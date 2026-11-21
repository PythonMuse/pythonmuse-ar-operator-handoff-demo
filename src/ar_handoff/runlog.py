"""Append-only run log: the output manifest.

Every completed run adds one row. Nothing is ever rewritten or deleted here,
so the log shows every attempt, including the ones that did not reconcile.
The log stores the input file's SHA-256 fingerprint, not the data itself.
"""

from __future__ import annotations

import csv
from pathlib import Path

LOG_NAME = "run_log.csv"

FIELDS = [
    "run_id", "run_timestamp_utc", "as_of", "prepared_by", "input_file",
    "input_sha256", "rows", "aging_total", "control_total", "difference",
    "status", "rules_version", "rules_sha256", "code_version",
    "workpaper_file", "workpaper_sha256", "note",
]


def log_path(output_dir: Path) -> Path:
    return Path(output_dir) / LOG_NAME


def read_runs(output_dir: Path) -> list[dict]:
    path = log_path(output_dir)
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def runs_for(output_dir: Path, as_of_iso: str) -> list[dict]:
    return [r for r in read_runs(output_dir) if r["as_of"] == as_of_iso]


def append_run(output_dir: Path, record: dict) -> None:
    path = log_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({k: record.get(k, "") for k in FIELDS})
