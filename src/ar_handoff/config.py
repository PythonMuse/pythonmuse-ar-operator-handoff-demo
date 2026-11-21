"""Load and sanity-check the approved rules file.

The accounting rules (buckets, thresholds, tolerance, file convention) live in
a YAML file, not in the code and not in the interface. Changing a rule means
changing that file, through the maintainer, with a new rules_version.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml


class RulesError(ValueError):
    """The rules file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Bucket:
    label: str
    max_days: int | None  # None = no upper limit (the last bucket)


@dataclass(frozen=True)
class Rules:
    version: str
    approved_by: str
    approved_input_folder: str
    file_name_pattern: str
    required_columns: tuple[str, ...]
    buckets: tuple[Bucket, ...]
    days_past_due_threshold: int
    customer_balance_threshold: Decimal
    reconciliation_tolerance: Decimal
    path: Path
    sha256: str

    def expected_file_name(self, as_of_iso: str) -> str:
        return self.file_name_pattern.format(as_of=as_of_iso)


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _decimal(value, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RulesError(f"'{field}' must be a number, got {value!r}") from exc
    if d < 0:
        raise RulesError(f"'{field}' must not be negative, got {value!r}")
    return d


def load_rules(path: str | Path) -> Rules:
    path = Path(path)
    if not path.is_file():
        raise RulesError(f"Rules file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulesError(f"Rules file is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RulesError("Rules file must be a mapping of settings.")

    def need(key):
        if key not in raw or raw[key] in (None, ""):
            raise RulesError(f"Rules file is missing '{key}'.")
        return raw[key]

    version = str(need("rules_version"))
    pattern = str(need("file_name_pattern"))
    if "{as_of}" not in pattern:
        raise RulesError("'file_name_pattern' must contain {as_of}.")

    cols = need("required_columns")
    if not isinstance(cols, list) or not cols:
        raise RulesError("'required_columns' must be a non-empty list.")

    buckets_raw = need("aging_buckets")
    if not isinstance(buckets_raw, list) or len(buckets_raw) < 2:
        raise RulesError("'aging_buckets' needs at least two buckets.")
    buckets = []
    previous = None
    for i, b in enumerate(buckets_raw):
        label = str(b.get("label", "")).strip()
        max_days = b.get("max_days")
        if not label:
            raise RulesError(f"Aging bucket {i + 1} has no label.")
        last = i == len(buckets_raw) - 1
        if last:
            if max_days is not None:
                raise RulesError("The last aging bucket must have max_days: null.")
        else:
            if not isinstance(max_days, int):
                raise RulesError(f"Bucket '{label}' needs a whole-number max_days.")
            if previous is not None and max_days <= previous:
                raise RulesError("Aging buckets must be in increasing order.")
            previous = max_days
        buckets.append(Bucket(label, max_days))

    thresholds = need("exception_thresholds")
    days = thresholds.get("days_past_due")
    if not isinstance(days, int) or days < 0:
        raise RulesError("'exception_thresholds.days_past_due' must be a whole number.")

    return Rules(
        version=version,
        approved_by=str(raw.get("approved_by", "")),
        approved_input_folder=str(need("approved_input_folder")),
        file_name_pattern=pattern,
        required_columns=tuple(str(c) for c in cols),
        buckets=tuple(buckets),
        days_past_due_threshold=days,
        customer_balance_threshold=_decimal(
            thresholds.get("customer_balance_review"), "customer_balance_review"),
        reconciliation_tolerance=_decimal(
            raw.get("reconciliation_tolerance", 0), "reconciliation_tolerance"),
        path=path,
        sha256=sha256_of_file(path),
    )
