"""Write/verify portable result hashes without changing immutable raw files.

Git checks text out as CRLF on Windows and LF on Linux. Hash CSV/JSON after
CRLF-to-LF canonicalization; hash figure binaries verbatim.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments/results/MANIFEST.sha256"


def artifact_digest(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix in (".csv", ".json"):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def artifacts():
    patterns = ("experiments/results/raw/*.csv", "experiments/results/summary/*.csv",
                "experiments/results/summary/*.json", "experiments/results/diagnostics/*.json",
                "experiments/figures/*.png", "experiments/figures/*.pdf")
    return sorted({path for pattern in patterns for path in ROOT.glob(pattern)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("write", "verify"))
    args = parser.parse_args()
    paths = artifacts()
    actual = {str(path.relative_to(ROOT).as_posix()): artifact_digest(path) for path in paths}
    if args.action == "write":
        lines = ["# CSV/JSON hashes canonicalize CRLF to LF; binary hashes are verbatim.",
                 "# Verify with: python experiments/artifact_manifest.py verify"]
        lines += [f"{digest}  {path}" for path, digest in actual.items()]
        MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {len(actual)} artifact hashes to experiments/results/MANIFEST.sha256")
    else:
        expected = {}
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            digest, path = line.split("  ", 1)
            if path in expected:
                raise RuntimeError(f"Duplicate manifest entry: {path}")
            expected[path] = digest
        if actual != expected:
            changed = sorted(path for path in actual.keys() | expected.keys()
                             if actual.get(path) != expected.get(path))
            raise RuntimeError(f"Artifact manifest mismatch: {changed}")
        print(f"manifest verification passed: {len(actual)} artifacts (LF-canonical text; verbatim binaries)")


if __name__ == "__main__":
    main()
