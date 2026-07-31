"""7-Zip technical-listing parsing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Inspection:
    """Best-effort archive metadata returned by a technical listing."""

    format: str | None = None
    methods: list[str] = field(default_factory=list)
    packed_size: int | None = None
    unpacked_size: int | None = None
    entries: int | None = None
    solid: bool | None = None
    blocks: int | None = None
    encrypted: bool | None = None
    multipart: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the stable manifest representation."""

        return {
            "format": self.format,
            "methods": self.methods,
            "packed_size": self.packed_size,
            "unpacked_size": self.unpacked_size,
            "entries": self.entries,
            "solid": self.solid,
            "blocks": self.blocks,
            "encrypted": self.encrypted,
            "multipart": self.multipart,
        }


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"+", "yes", "true", "1"}:
        return True
    if normalized in {"-", "no", "false", "0"}:
        return False
    return None


def parse_technical_listing(text: str) -> Inspection:
    """Parse the stable ``7z l -slt`` key/value subset conservatively."""

    sections: list[dict[str, str]] = []
    current: dict[str, str] = {}
    after_separator = False
    archive_meta: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip("\ufeff\r\n")
        if line.startswith("----------"):
            if current:
                archive_meta.update(current)
                current = {}
            after_separator = True
            continue
        if not line.strip():
            if after_separator and current:
                sections.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        current[key.strip()] = value.strip()
    if current:
        if after_separator:
            sections.append(current)
        else:
            archive_meta.update(current)

    methods: list[str] = []
    method_values = [archive_meta.get("Method", "")]
    method_values.extend(section.get("Method", "") for section in sections)
    for value in method_values:
        for token in value.replace(":", " ").replace("/", " ").split():
            if token and not token.isdigit() and token not in methods:
                methods.append(token)

    sizes = [_integer(section.get("Size")) for section in sections]
    known_sizes = [value for value in sizes if value is not None]
    encrypted_values = [_boolean(archive_meta.get("Encrypted"))]
    encrypted_values.extend(_boolean(section.get("Encrypted")) for section in sections)
    solid = _boolean(archive_meta.get("Solid"))
    volumes = _integer(archive_meta.get("Volumes"))
    return Inspection(
        format=archive_meta.get("Type") or archive_meta.get("Format"),
        methods=methods,
        packed_size=_integer(archive_meta.get("Physical Size"))
        or _integer(archive_meta.get("Packed Size")),
        unpacked_size=sum(known_sizes) if known_sizes else _integer(archive_meta.get("Size")),
        entries=len(sections) if after_separator else None,
        solid=solid,
        blocks=_integer(archive_meta.get("Blocks")),
        encrypted=True
        if True in encrypted_values
        else (False if False in encrypted_values else None),
        multipart=(volumes > 1) if volumes is not None else None,
    )
