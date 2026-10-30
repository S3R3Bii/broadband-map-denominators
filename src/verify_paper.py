"""Recompute every source-bound display and check the actual six-page PDF."""

import ast, csv, hashlib, json, re, unicodedata
from fractions import Fraction as F
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return list(csv.DictReader((ROOT / path).open(encoding="utf-8")))


def main():
    pdf = ROOT / "paper/manuscript.pdf"
    reader = PdfReader(pdf)
    assert len(reader.pages) == 6, len(reader.pages)
    pages = [unicodedata.normalize("NFKC", p.extract_text()) for p in reader.pages]
    assert all(len(p) > 900 for p in pages)
    ledger = json.loads(
        (ROOT / "paper/display_ledger.json").read_text(encoding="utf-8")
    )
    checks = 2
    for item in ledger:
        q = item["query"]
        kind = q["kind"]
        if kind == "summary":
            value = F(
                next(
                    r
                    for r in read("results/" + q["phase"] + "/summary.csv")
                    if r["transition"] == q["transition"] and r["speed"] == q["speed"]
                )[q["field"]]
            )
        elif kind == "json":
            value = json.loads((ROOT / q["path"]).read_text(encoding="utf-8"))[
                q["field"]
            ]
        elif kind == "freeze_count":
            value = len(
                json.loads(
                    (ROOT / "data/dependency_freeze.json").read_text(encoding="utf-8")
                )["files"]
            )
        elif kind == "test_count":
            value = sum(
                1
                for p in (ROOT / "tests").glob("test_*.py")
                for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
            )
        elif kind == "coverage":
            value = F(
                next(
                    r for r in read("data/coverage.csv") if r["data_as_of"] == q["date"]
                )[q["field"]]
            )
        else:
            assert kind == "example"
            value = (
                F(
                    next(
                        r
                        for r in read("results/later/pairs.csv")
                        if r["geography_id"] == q["geography_id"]
                        and r["start"] == q["start"]
                        and r["speed"] == q["speed"]
                    )[q["field"]]
                )
                * q["multiplier"]
            )
        expected = (
            format(int(value), item["format"])
            if item["format"] == ",d"
            else format(float(value), item["format"])
        )
        assert expected == item["text"]
        assert expected in pages[item["page"]], item
        checks += 2
    # PDF extraction wraps the authored compound "formal-publication" after its hyphen.
    text = re.sub(r"\s+", " ", re.sub(r"-[ \t]*\n[ \t]*", "-", " ".join(pages)))
    for phrase in [
        "not causal effects",
        "fraction-implied quantities",
        "not exact observed integer",
        "not a native rounding bound",
        "No cause is identified",
        "No model",
        "not a confidence interval",
        "formal-publication projects",
    ]:
        assert phrase in text, phrase
        checks += 1
    buildpath = ROOT / "paper/build_receipt.json"
    if buildpath.exists():
        build = json.loads(buildpath.read_text(encoding="utf-8"))
        assert build["status"] == "PASS_COMPILE_AND_SIX_PAGE_VISUAL_REVIEW"
        for name, digest in build["artifact_sha256"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
            checks += 1
        warnings = build["layout_warnings"]
        assert not warnings
        if (ROOT / "paper/main.log").exists():
            assert (
                hashlib.sha256((ROOT / "paper/main.log").read_bytes()).hexdigest()
                == build["private_log_sha256"]
            )
    else:
        log = (ROOT / "paper/main.log").read_text(encoding="utf-8", errors="replace")
        warnings = [
            l
            for l in log.splitlines()
            if any(
                w in l
                for w in ["Overfull", "Underfull", "Missing character", "Unused global"]
            )
        ]
        assert not warnings, warnings
    checks += 1
    result = dict(
        status="PASS_SOURCE_BOUND_DISPLAYS_AND_PDF_TEXT",
        pages=6,
        displays=len(ledger),
        checks=checks,
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        layout_warnings=warnings,
        visual_inspection="Separate recorded page inspection required",
    )
    (ROOT / "paper/verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
