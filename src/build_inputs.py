"""Stream four preserved public summaries into an exact, bounded state-level projection."""

import argparse, csv, hashlib, io, json, re, zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATES = ["2023-12-31", "2024-06-30", "2024-12-31", "2025-06-30"]
SOURCE_FIELDS = [
    "area_data_type",
    "geography_type",
    "geography_id",
    "geography_desc",
    "geography_desc_full",
    "total_units",
    "biz_res",
    "technology",
    "speed_02_02",
    "speed_10_1",
    "speed_25_3",
    "speed_100_20",
    "speed_250_25",
    "speed_1000_100",
]


def dump(path, obj):
    path.write_bytes((json.dumps(obj, indent=2) + "\n").encode())


def writecsv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def revision(filename, date):
    match = re.fullmatch(
        r"bdc_us_fixed_broadband_summary_by_geography_([JD])(\d{2})_(\d{2}[a-zA-Z]{3}\d{4})\.zip",
        filename,
    )
    assert match
    expected = "20" + match[2] + ("-06-30" if match[1] == "J" else "-12-31")
    assert expected == date
    return datetime.strptime(match[3], "%d%b%Y").date().isoformat()


def validate(rows, geographies):
    keys = [(r["data_as_of"], r["geography_id"]) for r in rows]
    expected = {(d, g) for d in DATES for g in geographies}
    assert len(rows) == len(set(keys)) == 204 and set(keys) == expected
    for r in rows:
        assert (
            r["area_data_type"] == "Total"
            and r["geography_type"] == "State"
            and r["biz_res"] == "R"
            and r["technology"] == "Any Terrestrial"
        )
        assert r["geography_desc"] == geographies[r["geography_id"]]
        n = Decimal(r["total_units"])
        assert n.is_finite() and n == n.to_integral_value() and n > 0
        p, q = Decimal(r["speed_25_3"]), Decimal(r["speed_100_20"])
        assert p.is_finite() and q.is_finite() and 0 <= q <= p <= 1
    return dict(
        status="PASS_FIXED_204_ROW_COHORT",
        rows=204,
        geographies=51,
        data_dates=4,
        native_share_cells=408,
        missing_keys=0,
        conflicting_keys=0,
        source_comparisons_computed=False,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--private-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, default=ROOT / "data")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    geo = {
        r["id"]: r["name"]
        for r in json.loads(
            (ROOT / "data/expected_geographies.json").read_text(encoding="utf-8")
        )["geographies"]
    }
    assert len(geo) == 51
    allrows = []
    ledger = []
    receipts = []
    coverage = []
    archivebytes = 0
    for date in DATES:
        folder = a.private_dir / date
        receipt = json.loads(
            (folder / "capture_receipt.json").read_text(encoding="utf-8")
        )
        archive = folder / receipt["file"]
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert digest == receipt["sha256"]
        archivebytes += archive.stat().st_size
        assert archive.stat().st_size <= 200_000_000 and archivebytes <= 800_000_000
        rev = revision(receipt["file"], date)
        groups = defaultdict(list)
        excluded = Counter()
        scanned = 0
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            assert (
                len(members) == 1
                and members[0].filename.endswith(".csv")
                and members[0].file_size <= 2_000_000_000
            )
            member = members[0].filename
            assert ".." not in Path(member).parts and not Path(member).is_absolute()
            raw = z.read(member)
            csvhash = hashlib.sha256(raw).hexdigest()
            reader = csv.DictReader(
                io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
            )
            assert reader.fieldnames == SOURCE_FIELDS
            for ordinal, row in enumerate(reader, 1):
                scanned += 1
                assert None not in row and all(v is not None for v in row.values())
                if row["geography_type"] != "State":
                    excluded["other_geography_type"] += 1
                    continue
                if row["area_data_type"] != "Total":
                    excluded["other_area_data_type"] += 1
                    continue
                if row["biz_res"] != "R":
                    excluded["other_biz_res"] += 1
                    continue
                if row["technology"] != "Any Terrestrial":
                    excluded["other_technology"] += 1
                    continue
                native = row["geography_id"]
                assert native.isdecimal() and len(native) <= 2
                key = native.zfill(2)
                if key not in geo:
                    excluded["territory_outside_fixed_state_dc_scope"] += 1
                    continue
                tokenhash = hashlib.sha256(
                    json.dumps(
                        [row[n] for n in SOURCE_FIELDS],
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                projected = dict(
                    data_as_of=date,
                    source_revision_date=rev,
                    area_data_type=row["area_data_type"],
                    geography_type=row["geography_type"],
                    geography_id=key,
                    native_geography_id=native,
                    geography_desc=row["geography_desc"],
                    biz_res=row["biz_res"],
                    technology=row["technology"],
                    total_units=row["total_units"],
                    speed_25_3=row["speed_25_3"],
                    speed_100_20=row["speed_100_20"],
                    source_archive=receipt["file"],
                    source_archive_sha256=digest,
                    source_member=member,
                    source_member_sha256=csvhash,
                    source_data_row=ordinal,
                    full_native_token_sha256=tokenhash,
                )
                groups[key].append(projected)
        conflicts = []
        for key, copies in sorted(groups.items()):
            signatures = {r["full_native_token_sha256"] for r in copies}
            status = "conflicting_copies" if len(signatures) > 1 else "eligible"
            for i, r in enumerate(copies):
                ledger.append(
                    dict(
                        data_as_of=date,
                        geography_id=key,
                        source_data_row=r["source_data_row"],
                        full_native_token_sha256=r["full_native_token_sha256"],
                        copy_count=len(copies),
                        status=(
                            status
                            if status != "eligible" or i == 0
                            else "identical_repeat"
                        ),
                    )
                )
            if len(signatures) > 1:
                conflicts.append(key)
            else:
                allrows.append(copies[0])
        assert not conflicts, conflicts
        assert scanned == sum(excluded.values()) + sum(len(c) for c in groups.values())
        coverage.append(
            dict(
                data_as_of=date,
                source_revision_date=rev,
                source_rows_scanned=scanned,
                selected_source_copies=sum(len(c) for c in groups.values()),
                eligible_state_keys=len(groups),
                identical_repeats=sum(len(c) - 1 for c in groups.values()),
                conflicts=len(conflicts),
                **dict(excluded),
            )
        )
        clean = {
            k: v for k, v in receipt.items() if k not in ["download_path", "ui_before"]
        }
        clean.update(source_member_sha256=csvhash, source_revision_date=rev)
        receipts.append(clean)
    allrows.sort(key=lambda r: (r["data_as_of"], r["geography_id"]))
    gate = validate(allrows, geo)
    writecsv(a.out / "summary_rows.csv", allrows)
    writecsv(a.out / "key_ledger.csv", ledger)
    # Every source has the same exclusion categories; a missing category is an explicit zero.
    fields = sorted({k for r in coverage for k in r})
    coverage = [{k: r.get(k, 0) for k in fields} for r in coverage]
    writecsv(a.out / "coverage.csv", coverage)
    dump(a.out / "source_receipts.json", receipts)
    dump(
        a.out / "input_receipt.json",
        dict(
            gate,
            source_rows_scanned=sum(r["source_rows_scanned"] for r in coverage),
            projection_sha256=hashlib.sha256(
                (a.out / "summary_rows.csv").read_bytes()
            ).hexdigest(),
            original_zip_bytes=archivebytes,
        ),
    )
    print(json.dumps(gate))


if __name__ == "__main__":
    main()
