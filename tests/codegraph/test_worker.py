"""
Verify the actual locked CodeGraph SDK inside its no-network disposable runtime.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from witful.codegraph.snapshot import capture
from witful.codegraph.worker import extract

from tests.codegraph.support import repository

if TYPE_CHECKING:
    from pathlib import Path


def test_real_sdk(tmp_path: Path) -> None:
    """
    Exercise the pinned SDK against real source without mocking its responses.

    Args:
        tmp_path (Path): Disposable public synthetic fixture.

    Returns:
        None: The isolated upstream SDK returns qualified caller evidence.
    """
    image = os.environ.get("WITFUL_CODEGRAPH_IMAGE")
    if not image:
        pytest.skip("WITFUL_CODEGRAPH_IMAGE is required by the separate SDK compatibility CI job")
    enrollment, revision = repository(tmp_path / "source")
    enrollment = evolve(enrollment, image=image)
    result = extract(enrollment, capture(enrollment, revision))
    names = {node.id: node.name for node in result.nodes}
    assert {"leaf", "caller"} <= set(names.values())
    assert any(names[edge.source] == "caller" and names[edge.target] == "leaf" for edge in result.edges)
    assert not (tmp_path / "source/.codegraph").exists()


def test_real_sdk_languages_and_inert_configuration(tmp_path: Path) -> None:
    """
    Exercise mixed language detection, custom suffixes and explicit omissions through the real SDK.

    Args:
        tmp_path (Path): Disposable synthetic source only.

    Returns:
        None: Upstream detection supplies complete coverage without honoring repository-owned SDK controls.
    """
    import json

    from witful.codegraph.models import Extension

    from tests.codegraph.support import command

    image = os.environ.get("WITFUL_CODEGRAPH_IMAGE")
    if not image:
        pytest.skip("WITFUL_CODEGRAPH_IMAGE is required by the SDK compatibility job")
    root = tmp_path / "source"
    enrollment, _ = repository(root)
    fixtures = {
        "sample.ts": "export function leaf(): number { return 1; }\nexport function caller(): number { return leaf(); }\n",
        "sample.js": "function leaf() { return 1; }\nfunction caller() { return leaf(); }\n",
        "Sample.java": "class Sample { int leaf() { return 1; } int caller() { return leaf(); } }\n",
        "sample.go": "package sample\nfunc leaf() int { return 1 }\nfunc caller() int { return leaf() }\n",
        "sample.rs": "fn leaf() -> i32 { 1 }\nfn caller() -> i32 { leaf() }\n",
        "sample.c": "int leaf(void) { return 1; }\nint caller(void) { return leaf(); }\n",
        "sample.cpp": "class Sample { public: int leaf() { return 1; } int caller() { return leaf(); } };\n",
        "Sample.cs": "class Sample { int Leaf() { return 1; } int Caller() { return Leaf(); } }\n",
        "sample.tf": 'variable "sample" { type = string }\n',
        "config.yaml": "sample: value\n",
        "sample.custom": "function leaf() { return 1; }\n",
        "codegraph.json": json.dumps({"exclude": ["**"], "extensions": {".py": "java"}}),
        ".gitignore": "*.ts\n",
        "node_modules/ignored.js": "function ignored() { return 1; }\n",
        "conf/routes": "GET /sample controllers.Sample.index\n",
        "sample.app.src": '{application, sample, [{description, "sample"}, {vsn, "1"}]}.\n',
    }
    for name, text in fixtures.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
    command(root, "add", "--force", ".")
    command(root, "commit", "-m", "Synthetic mixed language sources")
    revision = command(root, "rev-parse", "HEAD")
    enrollment = evolve(
        enrollment, image=image, profile="sdk", seconds=180, memory_mb=1024, extensions=(Extension(".custom", "javascript"),)
    )
    snapshot = capture(enrollment, revision)
    result = extract(enrollment, snapshot)
    coverage = {item.path: item for item in result.files}
    assert set(coverage) == {source.path for source in snapshot.sources}
    for name, language in {
        "sample.py": "python",
        "sample.ts": "typescript",
        "sample.js": "javascript",
        "Sample.java": "java",
        "sample.go": "go",
        "sample.rs": "rust",
        "sample.c": "c",
        "sample.cpp": "cpp",
        "Sample.cs": "csharp",
        "sample.tf": "terraform",
        "sample.custom": "javascript",
        "sample.app.src": "erlang",
    }.items():
        assert coverage[name].language == language
        assert coverage[name].coverage == "indexed"
        assert any(node.path == name for node in result.nodes)
    assert coverage["config.yaml"].coverage == "file-only"
    assert coverage["conf/routes"].language == "yaml"
    assert coverage["codegraph.json"].coverage == "worker-control"
    assert coverage[".gitignore"].coverage == "worker-control"
    assert coverage["node_modules/ignored.js"].coverage == "sdk-omitted"
    assert coverage["README.md"].coverage == "unsupported"
    assert not (root / ".codegraph").exists()


def test_every_advertised_sdk_language_loads(tmp_path: Path) -> None:
    """
    Discover the SDK registry at runtime and exercise every advertised language without a local whitelist.

    Args:
        tmp_path (Path): Disposable synthetic empty-language corpus.

    Returns:
        None: Every current upstream language accepts an explicit suffix and completes extraction.
    """
    import json
    import subprocess

    from witful.codegraph.models import Extension

    from tests.codegraph.support import command

    image = os.environ.get("WITFUL_CODEGRAPH_IMAGE")
    if not image:
        pytest.skip("WITFUL_CODEGRAPH_IMAGE is required by the SDK compatibility job")
    capabilities = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--log-driver=none",
            "--memory=256m",
            "--memory-swap=256m",
            "-i",
            image,
            "node",
            "/opt/codegraph/worker.mjs",
        ],
        input=b'{"operation":"capabilities"}',
        capture_output=True,
        check=True,
        timeout=30,
    )
    languages = json.loads(capabilities.stdout)["languages"]
    assert len(languages) > 1 and "python" in languages
    root = tmp_path / "source"
    enrollment, _ = repository(root)
    extensions = tuple(Extension(".witful_" + language, language) for language in languages)
    for extension in extensions:
        (root / ("sample" + extension.suffix)).write_text("")
    command(root, "add", ".")
    command(root, "commit", "-m", "Synthetic upstream language registry corpus")
    enrollment = evolve(enrollment, image=image, profile="sdk", seconds=240, memory_mb=2048, extensions=extensions)
    result = extract(enrollment, capture(enrollment, command(root, "rev-parse", "HEAD")))
    records = {item.path: item for item in result.files}
    for extension in extensions:
        item = records["sample" + extension.suffix]
        assert item.language == extension.language
        assert item.coverage in {"indexed", "file-only"}
