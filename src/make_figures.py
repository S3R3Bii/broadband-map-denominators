"""Plot native-unit changes, exact accounting components and retained infeasibility."""

import csv, hashlib, json, shutil
from fractions import Fraction as F
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "svg.fonttype": "none",
        "path.simplify": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": "#233b49",
        "text.color": "#233b49",
        "axes.edgecolor": "#a5b2b7",
        "savefig.facecolor": "white",
    }
)
BLUE = "#235d72"
ORANGE = "#b65f27"
GREY = "#667782"


def read(path):
    return list(csv.DictReader((ROOT / path).open(encoding="utf-8")))


def finish(fig, ax, name, items):
    ax.patch.set_gid("data-area-0")
    for item in items:
        item.pop("artist").set_gid(item["id"])
    files = []
    for ext in ["pdf", "svg", "png"]:
        p = ROOT / "figures" / f"{name}.{ext}"
        fig.savefig(
            p,
            dpi=155 if ext == "png" else 100,
            metadata={"Date": None} if ext == "svg" else None,
        )
        if ext == "svg":
            p.write_bytes(
                (
                    "\n".join(
                        line.rstrip()
                        for line in p.read_text(encoding="utf-8").splitlines()
                    )
                    + "\n"
                ).encode()
            )
        files.append(p)
    shutil.copyfile(
        ROOT / "figures" / f"{name}.pdf", ROOT / "paper/images" / f"{name}.pdf"
    )
    entry = dict(
        figure=name,
        xlim=list(ax.get_xlim()),
        ylim=list(ax.get_ylim()),
        items=items,
        files={
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    )
    plt.close(fig)
    return entry


def main():
    pairs = read("results/later/pairs.csv")
    summaries = read("results/later/summary.csv")
    transitions = sorted({r["transition"] for r in pairs})
    maps = []
    fig, ax = plt.subplots(figsize=(8.5, 4.3))
    fig.subplots_adjust(left=0.10, right=0.97, bottom=0.18, top=0.80)
    items = []
    for i, (transition, color, label) in enumerate(
        zip(transitions, [BLUE, ORANGE], ["Jun–Dec 2024", "Dec 2024–Jun 2025"])
    ):
        rows = sorted(
            [
                r
                for r in pairs
                if r["transition"] == transition and r["speed"] == "speed_100_20"
            ],
            key=lambda r: (F(r["relative_unit_change"]), r["geography_id"]),
        )
        values = [100 * F(r["relative_unit_change"]) for r in rows]
        (line,) = ax.plot(
            list(map(float, values)),
            range(1, 52),
            lw=1.3,
            marker="o",
            ms=3,
            color=color,
            label=label,
        )
        items.append(
            dict(
                artist=line,
                id=f"unit-change-{i}",
                kind="unit_change",
                transition=transition,
                values_exact=list(map(str, values)),
                geography_order=[r["geography_id"] for r in rows],
            )
        )
    ax.axvline(0, color=GREY, lw=0.8)
    ax.set(
        xlim=(-1, 5),
        ylim=(0, 52),
        xlabel="Change in the published unit denominator (%)",
        ylabel="Rank among 51 states/DC (equal geography weight)",
    )
    ax.grid(alpha=0.15)
    ax.legend(frameon=False, loc="lower right")
    fig.suptitle(
        "Map-unit totals change across both later transitions",
        x=0.10,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.10,
        0.87,
        "One unit denominator per state/date; speed rows are not added together.",
        fontsize=9,
    )
    maps.append(finish(fig, ax, "unit_denominator_changes", items))
    fig, ax = plt.subplots(figsize=(10, 4.5))
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.20, top=0.70)
    items = []
    fields = [
        ("mean_share_change_pp", "Reported share change", BLUE),
        ("mean_numerator_component_pp", "Fraction-implied numerator", ORANGE),
        ("mean_denominator_component_pp", "Denominator", GREY),
    ]
    labels = []
    for i, (transition, speed) in enumerate(
        (t, s) for t in transitions for s in ["speed_100_20", "speed_25_3"]
    ):
        row = next(
            r
            for r in summaries
            if r["transition"] == transition and r["speed"] == speed
        )
        labels.append(
            ("Jun–Dec 2024" if i < 2 else "Dec 2024–Jun 2025")
            + "\n"
            + ("100/20" if speed == "speed_100_20" else "25/3")
            + " Mbps"
        )
        for j, (field, label, color) in enumerate(fields):
            value = F(row[field])
            x = i + (j - 1) * 0.23
            bar = ax.bar(
                x,
                float(value),
                width=0.21,
                color=color,
                label=label if i == 0 else None,
            )[0]
            ax.text(
                x,
                float(value) + (0.04 if value >= 0 else -0.04),
                f"{float(value):.3f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8,
            )
            items.append(
                dict(
                    artist=bar,
                    id=f"component-{i}-{j}",
                    kind="component",
                    transition=transition,
                    speed=speed,
                    field=field,
                    x=x,
                    width=0.21,
                    value_exact=str(value),
                )
            )
    ax.axhline(0, color=GREY, lw=0.7)
    ax.set(
        xlim=(-0.6, 3.6),
        ylim=(-0.9, 1.7),
        ylabel="Mean arithmetic component (percentage points)",
    )
    ax.set_xticks(range(4), labels)
    ax.grid(axis="y", alpha=0.14)
    ax.set_axisbelow(True)
    ax.legend(
        frameon=False,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.28),
        fontsize=9,
    )
    fig.suptitle(
        "Numerator and denominator components can offset",
        x=0.09,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.09,
        0.88,
        "Each group averages 51 state/DC comparisons. The components sum to the reported mean change.",
        fontsize=9,
    )
    maps.append(finish(fig, ax, "offsetting_components", items))
    fig, ax = plt.subplots(figsize=(10, 4.2))
    fig.subplots_adjust(left=0.14, right=0.97, bottom=0.23, top=0.72)
    items = []
    for yi, speed in enumerate(["speed_100_20", "speed_25_3"]):
        row = next(
            r
            for r in pairs
            if r["geography_id"] == "11"
            and r["start"] == "2024-12-31"
            and r["end"] == "2025-06-30"
            and r["speed"] == speed
        )
        assert row["counterfactual_status"] == "infeasible"
        for field, label, color, marker, offset in [
            ("n0", "Baseline unit total", GREY, "s", -0.15),
            ("implied0", "Baseline fraction-implied quantity", ORANGE, "D", 0.16),
            ("n1", "Later unit total", BLUE, "o", -0.15),
        ]:
            value = F(row[field])
            (point,) = ax.plot(
                [float(value)],
                [yi],
                linestyle="none",
                marker=marker,
                ms=7,
                color=color,
                label=label if yi == 0 else None,
            )
            text = ("≈" if field == "implied0" else "") + f"{float(value):,.0f}"
            ax.text(float(value), yi + offset, text, ha="center", fontsize=9)
            items.append(
                dict(
                    artist=point,
                    id=f"dc-{yi}-{field}",
                    kind="dc_marker",
                    speed=speed,
                    field=field,
                    y=yi,
                    value_exact=str(value),
                    display=text,
                )
            )
    ax.set(
        xlim=(385600, 386300),
        ylim=(-0.45, 1.5),
        xlabel="Aggregate map units (zoomed axis; markers, not bars)",
    )
    ax.set_yticks([0, 1], ["100/20 Mbps", "25/3 Mbps"])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:,.0f}"))
    ax.grid(axis="x", alpha=0.15)
    ax.legend(
        frameon=False,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.28),
        fontsize=8,
    )
    fig.suptitle(
        "A constant-count counterfactual can be infeasible",
        x=0.14,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.14,
        0.88,
        "District of Columbia, Dec 2024 to Jun 2025: baseline-implied quantities exceed the later unit total.",
        fontsize=9,
    )
    maps.append(finish(fig, ax, "infeasible_counterfactual", items))
    (ROOT / "figures/value_map.json").write_bytes(
        (json.dumps(maps, indent=2) + "\n").encode()
    )
    print("THREE_ORIGINAL_FIGURES_EXPORTED")


if __name__ == "__main__":
    main()
