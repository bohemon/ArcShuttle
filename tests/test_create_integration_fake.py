from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from arcshuttle.config import Config
from arcshuttle.manifest import validate_manifest
from arcshuttle.operations.create import make_create_plan
from arcshuttle.runner import execute_manifest
from arcshuttle.sevenzip import SevenZip


def fake_runner() -> SevenZip:
    script = Path(__file__).with_name("fake7z.py")
    return SevenZip(Path(sys.executable), command_prefix=(str(script),))


def config(root: Path) -> Config:
    return replace(
        Config(),
        output_dir=root / "output",
        log_dir=root / "logs",
        small_threshold=0,
        cpu_budget=3,
        heavy_threads=3,
        max_processes=1,
        io_slots=1,
        quiet=True,
    )


@pytest.mark.parametrize("source_kind", ["file", "directory"])
@pytest.mark.parametrize(
    ("archive_format", "method_switch"),
    [("7z", "-m0=LZMA2"), ("zip", "-mm=Deflate")],
)
@pytest.mark.parametrize("compression_level", [0, 9])
def test_fake7z_create_uses_relative_source_and_verifies_without_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
    archive_format: str,
    method_switch: str,
    compression_level: int,
) -> None:
    source = tmp_path / ("file with space.dat" if source_kind == "file" else "directory with space")
    if source_kind == "file":
        source.write_bytes(b"source")
    else:
        (source / "nested" / "empty").mkdir(parents=True)
        (source / "payload.txt").write_text("payload", encoding="utf-8")
    fake_config = tmp_path / "fake-config.json"
    fake_config.write_text("{}", encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE7Z_CONFIG", str(fake_config))
    monkeypatch.setenv("FAKE7Z_STATE", str(state))
    resolved = replace(
        config(tmp_path),
        create_format=archive_format,
        compression_level=compression_level,
    )
    job = validate_manifest(make_create_plan([source], resolved).jobs, resolved)[0]

    results, _, code = execute_manifest([job], resolved, fake_runner())

    assert (code, results[0]["status"]) == (0, "success")
    assert Path(results[0]["output_dir"]).is_file()
    create_state = json.loads(next(state.glob("a-*.json")).read_text(encoding="utf-8"))
    test_state = json.loads(next(state.glob("t-*.json")).read_text(encoding="utf-8"))
    assert create_state["source_argument"] == (source.name if source_kind == "file" else ".")
    assert create_state["cwd"] == str(source.parent if source_kind == "file" else source)
    expected_threads = 1 if compression_level == 0 else 3
    assert f"-mmt={expected_threads}" in create_state["args"]
    assert f"-mx={compression_level}" in create_state["args"]
    if compression_level == 0:
        assert not any(argument.startswith(("-m0=", "-mm=")) for argument in create_state["args"])
    else:
        assert method_switch in create_state["args"]
    assert not any(argument.startswith("-p") for argument in create_state["args"])
    assert Path(create_state["args"][create_state["args"].index("--") + 1]).parent != source
    assert test_state["args"][0] == "t"
    assert not any(argument.startswith("-p") for argument in test_state["args"])
    logs = Path(results[0]["log_path"])
    assert {path.name for path in logs.iterdir()} == {
        "metadata.json",
        "create.stdout.log",
        "create.stderr.log",
        "test.stdout.log",
        "test.stderr.log",
    }
    metadata = json.loads((logs / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["create"]["exit_code"] == 0
    assert metadata["test"]["exit_code"] == 0
    assert metadata["commit"]["status"] == "committed"
