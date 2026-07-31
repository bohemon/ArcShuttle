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
def test_fake7z_create_uses_relative_source_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
    archive_format: str,
    method_switch: str,
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
    resolved = replace(config(tmp_path), create_format=archive_format)
    job = validate_manifest(make_create_plan([source], resolved).jobs, resolved)[0]

    results, _, code = execute_manifest([job], resolved, fake_runner())

    assert (code, results[0]["status"]) == (0, "success")
    assert Path(results[0]["output_dir"]).is_file()
    create_state = json.loads(next(state.glob("a-*.json")).read_text(encoding="utf-8"))
    test_state = json.loads(next(state.glob("t-*.json")).read_text(encoding="utf-8"))
    assert create_state["source_argument"] == (source.name if source_kind == "file" else ".")
    assert create_state["cwd"] == str(source.parent if source_kind == "file" else source)
    assert "-mmt=3" in create_state["args"]
    assert method_switch in create_state["args"]
    assert Path(create_state["args"][create_state["args"].index("--") + 1]).parent != source
    assert test_state["args"][0] == "t"
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


def test_level_zero_uses_7zip_store_mode_without_a_compression_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.dat"
    source.write_bytes(b"source")
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE7Z_STATE", str(state))
    resolved = replace(config(tmp_path), compression_level=0)
    job = validate_manifest(make_create_plan([source], resolved).jobs, resolved)[0]

    results, _, code = execute_manifest([job], resolved, fake_runner())

    assert (code, results[0]["status"]) == (0, "success")
    create_args = json.loads(next(state.glob("a-*.json")).read_text(encoding="utf-8"))["args"]
    assert "-mx=0" in create_args
    assert not any(argument.startswith(("-m0=", "-mm=")) for argument in create_args)
