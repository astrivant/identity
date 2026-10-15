"""
Run the reviewed synthetic local-Git baseline before the PostgreSQL candidate using a disposable persistent-volume database.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.native.physical import ROOT, cluster


def main() -> int:
    """
    Own bounded experiment setup, exact pytest selection, raw logs and cleanup without touching real services.

    Returns:
        int: Zero after both trials complete; nonzero preserves failure evidence and never silently advances past a failed baseline.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for reviewed synthetic raw measurements")
    args = parser.parse_args()
    output: Path = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results: dict[str, object] = {
        "schema": 1,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "storage": "PostgreSQL persistent Docker volume and local Git filesystem; local fsync/WAL acceptance, no power-loss attestation",
        "order": ["git", "postgres"],
        "completed": [],
    }
    completed: list[str] = []
    result = 1
    try:
        with TemporaryDirectory(prefix="witful-benchmark-") as temporary, cluster(Path(temporary)) as drill:
            results["postgres_image"] = drill.image
            environment = {
                **os.environ,
                "WITFUL_TEST_DATABASE_URL": drill.connection("primary"),
                "WITFUL_NATIVE_BENCHMARK": "1",
                "WITFUL_NATIVE_EVIDENCE": str(output),
            }
            for backend in ("git", "postgres"):
                # An exact node ID avoids -k also matching the test function name and accidentally selecting the candidate first.
                node = f"tests/native/test_benchmark.py::test_registered_local_git_comparison[{backend}]"
                with (output / (backend + ".log")).open("wb") as log:
                    run = subprocess.run(
                        [sys.executable, "-m", "pytest", "-n", "0", node, "-q", "--tb=short"],
                        cwd=ROOT,
                        env=environment,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=600,
                        check=False,
                    )
                if run.returncode:
                    results["failed"] = backend
                    results["exit_code"] = run.returncode
                    return 1
                completed.append(backend)
            result = 0
            return 0
    finally:
        results["completed"] = completed
        results["complete"] = result == 0
        (output / "experiment.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
