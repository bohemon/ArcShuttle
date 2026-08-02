from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from arcshuttle import cli, compat
from arcshuttle.config import Config
from arcshuttle.multipart import MultipartInfo
from arcshuttle.operations.extract import make_legacy_plan
from arcshuttle.sevenzip import ProcessOutcome
from arcshuttle.storage import StorageClass, StorageObservation


class PlanningSevenZip:
    executable = Path("fake-7z")

    def version(self) -> str:
        return "fake"

    def inspect(self, path: Path, timeout: float):
        raise AssertionError("inspection was not expected")


class FullSevenZip(PlanningSevenZip):
    def extract(
        self,
        *,
        archive: Path,
        staging: Path,
        threads: int,
        log_directory: Path,
        cpu_tokens: int,
        stop_event: threading.Event,
    ) -> ProcessOutcome:
        log_directory.mkdir(parents=True)
        (log_directory / "stdout.log").write_text("ok", encoding="utf-8")
        (staging / "payload.txt").write_text("ok", encoding="utf-8")
        return ProcessOutcome(0, False)

    def interrupt_all(self) -> None:
        pass


class FullCreateSevenZip(PlanningSevenZip):
    def create(self, **kwargs: object) -> ProcessOutcome:
        archive = kwargs["archive"]
        log_directory = kwargs["log_directory"]
        assert isinstance(archive, Path)
        assert isinstance(log_directory, Path)
        archive.write_bytes(b"created")
        log_directory.mkdir(parents=True)
        return ProcessOutcome(0, False)

    def test(self, **kwargs: object) -> ProcessOutcome:
        return ProcessOutcome(0, False)

    def interrupt_all(self) -> None:
        pass


def patch_sevenzip(monkeypatch: pytest.MonkeyPatch, instance: PlanningSevenZip) -> None:
    monkeypatch.setattr(cli, "find_executable", lambda configured: Path("fake"))
    monkeypatch.setattr(cli, "SevenZip", lambda executable: instance)


def test_plan_outputs_only_json_lines_to_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "空 白.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--small-threshold", "1M", str(archive)])
    captured = capsys.readouterr()

    assert code == 0
    record = json.loads(captured.out)
    assert record["schema_version"] == 1
    assert "operation" not in record
    assert record["path"] == str(archive.resolve())
    assert "7-Zip" in captured.err


def test_arcshuttle_plan_extract_outputs_schema_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "schema-v2.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = cli.main(["plan", "extract", "--small-threshold", "1M", str(archive)])
    captured = capsys.readouterr()
    record = json.loads(captured.out)

    assert code == 0
    assert record["schema_version"] == 2
    assert record["operation"] == "extract"
    assert record["source"]["path"] == str(archive.resolve())
    assert record["destination"]["kind"] == "directory"


def test_arcshuttle_plan_create_outputs_schema_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "圧縮 対象"
    source.mkdir()
    (source / "data.txt").write_text("content", encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = cli.main(["plan", "create", "--format", "zip", "--level", "7", str(source)])
    captured = capsys.readouterr()
    record = json.loads(captured.out)

    assert code == 0
    assert record["operation"] == "create"
    assert record["source"]["kind"] == "directory"
    assert record["destination"]["path"] == str(tmp_path / "圧縮 対象.zip")
    assert record["archive"] == {
        "format": "zip",
        "method": "Deflate",
        "compression_level": 7,
    }


def test_standalone_plan_never_detects_runtime_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "plan-only.dat"
    source.write_bytes(b"data")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    def forbidden(_path: Path) -> StorageObservation:
        raise AssertionError("standalone planning must not inspect runtime storage")

    code = cli.main(["plan", "create", "--quiet", str(source)], storage_detector=forbidden)

    assert code == 0


def test_arcshuttle_plan_create_reads_utf8_nul_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "nul 空白.dat"
    source.write_bytes(b"data")
    path_file = tmp_path / "paths.bin"
    path_file.write_bytes(str(source).encode("utf-8") + b"\0")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = cli.main(["plan", "create", "--files0-from", str(path_file)])
    captured = capsys.readouterr()

    assert code == 0
    assert json.loads(captured.out)["source"]["path"] == str(source)


def test_arcshuttle_create_plans_and_runs_in_one_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.dat"
    source.write_bytes(b"source")
    patch_sevenzip(monkeypatch, FullCreateSevenZip())
    detected: list[Path] = []

    def detector(path: Path) -> StorageObservation:
        detected.append(path)
        return StorageObservation("fixture:nvme", StorageClass.NVME, "fixture")

    code = cli.main(
        [
            "create",
            "--output-dir",
            str(tmp_path / "out"),
            "--log-dir",
            str(tmp_path / "logs"),
            str(source),
        ],
        storage_detector=detector,
    )
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert code == 0
    assert [record["record_type"] for record in records] == ["result", "summary"]
    assert records[0]["operation"] == "create"
    assert Path(records[0]["output_dir"]).read_bytes() == b"created"
    assert detected == [source, tmp_path / "out" / "source.dat.7z"]
    assert "arcshuttle: I/O auto: io_slots=" in captured.err
    assert "detected storage classes: nvme" in captured.err


def test_no_implicit_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan"])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""


def test_explicit_empty_input_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tmp_path / "paths.txt"
    paths.write_text("", encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--files-from", str(paths)])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""


def test_input_failure_emits_no_partial_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "good.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", str(archive), str(tmp_path / "missing.zip")])
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""
    assert "input error" in captured.err


def test_skip_input_errors_outputs_valid_jobs_and_returns_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "good.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(
        [
            "plan",
            "--on-input-error",
            "skip",
            str(archive),
            str(tmp_path / "missing.zip"),
        ]
    )
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out)["record_type"] == "job"


def test_files_from_is_exclusive_with_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["plan", "--files-from", "-", "a.zip"])
    capsys.readouterr()

    assert code == 64


def test_malformed_manifest_is_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("not json\n", encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    code = compat.parxtract_main(["run", "--manifest", str(manifest)])
    capsys.readouterr()

    assert code == 64


def test_invalid_manifest_shape_is_rejected_before_storage_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text('{"schema_version":2,"record_type":"job"}\n', encoding="utf-8")
    patch_sevenzip(monkeypatch, PlanningSevenZip())

    def forbidden(_path: Path) -> StorageObservation:
        raise AssertionError("invalid manifests must not invoke detection")

    code = cli.main(["run", "--manifest", str(manifest)], storage_detector=forbidden)
    captured = capsys.readouterr()

    assert code == 64
    assert captured.out == ""
    assert "missing field" in captured.err


def test_plan_filter_run_contract_emits_result_then_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"zip")
    config = Config(output_dir=tmp_path / "out", inspect_threshold=1000, small_threshold=1000)
    planning = make_legacy_plan([MultipartInfo(archive, False)], config, PlanningSevenZip().inspect)
    planning.jobs[0]["tags"] = ["filtered"]
    manifest = tmp_path / "plan.jsonl"
    manifest.write_text(json.dumps(planning.jobs[0]) + "\n", encoding="utf-8")
    patch_sevenzip(monkeypatch, FullSevenZip())
    detected: list[Path] = []

    def detector(path: Path) -> StorageObservation:
        detected.append(path)
        return StorageObservation("fixture:ssd", StorageClass.SSD, "fixture")

    code = cli.main(
        ["run", "--quiet", "--manifest", str(manifest), "--log-dir", str(tmp_path / "logs")],
        storage_detector=detector,
    )
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert code == 0
    assert [record["record_type"] for record in records] == ["result", "summary"]
    assert records[0]["status"] == "success"
    assert detected == [archive.resolve(), (tmp_path / "out" / "archive").resolve()]


def test_extract_convenience_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, FullSevenZip())
    detected: list[Path] = []

    def detector(path: Path) -> StorageObservation:
        detected.append(path)
        return StorageObservation("fixture:nvme", StorageClass.NVME, "fixture")

    monkeypatch.setattr(cli, "default_storage_detector", lambda: detector)

    code = compat.parxtract_main(
        [
            "extract",
            "--quiet",
            "--output-dir",
            str(tmp_path / "out"),
            "--log-dir",
            str(tmp_path / "logs"),
            str(archive),
        ]
    )
    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]

    assert (code, records[0]["status"]) == (0, "success")
    assert (tmp_path / "out" / "archive" / "payload.txt").is_file()
    assert detected == [archive.resolve(), (tmp_path / "out" / "archive").resolve()]


def test_arcshuttle_extract_executes_schema_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"zip")
    patch_sevenzip(monkeypatch, FullSevenZip())
    detected: list[Path] = []

    def detector(path: Path) -> StorageObservation:
        detected.append(path)
        return StorageObservation("fixture:ssd", StorageClass.SSD, "fixture")

    code = cli.main(
        [
            "extract",
            "--quiet",
            "--output-dir",
            str(tmp_path / "out"),
            "--log-dir",
            str(tmp_path / "logs"),
            str(archive),
        ],
        storage_detector=detector,
    )
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    assert records[0]["schema_version"] == 2
    assert records[0]["operation"] == "extract"
    assert records[-1]["schema_version"] == 2
    assert detected == [archive.resolve(), (tmp_path / "out" / "archive").resolve()]
