"""Reconstruct figure values and compare the actual SVG data geometry."""

import csv, hashlib, json, re
from fractions import Fraction as F
from pathlib import Path
from xml.etree import ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"


def read(path):
    return list(csv.DictReader((ROOT / path).open(encoding="utf-8")))


def vertices(node):
    p = node.find(".//" + SVG + "path")
    assert p is not None
    numbers = [
        float(x)
        for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", p.attrib["d"])
    ]
    assert len(numbers) % 2 == 0
    points = list(zip(numbers[::2], numbers[1::2]))
    return points[:-1] if points[0] == points[-1] else points


def main():
    pairs = read("results/later/pairs.csv")
    source = {
        (r["data_as_of"], r["geography_id"]): r for r in read("data/summary_rows.csv")
    }
    maps = json.loads((ROOT / "figures/value_map.json").read_text(encoding="utf-8"))
    vc = cc = hc = 0
    for fig in maps:
        tree = E.parse(ROOT / "figures" / (fig["figure"] + ".svg"))
        ids = {n.get("id"): n for n in tree.iter() if n.get("id")}
        area = vertices(ids["data-area-0"])
        left, right, top, bottom = (
            min(x for x, y in area),
            max(x for x, y in area),
            min(y for x, y in area),
            max(y for x, y in area),
        )
        for item in fig["items"]:
            node = ids[item["id"]]
            kind = item["kind"]
            if kind == "unit_change":
                start, end = item["transition"].split(" to ")
                rows = []
                for key in sorted({r["geography_id"] for r in pairs}):
                    old, new = source[start, key], source[end, key]
                    value = 100 * (F(new["total_units"]) / F(old["total_units"]) - 1)
                    rows.append((value, key))
                rows.sort()
                assert item["geography_order"] == [g for value, g in rows]
                assert [F(x) for x in item["values_exact"]] == [v for v, g in rows]
                vc += 51
                expected = [(float(v), i + 1) for i, (v, g) in enumerate(rows)]
                actual = vertices(node)
                assert fig["xlim"] == [-1, 5] and fig["ylim"] == [0, 52]
            elif kind == "component":
                group = [
                    r
                    for r in pairs
                    if r["transition"] == item["transition"]
                    and r["speed"] == item["speed"]
                ]
                assert len(group) == 51
                field = item["field"].removeprefix("mean_")
                value = sum(F(r[field]) for r in group) / 51
                assert F(item["value_exact"]) == value
                vc += 1
                transitions = sorted({r["transition"] for r in pairs})
                i = transitions.index(item["transition"]) * 2 + [
                    "speed_100_20",
                    "speed_25_3",
                ].index(item["speed"])
                j = [
                    "share_change_pp",
                    "numerator_component_pp",
                    "denominator_component_pp",
                ].index(field)
                x = i + (j - 1) * 0.23
                assert item["x"] == x and item["width"] == 0.21
                expected = [
                    (x - 0.105, 0),
                    (x + 0.105, 0),
                    (x + 0.105, float(value)),
                    (x - 0.105, float(value)),
                ]
                actual = vertices(node)
                assert fig["xlim"] == [-0.6, 3.6] and fig["ylim"] == [-0.9, 1.7]
            else:
                assert kind == "dc_marker"
                old, new = source["2024-12-31", "11"], source["2025-06-30", "11"]
                field = item["field"]
                value = (
                    F(old["total_units"]) * F(old[item["speed"]])
                    if field == "implied0"
                    else F(old["total_units"] if field == "n0" else new["total_units"])
                )
                assert F(item["value_exact"]) == value
                vc += 1
                y = ["speed_100_20", "speed_25_3"].index(item["speed"])
                assert item["y"] == y
                expected = [(float(value), y)]
                actual = [
                    (float(n.attrib["x"]), float(n.attrib["y"]))
                    for n in node.findall(".//" + SVG + "use")
                ]
                assert fig["xlim"] == [385600, 386300] and fig["ylim"] == [-0.45, 1.5]
                text = ("≈" if field == "implied0" else "") + f"{float(value):,.0f}"
                assert item["display"] == text and text in "".join(
                    tree.getroot().itertext()
                )
                vc += 1
            xmin, xmax = fig["xlim"]
            ymin, ymax = fig["ylim"]
            converted = [
                (
                    left + (x - xmin) / (xmax - xmin) * (right - left),
                    bottom - (y - ymin) / (ymax - ymin) * (bottom - top),
                )
                for x, y in expected
            ]
            assert len(actual) == len(converted), (
                item["id"],
                len(actual),
                len(converted),
            )
            for a, b in zip(actual, converted):
                assert max(abs(x - y) for x, y in zip(a, b)) < 0.00002, (
                    item["id"],
                    a,
                    b,
                )
                cc += 2
        for path, digest in fig["files"].items():
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
            hc += 1
    result = dict(
        status="PASS_SOURCE_VALUES_AND_ACTUAL_SVG_GEOMETRY",
        figures=3,
        value_checks=vc,
        coordinate_checks=cc,
        export_hash_checks=hc,
    )
    (ROOT / "figures/verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
