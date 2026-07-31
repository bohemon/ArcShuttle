"""Tiny controllable 7-Zip stand-in used by integration tests."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def load_config(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def configured(path: Path) -> dict[str, object]:
    explicit = os.environ.get("FAKE7Z_CONFIG")
    return load_config(Path(explicit)) if explicit else load_config(path)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("7-Zip (fake) 24.00")
        return 0
    command = args[0]
    archive = Path(args[-1])
    config = configured(archive)
    if command == "l":
        listing = config.get("listing")
        if isinstance(listing, str):
            print(listing)
        else:
            print(f"Path = {archive}")
            print("Type = 7z")
            print(f"Physical Size = {archive.stat().st_size}")
            print("Method = LZMA2")
            print("Solid = -")
            print("Blocks = 1")
            print("----------")
            print("Path = payload.txt")
            print("Size = 7")
            print("Encrypted = -")
        print(str(config.get("listing_stderr", "")), file=sys.stderr)
        return int(config.get("listing_exit", 0))
    if command == "a":
        separator = args.index("--")
        output = Path(args[separator + 1])
        source_argument = args[separator + 2]
        time.sleep(float(config.get("create_sleep", 0)))
        if config.get("create_archive", True):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(config), encoding="utf-8")
        state = os.environ.get("FAKE7Z_STATE")
        if state:
            state_path = Path(state)
            state_path.mkdir(parents=True, exist_ok=True)
            (state_path / f"a-{os.getpid()}.json").write_text(
                json.dumps(
                    {
                        "args": args,
                        "cwd": str(Path.cwd()),
                        "source_argument": source_argument,
                    }
                ),
                encoding="utf-8",
            )
        print(str(config.get("create_stdout", "fake create stdout")))
        print(str(config.get("create_stderr", "fake create stderr")), file=sys.stderr)
        return int(config.get("create_exit", 0))
    if command == "t":
        archive = Path(args[-1])
        config = configured(archive)
        state = os.environ.get("FAKE7Z_STATE")
        if state:
            state_path = Path(state)
            state_path.mkdir(parents=True, exist_ok=True)
            (state_path / f"t-{os.getpid()}.json").write_text(
                json.dumps({"args": args, "cwd": str(Path.cwd())}), encoding="utf-8"
            )
        print(str(config.get("test_stdout", "fake test stdout")))
        print(str(config.get("test_stderr", "fake test stderr")), file=sys.stderr)
        return int(config.get("test_exit", 0))
    if command != "x":
        return 7
    output_switch = next(arg for arg in args if arg.startswith("-o"))
    threads_switch = next(arg for arg in args if arg.startswith("-mmt="))
    output = Path(output_switch[2:])
    output.mkdir(parents=True, exist_ok=True)
    time.sleep(float(config.get("sleep", 0)))
    if config.get("create", True):
        (output / "payload.txt").write_text(str(config.get("payload", "created")), encoding="utf-8")
    state = os.environ.get("FAKE7Z_STATE")
    if state:
        state_path = Path(state)
        state_path.mkdir(parents=True, exist_ok=True)
        (state_path / f"{os.getpid()}.json").write_text(
            json.dumps({"args": args, "threads": int(threads_switch.split("=", 1)[1])}),
            encoding="utf-8",
        )
    print(str(config.get("stdout", "fake stdout")))
    print(str(config.get("stderr", "fake stderr")), file=sys.stderr)
    return int(config.get("exit", 0))


if __name__ == "__main__":
    raise SystemExit(main())
