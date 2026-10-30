"""Independent DuckDB CSV parser and SQL reconciliation of all original selected tokens."""

import argparse, csv, hashlib, json, tempfile, zipfile
from fractions import Fraction
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--private-dir", type=Path, required=True)
    a = p.parse_args()
    rows = list(csv.DictReader((ROOT / "data/summary_rows.csv").open(encoding="utf-8")))
    coverage = {
        r["data_as_of"]: r
        for r in csv.DictReader((ROOT / "data/coverage.csv").open(encoding="utf-8"))
    }
    geo = {
        r["id"]: r["name"]
        for r in json.loads(
            (ROOT / "data/expected_geographies.json").read_text(encoding="utf-8")
        )["geographies"]
    }
    receipts = json.loads(
        (ROOT / "data/source_receipts.json").read_text(encoding="utf-8")
    )
    checks = 0
    before = {}
    scratch = a.private_dir.parent / "broadband35-readers"
    scratch.mkdir(exist_ok=True)
    assert scratch.resolve().is_relative_to(a.private_dir.parent.resolve())
    for rec in receipts:
        date = rec["data_as_of"]
        archive = a.private_dir / date / rec["file"]
        before[archive] = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert before[archive] == rec["sha256"]
        checks += 1
        expected = {r["geography_id"]: r for r in rows if r["data_as_of"] == date}
        assert len(expected) == 51
        checks += 1
        with tempfile.TemporaryDirectory(dir=scratch, prefix="native-csv-") as temp:
            temp = Path(temp).resolve()
            assert temp.is_relative_to(scratch.resolve())
            with zipfile.ZipFile(archive) as z:
                assert len(z.namelist()) == 1
                member = z.namelist()[0]
                raw = z.read(member)
                assert hashlib.sha256(raw).hexdigest() == rec["source_member_sha256"]
                checks += 2
                path = temp / "summary.csv"
                path.write_bytes(raw)
            db = duckdb.connect()
            db.execute("SET preserve_insertion_order=true")
            db.execute(
                "CREATE TABLE original AS SELECT row_number() OVER () AS native_row, * FROM read_csv(?,all_varchar=true,parallel=false)",
                [str(path)],
            )
            assert db.execute("SELECT count(*) FROM original").fetchone()[0] == int(
                coverage[date]["source_rows_scanned"]
            )
            checks += 1
            query = """SELECT native_row,geography_id,geography_desc,total_units,speed_25_3,speed_100_20,area_data_type,geography_type,biz_res,technology FROM original WHERE geography_type='State' AND area_data_type='Total' AND biz_res='R' AND technology='Any Terrestrial'"""
            found = []
            for (
                native_row,
                native_id,
                name,
                n,
                p25,
                p100,
                area,
                kind,
                biz,
                technology,
            ) in db.execute(query).fetchall():
                key = native_id.zfill(2)
                if key not in geo:
                    continue
                r = expected[key]
                exact_n, exact_p, exact_q = Fraction(n), Fraction(p25), Fraction(p100)
                assert exact_n.denominator == 1 and exact_n > 0
                assert 0 <= exact_q <= exact_p <= 1
                checks += 2
                for k, v in [
                    ("source_data_row", str(native_row)),
                    ("native_geography_id", native_id),
                    ("geography_desc", name),
                    ("total_units", n),
                    ("speed_25_3", p25),
                    ("speed_100_20", p100),
                    ("area_data_type", area),
                    ("geography_type", kind),
                    ("biz_res", biz),
                    ("technology", technology),
                    ("source_member", member),
                ]:
                    assert r[k] == v, (date, key, k)
                    checks += 1
                assert name == geo[key]
                checks += 1
                found.append(key)
            assert len(found) == len(set(found)) == 51 and set(found) == set(geo)
            checks += 2
            # Independently verify numeric eligibility and the source's speed nesting in SQL.
            bad = db.execute(
                """SELECT count(*) FROM original WHERE geography_type='State' AND area_data_type='Total' AND biz_res='R' AND technology='Any Terrestrial' AND try_cast(geography_id AS INTEGER)<=56 AND (try_cast(total_units AS BIGINT) IS NULL OR try_cast(speed_100_20 AS DECIMAL(38,20)) IS NULL OR try_cast(speed_25_3 AS DECIMAL(38,20)) IS NULL OR try_cast(total_units AS BIGINT)<=0 OR try_cast(speed_100_20 AS DECIMAL(38,20))<0 OR try_cast(speed_25_3 AS DECIMAL(38,20))>1 OR try_cast(speed_100_20 AS DECIMAL(38,20))>try_cast(speed_25_3 AS DECIMAL(38,20)))"""
            ).fetchone()[0]
            assert bad == 0
            checks += 1
            db.close()
    for path, digest in before.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        checks += 1
    result = dict(
        status="PASS_INDEPENDENT_NATIVE_CSV_SQL_RECONCILIATION",
        count_rows=204,
        source_numeric_cells=612,
        checks=checks,
        parser="DuckDB " + duckdb.__version__,
        original_hashes_unchanged=True,
        temporary_csv="Only the bound source member; private verified workspace; removed after each reader",
        source_network=False,
    )
    (ROOT / "data/original_verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
