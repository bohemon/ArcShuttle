from __future__ import annotations

from arcshuttle.inspect import parse_technical_listing


def test_technical_listing() -> None:
    listing = """Path = sample.7z
Type = 7z
Physical Size = 42
Method = LZMA2 BZip2
Solid = +
Blocks = 3
Volumes = 2
----------
Path = a.txt
Size = 10
Encrypted = -

Path = b.txt
Size = 20
Encrypted = +
"""
    result = parse_technical_listing(listing)

    assert result.format == "7z"
    assert result.packed_size == 42
    assert result.unpacked_size == 30
    assert result.entries == 2
    assert result.blocks == 3
    assert result.solid is True
    assert result.encrypted is True
    assert result.multipart is True
    assert "BZip2" in result.methods


def test_unknown_values_remain_none() -> None:
    result = parse_technical_listing("garbage\n")
    assert result.format is None
    assert result.entries is None
