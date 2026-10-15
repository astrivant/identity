"""
Prove redaction, staged-source ownership, and known detector boundaries with synthetic inputs.
"""

from __future__ import annotations

import base64
import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from witful.collection.models import CONFIG, Config
from witful.knowledge.contracts import as_data
from witful.privacy.cli import main
from witful.privacy.scanner import scan, scan_report, scan_text

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture


@pytest.mark.parametrize(
    "text,rule",
    [
        ("sample" + "@" + "synthetic-company.dev", "email"),
        ("/Users/" + "synthetic-owner/project", "personal-home"),
        ("C:\\Users\\" + "synthetic-owner\\project", "personal-home"),
        ("555" + "-010-1234", "phone"),
        ("123" + "-45-6789", "government-id"),
        ("https://www.linkedin.com/" + "in/synthetic-member", "profile-url"),
        ("-----BEGIN " + "PRIVATE KEY-----", "private-key"),
    ],
)
def test_known_patterns(text: str, rule: str) -> None:
    """
    Recognize each declared detector without storing real personal fixtures.

    Args:
        text (str): Constructed synthetic pattern instance.
        rule (str): Expected detector identifier.

    Returns:
        None: Findings preserve the correct line and contain no matched value.
    """
    assert (2, rule) in scan_text("header\n" + text)
    assert text not in repr(scan_text(text))


def test_explicit_literals_and_safe_examples() -> None:
    """
    Accept documented synthetic domains while applying private deny terms consistently.

    Returns:
        None: Literal checks are case-insensitive and regex syntax is not interpreted.
    """
    assert scan_text("sample@example.org /home/runner/work") == ()
    assert scan_text("git@github.com:example/repository.git") == ()
    assert scan_text("member" + "@github.com") == ((1, "email"),)
    assert scan_text("Some Private Literal", ["private literal"]) == ((1, "deny-term"),)
    assert scan_text("abc", ["a.*"]) == ()


def test_scan_uses_exact_index_and_redacts_sensitive_paths(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Prevent unstaged replacements from hiding staged findings and avoid disclosing filename matches.

    Args:
        tmp_path (Path): Temporary Git checkout.
        capsys (CaptureFixture[str]): Redacted CLI output capture.

    Returns:
        None: The index and worktree are scanned independently and unsupported content is not a finding.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "fixture.txt"
    path.write_text("a synthetic forbidden literal\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "fixture.txt"], check=True)
    path.write_text("clean unstaged replacement\n")
    assert scan(tmp_path, terms=["forbidden literal"]) == ()
    assert scan(tmp_path, staged=True, terms=["forbidden literal"])[0].rule == "deny-term"

    secret_name = "forbidden" + "-filename.txt"
    (tmp_path / secret_name).write_text("clean\n")
    findings = scan(tmp_path, terms=["forbidden"])
    assert findings[0].path.startswith("path-sha256:")
    assert secret_name not in repr(findings)
    (tmp_path / "opaque.bin").write_bytes(b"\0\xff")
    assert scan(tmp_path) == ()
    assert scan_report(tmp_path).skipped[0].reason == "binary-content"
    assert main(["scan", "--repo", str(tmp_path)]) == 0
    assert "forbidden literal" not in capsys.readouterr().out


def test_symlinks_do_not_read_outside_the_repository(tmp_path: Path) -> None:
    """
    Read link text while avoiding traversal into unrelated private files.

    Args:
        tmp_path (Path): Temporary checkout and external test file owner.

    Returns:
        None: External contents are not scanned or exposed through a symlink.
    """
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    external = tmp_path / "outside.txt"
    external.write_text("forbidden sentinel")
    (root / "link").symlink_to(external)
    assert scan(root, terms=["forbidden sentinel"]) == ()


def test_managed_file_policy_comes_from_the_scanned_snapshot(tmp_path: Path) -> None:
    """
    Prevent an unstaged configuration edit from bypassing staged envelope validation.

    Args:
        tmp_path (Path): Synthetic Git index and distinct working configuration.

    Returns:
        None: The registered staged file still requires an envelope after an unstaged removal.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".config").mkdir()
    (tmp_path / "collection/files").mkdir(parents=True)
    config = Config("example/collection", "a" * 64, "b" * 64, managed_files=("export-01",))
    (tmp_path / CONFIG).write_text(json.dumps(as_data(config)))
    relative = "collection/files/export-01.enc.json"
    (tmp_path / relative).write_text("not an encrypted envelope")
    subprocess.run(["git", "-C", str(tmp_path), "add", CONFIG, relative], check=True)
    (tmp_path / CONFIG).write_text(json.dumps(as_data(Config("example/collection", "a" * 64, "b" * 64))))
    assert scan(tmp_path) == ()
    report = scan_report(tmp_path, staged=True)
    assert report.findings == ()
    assert [(item.path, item.reason) for item in report.errors] == [(relative, "invalid-envelope")]
    with pytest.raises(ValueError, match="file inspection failed"):
        scan(tmp_path, staged=True)
    assert main(["scan", "--repo", str(tmp_path), "--staged"]) == 2


@pytest.mark.parametrize(
    "name,data,reason",
    [
        ("asset.png", b"\x89PNG\r\n\x1a\n\0payload", "binary-content"),
        ("asset.dat", b"\xff\xfe", "non-utf8-content"),
        ("source.txt", b"\0binary despite extension", "binary-content"),
    ],
)
def test_unsupported_content_is_reported_without_a_finding(
    tmp_path: Path, capsys: CaptureFixture[str], name: str, data: bytes, reason: str
) -> None:
    """
    Keep unsupported payloads visible without asserting that their contents contain PII.

    Args:
        tmp_path (Path): Disposable repository.
        capsys (CaptureFixture[str]): JSON-lines output capture.
        name (str): Asset filename, independent of content classification.
        data (bytes): Synthetic unsupported payload.
        reason (str): Expected coverage explanation.

    Returns:
        None: Default scans pass, strict scans fail coverage, and neither emits a false finding.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / name).write_bytes(data)
    assert main(["scan", "--repo", str(tmp_path)]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records == [
        {"status": "skipped", "path": name, "reason": reason},
        {"findings": 0, "skipped": 1, "errors": 0, "complete": False},
    ]
    assert main(["scan", "--repo", str(tmp_path), "--require-complete"]) == 2
    report = scan_report(tmp_path)
    assert report.findings == ()
    assert report.errors == ()
    assert not report.complete


def test_actual_matches_and_staged_content_still_fail(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Detect text disguised as an image and preserve default and strict status precedence.

    Args:
        tmp_path (Path): Disposable index and differing working tree.
        capsys (CaptureFixture[str]): Diagnostic output capture.

    Returns:
        None: Extension-based bypasses and unstaged binary replacements cannot conceal indexed matches.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "disguised.png"
    path.write_text("sample" + "@" + "synthetic-company.dev")
    subprocess.run(["git", "-C", str(tmp_path), "add", path.name], check=True)
    assert main(["scan", "--repo", str(tmp_path)]) == 1
    path.write_bytes(b"\0opaque")
    assert main(["scan", "--repo", str(tmp_path)]) == 0
    assert main(["scan", "--repo", str(tmp_path), "--staged"]) == 1
    report = scan_report(tmp_path, staged=True)
    assert report.complete
    assert report.findings[0].rule == "email"
    (tmp_path / "other.txt").write_text("sample" + "@" + "synthetic-company.dev")
    assert main(["scan", "--repo", str(tmp_path)]) == 1
    assert main(["scan", "--repo", str(tmp_path), "--require-complete"]) == 2
    assert "synthetic-company.dev" not in capsys.readouterr().out


def test_sensitive_binary_names_are_redacted_everywhere(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Protect filenames in coverage records as well as pattern findings.

    Args:
        tmp_path (Path): Disposable repository.
        capsys (CaptureFixture[str]): Output capture for sensitive-name checks.

    Returns:
        None: Both public records use the same digest without disclosing the supplied literal.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    name = "sample" + "@" + "synthetic-company.dev.png"
    (tmp_path / name).write_bytes(b"\0binary")
    report = scan_report(tmp_path)
    assert report.findings[0].path == report.skipped[0].path
    assert report.skipped[0].path.startswith("path-sha256:")
    assert main(["scan", "--repo", str(tmp_path)]) == 1
    assert name not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["missing", "oversized"])
def test_inspection_errors_are_not_findings(tmp_path: Path, capsys: CaptureFixture[str], failure: str) -> None:
    """
    Fail the scan when source cannot be inspected without asserting a personal-data match.

    Args:
        tmp_path (Path): Disposable repository with a tracked source.
        capsys (CaptureFixture[str]): Summary and diagnostics capture.
        failure (str): Inspection failure to induce independently of permissions.

    Returns:
        None: Inspection errors take precedence over findings and remain visible in the summary.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "source.txt"
    path.write_text("clear")
    subprocess.run(["git", "-C", str(tmp_path), "add", path.name], check=True)
    if failure == "missing":
        path.unlink()
    else:
        path.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    report = scan_report(tmp_path)
    assert report.findings == ()
    assert report.skipped == ()
    assert report.errors[0].reason == ("read-error" if failure == "missing" else "file-too-large")
    assert not report.complete
    assert main(["scan", "--repo", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == {
        "findings": 0,
        "skipped": 0,
        "errors": 1,
        "complete": False,
    }
    (tmp_path / "match.txt").write_text("sample" + "@" + "synthetic-company.dev")
    assert main(["scan", "--repo", str(tmp_path)]) == 2
    with pytest.raises(ValueError, match="file inspection failed"):
        scan(tmp_path)
    # The intact staged text remains scannable despite the failed working-tree inspection.
    assert scan_report(tmp_path, staged=True).complete


def test_valid_envelope_is_validated_but_not_scanned(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Distinguish transport schema validation from personal-data inspection of plaintext.

    Args:
        tmp_path (Path): Disposable repository with a synthetic envelope.
        capsys (CaptureFixture[str]): Diagnostic capture.

    Returns:
        None: Valid transport is explicitly skipped; invalid transport fails with no invented finding.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "collection/sources.enc.json"
    path.parent.mkdir()
    envelope = {
        "version": 1,
        "repository": "example/collection",
        "purpose": "sources",
        "encryption_fingerprint": "a" * 64,
        "wrapped_key": base64.b64encode(b"k" * 384).decode(),
        "nonce": base64.b64encode(b"n" * 12).decode(),
        "ciphertext": base64.b64encode(b"c" * 16).decode(),
    }
    path.write_text(json.dumps(envelope))
    report = scan_report(tmp_path)
    assert report.findings == ()
    assert report.errors == ()
    assert report.skipped[0].reason == "encrypted-envelope"
    assert not report.complete
    assert main(["scan", "--repo", str(tmp_path)]) == 0
    assert main(["scan", "--repo", str(tmp_path), "--require-complete"]) == 2
    envelope["nonce"] = "invalid"
    path.write_text(json.dumps(envelope))
    assert main(["scan", "--repo", str(tmp_path)]) == 2
    report = scan_report(tmp_path)
    assert report.findings == ()
    assert report.skipped == ()
    assert report.errors[0].reason == "invalid-envelope"
    assert "ciphertext" not in capsys.readouterr().out


def test_empty_and_selected_text_scopes_are_complete(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Describe coverage of the selected scope and retain safe invalid-selection diagnostics.

    Args:
        tmp_path (Path): Empty then mixed-content repository.
        capsys (CaptureFixture[str]): CLI output and stderr capture.

    Returns:
        None: Unselected binary content does not affect text-only coverage.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert scan_report(tmp_path).complete
    (tmp_path / "source.txt").write_text("synthetic source\n")
    (tmp_path / "opaque.bin").write_bytes(b"\0binary")
    assert scan_report(tmp_path, paths=["source.txt"]).complete
    assert main(["scan", "source.txt", "--repo", str(tmp_path), "--require-complete"]) == 0
    with pytest.raises(SystemExit) as error:
        main(["scan", "absent.txt", "--repo", str(tmp_path)])
    assert error.value.code == 2
    assert "absent.txt" not in capsys.readouterr().err


@pytest.mark.parametrize("staged", [False, True])
@pytest.mark.parametrize("invalid", [{"private": "synthetic-config-canary"}, {"repository": ["synthetic-config-canary"]}])
def test_invalid_configuration_is_redacted(tmp_path: Path, capsys: CaptureFixture[str], staged: bool, invalid: dict[str, object]) -> None:
    """
    Keep schema-invalid collection configuration out of CLI tracebacks and diagnostics.

    Args:
        tmp_path (Path): Disposable repository containing only synthetic configuration.
        capsys (CaptureFixture[str]): Captured public diagnostic streams.
        staged (bool): Select the index or working snapshot.
        invalid (dict[str, object]): Valid JSON that violates the collection schema.

    Returns:
        None: Validation exits with a bounded error and does not disclose the input.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / CONFIG
    path.parent.mkdir()
    path.write_text(json.dumps(invalid))
    subprocess.run(["git", "-C", str(tmp_path), "add", CONFIG], check=True)
    arguments = ["scan", "--repo", str(tmp_path)] + (["--staged"] if staged else [])
    with pytest.raises(SystemExit) as rejected:
        main(arguments)
    assert rejected.value.code == 2
    captured = capsys.readouterr()
    assert "synthetic-config-canary" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert "PII scan incomplete" in captured.err


def test_npm_namespace_paths_do_not_hide_real_email_or_deny_terms() -> None:
    """
    Distinguish npm scope syntax from personal email without exempting a lockfile or its neighboring metadata.

    Returns:
        None: Recognized registry/package paths pass, while actual emails, unrelated URL credentials and explicit deny terms still fail.
    """
    namespace = "@" + "example.scope/package"
    references = (
        '"node_modules/' + namespace + '": {"version": "1.0.0"}',
        '"resolved": "https://registry.npmjs.org/' + namespace + '/-/package-1.0.0.tgz"',
    )
    for reference in references:
        assert scan_text(reference) == ()
        assert scan_text(reference, ["example.scope"]) == ((1, "deny-term"),)
        assert scan_text(reference + '\n"author": "person' + '@company.dev"') == ((2, "email"),)
    assert scan_text("node_modules/person" + "@company.dev/package") == ((1, "email"),)
    assert scan_text("https://person" + "@registry.npmjs.org/package") == ((1, "email"),)
    assert scan_text("https://elsewhere.invalid/" + namespace) == ((1, "email"),)
