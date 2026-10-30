"""Independent source joins and two-order substitution arithmetic, without analysis imports."""

import argparse, csv, hashlib, itertools, json, sqlite3
from fractions import Fraction as Q
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", type=Path, required=True)
    a = p.parse_args()
    checks = 0

    def check(condition):
        nonlocal checks
        assert condition, f"Independent condition {checks+1} failed"
        checks += 1

    def read(path):
        return list(csv.DictReader(path.open(encoding="utf-8")))

    source = read(ROOT / "data/summary_rows.csv")
    geo = {
        r["id"]: r["name"]
        for r in json.loads(
            (ROOT / "data/expected_geographies.json").read_text(encoding="utf-8")
        )["geographies"]
    }
    db = sqlite3.connect(":memory:")
    db.execute(
        "create table facts(t text,g text,n text,p25 text,p100 text,primary key(t,g))"
    )
    for r in source:
        check(
            r["geography_id"] in geo and r["geography_desc"] == geo[r["geography_id"]]
        )
        check(
            (r["area_data_type"], r["geography_type"], r["biz_res"], r["technology"])
            == ("Total", "State", "R", "Any Terrestrial")
        )
        n, p25, p100 = map(Q, [r["total_units"], r["speed_25_3"], r["speed_100_20"]])
        check(n.denominator == 1 and n > 0)
        check(0 <= p100 <= p25 <= 1)
        db.execute(
            "insert into facts values(?,?,?,?,?)",
            (
                r["data_as_of"],
                r["geography_id"],
                r["total_units"],
                r["speed_25_3"],
                r["speed_100_20"],
            ),
        )
    check(len(source) == 204)
    check(
        set(db.execute("select t,g from facts"))
        == {
            (t, g)
            for t in ["2023-12-31", "2024-06-30", "2024-12-31", "2025-06-30"]
            for g in geo
        }
    )
    execution = json.loads((a.results / "execution.json").read_text(encoding="utf-8"))
    phase = execution["phase"]
    check(phase in ["development", "later"])
    transitions = (
        [("2023-12-31", "2024-06-30")]
        if phase == "development"
        else [("2024-06-30", "2024-12-31"), ("2024-12-31", "2025-06-30")]
    )
    keys = {
        (s, e, g, speed)
        for s, e in transitions
        for g in geo
        for speed in ["speed_25_3", "speed_100_20"]
    }

    def source_values(start, end, g, speed):
        col = "p25" if speed == "speed_25_3" else "p100"
        n0, p0 = map(
            Q,
            db.execute(
                "select n," + col + " from facts where t=? and g=?", (start, g)
            ).fetchone(),
        )
        n1, p1 = map(
            Q,
            db.execute(
                "select n," + col + " from facts where t=? and g=?", (end, g)
            ).fetchone(),
        )
        return n0, n1, p0, p1

    def arithmetic(n0, n1, p0, p1):
        i0, i1 = n0 * p0, n1 * p1
        # Average the two full substitution orders, independently of the primary closed form.
        s = ((i1 / n0 - p0) + (p1 - i0 / n1)) * 50
        d = ((i0 / n1 - p0) + (p1 - i1 / n0)) * 50
        change = (p1 - p0) * 100
        check(s + d == change)
        feasible = i0 <= n1
        return dict(
            implied0=i0,
            implied1=i1,
            unit_change=n1 - n0,
            relative_unit_change=(n1 - n0) / n0,
            share_change_pp=change,
            numerator_component_pp=s,
            denominator_component_pp=d,
            counterfactual_status="feasible" if feasible else "infeasible",
            constant_implied_count_change_pp=(i0 / n1 - p0) * 100 if feasible else "",
        )

    pairs = read(a.results / "pairs.csv")
    expected = {}
    check(len(pairs) == len(keys))
    for r in pairs:
        key = tuple(r[k] for k in ["start", "end", "geography_id", "speed"])
        check(key in keys and key not in expected)
        s, e, g, speed = key
        check(
            r["state"] == geo[g]
            and r["transition"] == s + " to " + e
            and r["phase"] == phase
        )
        n0, n1, p0, p1 = source_values(*key)
        for k, v in [("n0", n0), ("n1", n1), ("p0", p0), ("p1", p1)]:
            check(Q(r[k]) == v)
        value = arithmetic(n0, n1, p0, p1)
        for k, v in value.items():
            check(r[k] == v if isinstance(v, str) else Q(r[k]) == v)
        expected[key] = value
    check(set(expected) == keys)

    def interval(p):
        return max(0, p - Q(1, 10000)), min(1, p + Q(1, 10000))

    cases = read(a.results / "sensitivity.csv")
    casevalues = {}
    check(len(cases) == 4 * len(keys))
    for r in cases:
        key = tuple(r[k] for k in ["start", "end", "geography_id", "speed"])
        check(key in keys)
        case = r["case"]
        check(case in ["00", "01", "10", "11"] and (*key, case) not in casevalues)
        n0, n1, p0, p1 = source_values(*key)
        a0, b0 = interval(p0)[int(case[0])], interval(p1)[int(case[1])]
        check(Q(r["p0_case"]) == a0 and Q(r["p1_case"]) == b0)
        value = arithmetic(n0, n1, a0, b0)
        for field in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            check(Q(r[field]) == value[field])
        casevalues[(*key, case)] = value
    bounds = read(a.results / "bounds.csv")
    boundvalues = {}
    check(len(bounds) == len(keys))
    for r in bounds:
        key = tuple(r[k] for k in ["start", "end", "geography_id", "speed"])
        check(key in keys and key not in boundvalues)
        mapped = {}
        for field in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            values = [
                casevalues[(*key, case)][field] for case in ["00", "01", "10", "11"]
            ]
            lo, hi = min(values), max(values)
            label = (
                "positive"
                if lo > 0
                else (
                    "negative" if hi < 0 else ("zero" if lo == hi == 0 else "ambiguous")
                )
            )
            check(Q(r[field + "_min"]) == lo)
            check(Q(r[field + "_max"]) == hi)
            check(r[field + "_stable_sign"] == label)
            mapped[field] = label
        boundvalues[key] = mapped
    summaries = read(a.results / "summary.csv")
    summarykeys = set()
    check(len(summaries) == (2 if phase == "development" else 6))
    for r in summaries:
        skey = r["transition"], r["speed"]
        check(skey not in summarykeys)
        summarykeys.add(skey)
        group = [
            key
            for key in keys
            if key[3] == r["speed"]
            and (
                r["transition"] == "All later transitions"
                or key[0] + " to " + key[1] == r["transition"]
            )
        ]
        check(len(group) == int(r["pairs"]) and len(group) > 0)
        v = lambda field: [expected[key][field] for key in group]
        calculated = dict(
            reported_share_increase=sum(x > 0 for x in v("share_change_pp")),
            reported_share_decrease=sum(x < 0 for x in v("share_change_pp")),
            reported_share_unchanged=sum(x == 0 for x in v("share_change_pp")),
            positive_denominator_component=sum(
                x > 0 for x in v("denominator_component_pp")
            ),
            negative_denominator_component=sum(
                x < 0 for x in v("denominator_component_pp")
            ),
            zero_denominator_component=sum(
                x == 0 for x in v("denominator_component_pp")
            ),
        )
        for field in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            calculated["mean_" + field] = sum(v(field)) / len(group)
        ds = sorted(v("denominator_component_pp"))
        mid = len(ds) // 2
        calculated.update(
            mean_abs_denominator_pp=sum(map(abs, ds)) / len(ds),
            median_denominator_pp=(
                ds[mid] if len(ds) % 2 else Q(ds[mid - 1] + ds[mid], 2)
            ),
            max_abs_denominator_pp=max(map(abs, ds)),
            gain_with_positive_denominator_component=sum(
                expected[key]["share_change_pp"] > 0
                and expected[key]["denominator_component_pp"] > 0
                for key in group
            ),
            counterfactual_feasible=sum(
                expected[key]["counterfactual_status"] == "feasible" for key in group
            ),
            counterfactual_infeasible=sum(
                expected[key]["counterfactual_status"] == "infeasible" for key in group
            ),
        )
        for field in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            for label in ["positive", "negative", "zero", "ambiguous"]:
                calculated[field + "_sensitivity_" + label] = sum(
                    boundvalues[key][field] == label for key in group
                )
        for k, v in calculated.items():
            check(Q(r[k]) == v)
        check(
            Q(r["mean_numerator_component_pp"]) + Q(r["mean_denominator_component_pp"])
            == Q(r["mean_share_change_pp"])
        )
    check(
        execution["state_speed_pairs"] == len(keys)
        and execution["authored_endpoint_cases"] == 4 * len(keys)
    )
    check(
        execution["source_projection_sha256"]
        == hashlib.sha256((ROOT / "data/summary_rows.csv").read_bytes()).hexdigest()
    )
    check(execution["perturbation_fraction"] == "1/10000")
    result = dict(
        status="PASS_INDEPENDENT_EXACT_RECONSTRUCTION",
        phase=phase,
        checks=checks,
        state_speed_pairs=len(keys),
        authored_endpoint_cases=len(cases),
        source_network=False,
        no_analysis_imports=True,
    )
    (a.results / "verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
