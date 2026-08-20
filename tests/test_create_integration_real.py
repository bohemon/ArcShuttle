from __future__ import annotations

import threading
from pathlib import Path

import pytest

from arcshuttle.sevenzip import SevenZip, find_executable
from arcshuttle.util import UsageError


@pytest.fixture(scope="module")
def real_sevenzip() -> SevenZip:
    try:
        executable = find_executable(None)
    except UsageError:
        pytest.skip("real 7-Zip is unavailable")
    return SevenZip(executable)


@pytest.mark.parametrize(
    ("archive_format", "method"),
    [("7z", "LZMA2"), ("zip", "Deflate")],
)
def test_real_sevenzip_create_is_unencrypted(
    tmp_path: Path,
    real_sevenzip: SevenZip,
    archive_format: str,
    method: str,
) -> None:
    source = tmp_path / "non-empty.txt"
    source.write_text("non-empty payload", encoding="utf-8")
    archive = tmp_path / f"output.{archive_format}"
    logs = tmp_path / f"logs-{archive_format}"
    stop_event = threading.Event()

    outcome = real_sevenzip.create(
        source=source,
        source_kind="file",
        archive=archive,
        archive_format=archive_format,
        method=method,
        compression_level=9,
        threads=1,
        log_directory=logs,
        cpu_tokens=1,
        stop_event=stop_event,
    )

    assert (outcome.exit_code, outcome.error) == (0, None)
    inspection = real_sevenzip.inspect(archive, timeout=10)
    assert inspection.error is None
    assert inspection.inspection.encrypted is False
    verification = real_sevenzip.test(
        archive=archive,
        log_directory=logs,
        stop_event=stop_event,
    )
    assert (verification.exit_code, verification.error) == (0, None)
