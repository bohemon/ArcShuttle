from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from parxtract.cli import execute_manifest
from parxtract.config import Config
from parxtract.manifest import make_plan, validate_manifest
from parxtract.multipart import MultipartInfo
from parxtract.sevenzip import SevenZip


def test_inspect_extract_logs_threads_and_unicode_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "空 白.7z"
    archive.write_text(
        json.dumps(
            {
                "listing": "Path = x.7z\nType = 7z\nPhysical Size = 200\nMethod = BZip2\nSolid = -\nBlocks = 3\n----------\nPath = a.txt\nSize = 900\nEncrypted = -\n",
                "payload": "hello",
                "stdout": "out text",
                "stderr": "err text",
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE7Z_STATE", str(state))
    runner = SevenZip(
        Path(sys.executable), command_prefix=[str(Path(__file__).with_name("fake7z.py"))]
    )
    config = replace(
        Config(),
        output_dir=tmp_path / "out",
        log_dir=tmp_path / "logs",
        inspect_threshold=0,
        small_threshold=1,
        cpu_budget=4,
        heavy_threads=3,
        max_processes=2,
        io_slots=2,
        quiet=True,
    )

    planning = make_plan([MultipartInfo(archive, False)], config, runner.inspect)
    assert planning.jobs[0]["scheduling"]["profile"] == "heavy-scalable"
    jobs = validate_manifest(planning.jobs, config)
    results, _, code = execute_manifest(jobs, config, runner)

    assert (code, results[0]["status"]) == (0, "success")
    assert (Path(results[0]["output_dir"]) / "payload.txt").read_text() == "hello"
    invocation = json.loads(next(state.glob("*.json")).read_text())
    assert invocation["threads"] == 3
    log_dir = Path(results[0]["log_path"])
    assert "out text" in (log_dir / "stdout.log").read_text()
    assert "err text" in (log_dir / "stderr.log").read_text()
    metadata = json.loads((log_dir / "metadata.json").read_text())
    assert "shell" not in metadata
