"""
Keep merge protection tied to a complete, successful set of CI prerequisites.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
REQUIRED = (
    "codegraph",
    "distributions",
    "helm-properties",
    "learning",
    "lint",
    "native-physical",
    "orchestration",
    "privacy",
    "provider-contracts",
    "security",
    "tests",
    "views",
)


def gate_result(payload: str) -> int:
    """
    Exercise the same shell boundary used by GitHub Actions without network access.

    Args:
        payload (str): Serialized prerequisite results, including malformed cases.

    Returns:
        int: Shell exit status, with zero reserved for complete success.
    """
    return subprocess.run(
        ["bash", str(ROOT / "scripts/ci/checks/quality-gate.sh")],
        env={**os.environ, "NEEDS_JSON": payload},
        capture_output=True,
        check=False,
        timeout=10,
    ).returncode


def test_all_prerequisites_succeed() -> None:
    """
    Permit the merge gate only when every required producer succeeded.

    Returns:
        None: The complete success path passes.
    """
    assert gate_result(json.dumps({name: {"result": "success"} for name in REQUIRED})) == 0


@pytest.mark.parametrize("job_id", REQUIRED)
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_unsuccessful_prerequisite_blocks_merge(job_id: str, result: str) -> None:
    """
    Reject failure, cancellation and optional-skip leakage from every producer.

    Args:
        job_id (str): Required producer whose result changes.
        result (str): Non-success state supplied by GitHub Actions.

    Returns:
        None: The unsuccessful gate cannot permit a normal merge.
    """
    payload = {name: {"result": "success"} for name in REQUIRED}
    payload[job_id]["result"] = result
    assert gate_result(json.dumps(payload)) != 0


@pytest.mark.parametrize("payload", ["{}", "[]", "null", "invalid", "", '{"tests":{"result":"success"}}'])
def test_incomplete_or_malformed_results_block_merge(payload: str) -> None:
    """
    Reject empty, incomplete and malformed result sets rather than vacuous success.

    Args:
        payload (str): Invalid prerequisite payload.

    Returns:
        None: Every invalid boundary input fails.
    """
    assert gate_result(payload) != 0


def test_gate_matches_workflow_and_branch_policy() -> None:
    """
    Prevent settings drift, filtered PR triggers and silently omitted producers.

    Returns:
        None: The stable required check covers the entire validation graph.
    """
    # BaseLoader preserves GitHub's YAML key "on" instead of treating it as a YAML 1.1 boolean.
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    gate = jobs["quality-gate"]
    assert sorted(gate["needs"]) == list(REQUIRED)
    assert set(gate["needs"]) == set(jobs["publish"]["needs"])
    guard = "github.event_name != 'pull_request_target' && github.event_name != 'schedule'"
    assert all(name in jobs and jobs[name]["if"] == guard for name in REQUIRED)
    assert gate["if"] == "always() && " + guard
    assert workflow["on"]["pull_request"] == ""
    assert "main" in workflow["on"]["push"]["branches"]
    assert gate["steps"][-1]["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert gate["steps"][-1]["run"] == "bash scripts/ci/checks/quality-gate.sh"

    settings = yaml.safe_load((ROOT / ".github/settings.yml").read_text())
    policy = next(branch["protection"] for branch in settings["branches"] if branch["name"] == "main")
    assert policy["required_status_checks"] == {
        "strict": True,
        "checks": [{"context": gate["name"], "app_id": 15368}],
    }
    assert policy["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert policy["required_pull_request_reviews"]["dismiss_stale_reviews"] is True
    assert policy["enforce_admins"] is False
    assert policy["required_conversation_resolution"] is True
    assert policy["restrictions"] is None
    assert policy["allow_force_pushes"] is False
    assert policy["allow_deletions"] is False


def test_app_bound_checks_do_not_include_legacy_contexts() -> None:
    """
    Reject the mutually exclusive status-check fields refused by GitHub's API.

    Returns:
        None: The policy uses only the app-bound form of required status checks.
    """
    settings = yaml.safe_load((ROOT / ".github/settings.yml").read_text())
    for branch in settings["branches"]:
        checks = branch["protection"]["required_status_checks"]
        assert not {"contexts", "checks"}.issubset(checks)


def test_figure_publication_follows_both_current_run_producers() -> None:
    """
    Preserve synthetic figures when the coverage publisher changes implementation.

    Returns:
        None: Publication consumes both producers without selecting another run.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    publisher = jobs["coverage-badge"]
    assert set(publisher["needs"]) == {"tests", "learning"}
    assert "needs" not in jobs["learning"]
    downloads = {
        step["with"]["name"]: step["with"] for step in publisher["steps"] if step.get("uses", "").startswith("actions/download-artifact@")
    }
    assert set(downloads) == {"python-coverage", "continual-learning-example"}
    assert downloads["continual-learning-example"]["path"] == ".cache/coverage/badges/continual-learning"
    assert all("run-id" not in settings and "github-token" not in settings for settings in downloads.values())
    assert jobs["learning"]["steps"][-1]["with"]["name"] == "continual-learning-example"


def test_pr_and_tag_gate_tests_renewed_latest_contracts() -> None:
    """
    Refresh current upstream inputs before requiring their compatibility with the locked SDKs.

    Returns:
        None: Every caller tests renewed inputs; failures remain required and publication is restricted to passing main runs.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    gate = workflow["jobs"]["provider-contracts"]
    assert gate["with"] == {"source": "${{ github.sha }}"}
    stage = yaml.load((ROOT / ".github/workflows/stage-provider-contracts.yml").read_text(), Loader=yaml.BaseLoader)
    steps = stage["jobs"]["contracts"]["steps"]
    refresh = next(step for step in steps if "refresh.py --latest --observation" in step.get("run", ""))
    test = next(step for step in steps if step.get("run", "").startswith("pytest "))
    assert "if" not in refresh
    assert steps.index(refresh) < steps.index(test)
    assert "if" not in test and "continue-on-error" not in refresh and "continue-on-error" not in test
    assert "provider-contracts" in workflow["jobs"]["publish"]["needs"]
    publication = workflow["jobs"]["generated-updates"]
    assert publication["needs"] == ["quality-gate", "provider-contracts", "tests"]
    assert "needs.quality-gate.result == 'success'" in publication["if"]
    assert "needs.provider-contracts.result == 'success'" in publication["if"]
    assert "github.event_name == 'push'" in publication["if"]
    assert "github.ref == 'refs/heads/main'" in publication["if"]
    assert publication["permissions"] == {"contents": "write", "pull-requests": "write", "actions": "write"}
    download = next(step for step in publication["steps"] if "actions/download-artifact@" in step.get("uses", ""))
    assert download["with"] == {"name": "provider-contracts", "path": ".cache/provider-contracts/"}
    upload = next(step for step in steps if "actions/upload-artifact@" in step.get("uses", ""))
    assert upload["with"]["name"] == download["with"]["name"]
    assert "provider-contracts" not in workflow["jobs"]["tests"].get("needs", [])


def test_python_setup_selects_project_interpreter(tmp_path: Path) -> None:
    """
    Exercise the composite action path exports with GitHub's prepend ordering.

    Args:
        tmp_path (Path): Isolated runner checkout with separate tool and project bins.

    Returns:
        None: Direct Python calls select project dependencies rather than Poetry's environment.
    """
    action = yaml.safe_load((ROOT / ".github/actions/python/action.yml").read_text())
    step = next(step for step in action["runs"]["steps"] if step.get("name") == "Install current entry points")
    project = tmp_path / ".venv/bin"
    tooling = tmp_path / ".cache/poetry-cli/bin"
    project.mkdir(parents=True)
    tooling.mkdir(parents=True)
    (project / "python").symlink_to(sys.executable)
    (tooling / "python").symlink_to(sys.executable)
    # Installation is outside this regression; execute the actual export script unchanged.
    (tooling / "poetry").symlink_to(shutil.which("true") or "/usr/bin/true")
    path_file, env_file = tmp_path / "path", tmp_path / "environment"
    subprocess.run(
        ["bash", "-eu", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_PATH": str(path_file), "GITHUB_ENV": str(env_file)},
        check=True,
        timeout=10,
    )
    runner_path = os.pathsep.join([*reversed(path_file.read_text().splitlines()), os.environ["PATH"]])
    assert shutil.which("python", path=runner_path) == str(project / "python")
    assert f"VIRTUAL_ENV={tmp_path}/.venv" in env_file.read_text().splitlines()


def test_adaptive_matrix_preserves_required_gates_and_main_only_feedback() -> None:
    """
    Keep independent source checks parallel while complete test fan-in gates feedback publication.

    Returns:
        None: Failed shards cannot be masked; forks, PRs and tags cannot train shared state.
    """
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    stage = yaml.load((ROOT / ".github/workflows/stage-tests.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow["jobs"]["tests"]["uses"] == "./.github/workflows/stage-tests.yml"
    assert "needs" not in workflow["jobs"]["lint"]
    assert stage["jobs"]["worker"]["strategy"]["fail-fast"] == "false"
    assert stage["jobs"]["aggregate"]["needs"] == ["plan", "worker"]
    assert "if" not in stage["jobs"]["aggregate"]
    assert stage["permissions"] == {"contents": "read"}
    publisher = workflow["jobs"]["generated-updates"]
    assert "github.event_name == 'push'" in publisher["if"] and "refs/heads/main" in publisher["if"]
    for step in publisher["steps"]:
        if "actions/cache/save@" in step.get("uses", "") or "publish-tests.mjs" in step.get("with", {}).get("script", ""):
            assert step["if"] == "needs.tests.outputs.capture == 'true'"
    assert not any("actions/cache/save@" in step.get("uses", "") for job in stage["jobs"].values() for step in job["steps"])
