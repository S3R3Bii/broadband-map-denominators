"""Replay exact exports in a full-history clone, without fetching or replacing sources."""

import csv, hashlib, json, platform, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    originals = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(n in p.parts for n in [".git", "__pycache__", "rendered"])
        and p.name != "reproduction.json"
        and p.suffix not in [".log", ".aux", ".out", ".xdv"]
    }
    fields = documents = 0
    with tempfile.TemporaryDirectory(prefix="broadband-denominator-replay-") as temp:
        folder = Path(temp)
        clone = folder / "study"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(clone)],
            check=True,
        )

        def run(*args):
            r = subprocess.run(
                [sys.executable, *args], cwd=clone, capture_output=True, text=True
            )
            if r.returncode:
                raise RuntimeError(
                    str(args) + "\n" + r.stdout[-1500:] + "\n" + r.stderr[-1500:]
                )
            return r.stdout

        proof = json.loads(run("src/freeze_proof.py"))
        assert proof["files"] == 32
        run("-m", "unittest", "discover", "-s", "tests")
        for phase in ["development", "later"]:
            out = folder / phase
            run("src/analyze.py", "--phase", phase, "--out", str(out))
            run("src/verify_results.py", "--results", str(out))
            for name in ["pairs", "sensitivity", "bounds", "summary"]:
                with (ROOT / "results" / phase / (name + ".csv")).open(
                    encoding="utf-8", newline=""
                ) as a, (out / (name + ".csv")).open(encoding="utf-8", newline="") as b:
                    for x, y in zip(csv.reader(a), csv.reader(b), strict=True):
                        assert x == y, name
                        fields += len(x)
            for name in ["execution", "verification"]:
                assert json.loads(
                    (ROOT / "results" / phase / (name + ".json")).read_text(
                        encoding="utf-8"
                    )
                ) == json.loads((out / (name + ".json")).read_text(encoding="utf-8"))
                documents += 1
        denominator = json.loads(
            run(
                "src/cli.py",
                "examples/baseline-authored.json",
                "examples/denominator-only-authored.json",
            )
        )
        numerator = json.loads(
            run(
                "src/cli.py",
                "examples/baseline-authored.json",
                "examples/numerator-only-authored.json",
            )
        )
        assert denominator["status"] == numerator["status"] == "available"
        assert denominator["share_change_pp"] == numerator["share_change_pp"] == "10"
        assert (
            denominator["numerator_component_pp"]
            == numerator["denominator_component_pp"]
            == "0"
        )
        assert (
            denominator["denominator_component_pp"]
            == numerator["numerator_component_pp"]
            == "10"
        )
    after = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in originals
    }
    assert after == originals
    result = dict(
        status="PASS",
        python=platform.python_version(),
        csv_fields_compared=fields,
        json_documents_compared=documents,
        fixtures=42,
        frozen_dependencies=32,
        source_network=False,
        original_files_unchanged=True,
        full_history_clone=True,
        cli_examples=2,
    )
    (ROOT / "results/reproduction.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
