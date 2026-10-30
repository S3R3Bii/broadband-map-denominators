"""Offline two-snapshot exercise; no attribution of new connections or adoption."""

import argparse, json, re
from datetime import date
from fractions import Fraction
from pathlib import Path
from analyze import components

KEYS = [
    "geography_id",
    "geography_type",
    "area_data_type",
    "biz_res",
    "technology",
    "speed",
    "unit",
]


def compare(old, new):
    try:
        if any(not isinstance(r, dict) for r in [old, new]):
            return dict(status="unavailable", reason="Snapshot must be an object")
        if any(
            not isinstance(r.get(k), str) or not r[k].strip()
            for r in [old, new]
            for k in KEYS
        ):
            return dict(
                status="unavailable", reason="Missing geographic or service identity"
            )
        if any(old[k] != new[k] for k in KEYS):
            return dict(
                status="unavailable", reason="Geographic or service identity mismatch"
            )
        if (
            old["geography_type"] != "State"
            or old["area_data_type"] != "Total"
            or old["biz_res"] != "R"
            or old["technology"] != "Any Terrestrial"
            or old["speed"] not in ["speed_25_3", "speed_100_20"]
            or old["unit"] != "map_units"
        ):
            return dict(status="unavailable", reason="Unsupported summary definition")
        if date.fromisoformat(old["data_as_of"]) >= date.fromisoformat(
            new["data_as_of"]
        ):
            return dict(status="unavailable", reason="Data dates must be ordered")
        if any(
            not isinstance(r.get(k), str)
            for r in [old, new]
            for k in ["total_units", "share"]
        ):
            return dict(
                status="unavailable",
                reason="Use native numeric strings, not binary floats",
            )
        if any(
            re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", r[k]) is None
            for r in [old, new]
            for k in ["total_units", "share"]
        ):
            return dict(status="unavailable", reason="Finite decimal tokens required")
        value = components(
            old["total_units"], new["total_units"], old["share"], new["share"]
        )
        return dict(
            status="available",
            **{k: str(v) for k, v in value.items()},
            interpretation="Exact arithmetic of reported fractions and aggregate units; no causal or new-connection attribution"
        )
    except (AssertionError, KeyError, ValueError, TypeError, ZeroDivisionError):
        return dict(
            status="unavailable", reason="Invalid date, denominator or fractional share"
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("old", type=Path)
    p.add_argument("new", type=Path)
    a = p.parse_args()
    print(
        json.dumps(
            compare(
                json.loads(a.old.read_text(encoding="utf-8")),
                json.loads(a.new.read_text(encoding="utf-8")),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
