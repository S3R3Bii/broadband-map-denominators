"""Exact symmetric accounting; components are not causal effects or new connections."""

import argparse, csv, hashlib, itertools, json, subprocess
from collections import defaultdict
from fractions import Fraction as F
from pathlib import Path
from build_inputs import validate, writecsv, dump

ROOT = Path(__file__).resolve().parents[1]
PERTURBATION = F(1, 10000)
TRANSITIONS = {
    "development": [("2023-12-31", "2024-06-30")],
    "later": [("2024-06-30", "2024-12-31"), ("2024-12-31", "2025-06-30")],
}
SPEEDS = ["speed_25_3", "speed_100_20"]


def components(n0, n1, p0, p1):
    n0, n1, p0, p1 = map(F, [n0, n1, p0, p1])
    assert (
        n0 > 0
        and n1 > 0
        and n0.denominator == n1.denominator == 1
        and 0 <= p0 <= 1
        and 0 <= p1 <= 1
    )
    i0, i1 = n0 * p0, n1 * p1
    # 50 is 100 percentage points times the half-weight for the two substitution orders.
    s = 50 * (i1 - i0) * (1 / n0 + 1 / n1)
    d = 50 * (i0 + i1) * (1 / n1 - 1 / n0)
    change = 100 * (p1 - p0)
    assert s + d == change
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
        constant_implied_count_change_pp=100 * (i0 / n1 - p0) if feasible else "",
    )


def endpoints(p):
    return max(F(0), F(p) - PERTURBATION), min(F(1), F(p) + PERTURBATION)


def stable(lo, hi):
    assert lo <= hi
    return (
        "positive"
        if lo > 0
        else ("negative" if hi < 0 else ("zero" if lo == hi == 0 else "ambiguous"))
    )


def median(values):
    v = sorted(values)
    i = len(v) // 2
    return v[i] if len(v) % 2 else (v[i - 1] + v[i]) / 2


def summarize(pairs, bounds):
    groups = defaultdict(list)
    boundkeys = {
        (r["start"], r["end"], r["geography_id"], r["speed"]): r for r in bounds
    }
    for row in pairs:
        groups[row["transition"], row["speed"]].append(row)
        if len({r["transition"] for r in pairs}) > 1:
            groups["All later transitions", row["speed"]].append(row)
    result = []
    for (transition, speed), group in sorted(groups.items()):
        values = lambda k: [F(r[k]) for r in group]
        row = dict(
            phase=group[0]["phase"],
            transition=transition,
            speed=speed,
            pairs=len(group),
            reported_share_increase=sum(x > 0 for x in values("share_change_pp")),
            reported_share_decrease=sum(x < 0 for x in values("share_change_pp")),
            reported_share_unchanged=sum(x == 0 for x in values("share_change_pp")),
            positive_denominator_component=sum(
                x > 0 for x in values("denominator_component_pp")
            ),
            negative_denominator_component=sum(
                x < 0 for x in values("denominator_component_pp")
            ),
            zero_denominator_component=sum(
                x == 0 for x in values("denominator_component_pp")
            ),
        )
        for name in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            row["mean_" + name] = str(sum(values(name)) / len(group))
        ds = values("denominator_component_pp")
        row.update(
            mean_abs_denominator_pp=str(sum(map(abs, ds)) / len(group)),
            median_denominator_pp=str(median(ds)),
            max_abs_denominator_pp=str(max(map(abs, ds))),
            gain_with_positive_denominator_component=sum(
                F(r["share_change_pp"]) > 0 and F(r["denominator_component_pp"]) > 0
                for r in group
            ),
            counterfactual_feasible=sum(
                r["counterfactual_status"] == "feasible" for r in group
            ),
            counterfactual_infeasible=sum(
                r["counterfactual_status"] == "infeasible" for r in group
            ),
        )
        for field in [
            "share_change_pp",
            "numerator_component_pp",
            "denominator_component_pp",
        ]:
            for label in ["positive", "negative", "zero", "ambiguous"]:
                row[field + "_sensitivity_" + label] = sum(
                    boundkeys[r["start"], r["end"], r["geography_id"], r["speed"]][
                        field + "_stable_sign"
                    ]
                    == label
                    for r in group
                )
        result.append(row)
    return result


def run(phase, out):
    rows = list(csv.DictReader((ROOT / "data/summary_rows.csv").open(encoding="utf-8")))
    geo = {
        r["id"]: r["name"]
        for r in json.loads(
            (ROOT / "data/expected_geographies.json").read_text(encoding="utf-8")
        )["geographies"]
    }
    validate(rows, geo)
    index = {(r["data_as_of"], r["geography_id"]): r for r in rows}
    pairs = []
    cases = []
    bounds = []
    for start, end in TRANSITIONS[phase]:
        transition = start + " to " + end
        for key in sorted(geo):
            old, new = index[start, key], index[end, key]
            for speed in SPEEDS:
                common = dict(
                    phase=phase,
                    transition=transition,
                    start=start,
                    end=end,
                    geography_id=key,
                    state=geo[key],
                    speed=speed,
                )
                n0, n1, p0, p1 = map(
                    F, [old["total_units"], new["total_units"], old[speed], new[speed]]
                )
                point = components(n0, n1, p0, p1)
                pairs.append(
                    dict(
                        common,
                        n0=str(n0),
                        n1=str(n1),
                        p0=str(p0),
                        p1=str(p1),
                        **{k: str(v) for k, v in point.items()},
                    )
                )
                current = []
                for ai, bi in itertools.product(range(2), repeat=2):
                    a, b = endpoints(p0)[ai], endpoints(p1)[bi]
                    value = components(n0, n1, a, b)
                    row = dict(
                        common,
                        case=f"{ai}{bi}",
                        p0_case=str(a),
                        p1_case=str(b),
                        share_change_pp=str(value["share_change_pp"]),
                        numerator_component_pp=str(value["numerator_component_pp"]),
                        denominator_component_pp=str(value["denominator_component_pp"]),
                    )
                    cases.append(row)
                    current.append(row)
                bound = dict(common)
                for field in [
                    "share_change_pp",
                    "numerator_component_pp",
                    "denominator_component_pp",
                ]:
                    values = [F(r[field]) for r in current]
                    lo, hi = min(values), max(values)
                    bound[field + "_min"] = str(lo)
                    bound[field + "_max"] = str(hi)
                    bound[field + "_stable_sign"] = stable(lo, hi)
                bounds.append(bound)
    out.mkdir(parents=True, exist_ok=False)
    for name, content in [
        ("pairs", pairs),
        ("sensitivity", cases),
        ("bounds", bounds),
        ("summary", summarize(pairs, bounds)),
    ]:
        writecsv(out / (name + ".csv"), content)
    receipt = dict(
        status="PASS_FIXED_DESCRIPTIVE_EXECUTION",
        phase=phase,
        state_speed_pairs=len(pairs),
        authored_endpoint_cases=len(cases),
        source_network=False,
        no_fitting=True,
        source_projection_sha256=hashlib.sha256(
            (ROOT / "data/summary_rows.csv").read_bytes()
        ).hexdigest(),
        perturbation_fraction=str(PERTURBATION),
        perturbation_meaning="Authored sensitivity; not native rounding, sampling uncertainty or a source-error bound",
    )
    dump(out / "execution.json", receipt)
    print(json.dumps(receipt))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=list(TRANSITIONS), required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.phase == "later":
        path = ROOT / "data/dependency_freeze.json"
        assert path.read_bytes() == subprocess.check_output(
            ["git", "show", "HEAD:data/dependency_freeze.json"], cwd=ROOT
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            assert (
                hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
                == item["sha256"]
            )
    run(a.phase, a.out)


if __name__ == "__main__":
    main()
