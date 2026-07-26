#!/usr/bin/env python3
"""Validate AC:ITEM_BILLBOARD_TEXTURE with a source-free Yaz0 fixture."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SOURCE_OFFSET = 1_447_155_436
LOGICAL_SIZE = 6_137_393
STORED_SIZE = 6_137_408
MAX_DECOMPRESSED_SIZE = 24 * 1024 * 1024


def write_sparse(path: Path, chunks: list[tuple[int, bytes]]) -> None:
    with path.open("w+b") as handle:
        if os.name == "nt":
            import msvcrt
            returned = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.DeviceIoControl(
                msvcrt.get_osfhandle(handle.fileno()), 0x000900C4,
                None, 0, None, 0, ctypes.byref(returned), None
            )
            if not ok:
                raise OSError(
                    ctypes.get_last_error(), "FSCTL_SET_SPARSE failed"
                )
        for offset, data in chunks:
            handle.seek(offset)
            handle.write(data)


def sparse_zero_yaz0(data: bytes) -> bytes:
    tokens: list[tuple[bool, bytes]] = []
    position = 0
    while position < len(data):
        if data[position] == 0 and position > 0:
            run = 1
            while (
                position + run < len(data)
                and data[position + run] == 0
                and run < 0x111
            ):
                run += 1
            if run >= 3:
                if run >= 0x12:
                    tokens.append(
                        (False, bytes((0, 0, run - 0x12)))
                    )
                else:
                    tokens.append(
                        (False, bytes(((run - 2) << 4, 0)))
                    )
                position += run
                continue
        tokens.append((True, data[position:position + 1]))
        position += 1

    encoded = bytearray(b"Yaz0")
    encoded.extend(len(data).to_bytes(4, "big"))
    encoded.extend(b"\0" * 8)
    for start in range(0, len(tokens), 8):
        group = tokens[start:start + 8]
        code = 0
        for index, (literal, _) in enumerate(group):
            if literal:
                code |= 0x80 >> index
        encoded.append(code)
        for _, payload in group:
            encoded.extend(payload)
    if len(encoded) > LOGICAL_SIZE:
        raise RuntimeError("Yaz0 fixture exceeds the exact source member")
    encoded.extend(b"\0" * (LOGICAL_SIZE - len(encoded)))
    encoded.extend(bytes(range(1, STORED_SIZE - LOGICAL_SIZE + 1)))
    return bytes(encoded)


def recipe(
    name: str, texture_offset: int, palette_offset: int,
    width: int, edits: dict[str, object] | None = None
) -> str:
    fields: dict[str, object] = {
        "offset": 0,
        "item_name": name,
        "source_member": "/foresta.rel.szs",
        "compressed_logical_size": LOGICAL_SIZE,
        "compressed_stored_size": STORED_SIZE,
        "texture_offset": texture_offset,
        "texture_size": width * width // 2,
        "palette_offset": palette_offset,
        "palette_size": 32,
        "width": width,
        "height": width,
        "format": "C4",
        "palette_format": "RGB5A3",
        "palette_entries": 16,
        "destination_path": f"__OTR__ac/texture/item/{name}.OTEX",
    }
    range_fields: dict[str, object] = {
        "source_offset": SOURCE_OFFSET,
        "size": STORED_SIZE,
        "packed_offset": 0,
    }
    for key, value in (edits or {}).items():
        if key.startswith("range_"):
            range_fields[key.removeprefix("range_")] = value
        else:
            fields[key] = value
    lines = [
        f"{name}:",
        "  type: AC:ITEM_BILLBOARD_TEXTURE",
        "  path: source.bin",
        "  bounded_ranges:",
        f"    - source_offset: {range_fields['source_offset']}",
        f"      size: {range_fields['size']}",
        f"      packed_offset: {range_fields['packed_offset']}",
    ]
    lines.extend(f"  {key}: {value}" for key, value in fields.items())
    return "\n".join(lines)


def configure(root: Path, body: str) -> None:
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "root.yml").write_text(
        body + "\n", encoding="utf-8"
    )
    (root / "config.yml").write_text(
        "mode: directory\nfolder: item-billboard\npath: assets\nconfig:\n"
        "  sort: OFFSET\n  logging: CRITICAL\n  output:\n"
        "    binary: game.o2r\n",
        encoding="utf-8",
    )


def run(torch: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(torch), "o2r", "source.bin", "-s", ".", "-d", "out"],
        cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=os.environ.copy(), check=False,
    )


def expand3(value: int) -> int:
    return (value * 255 + 3) // 7


def expand4(value: int) -> int:
    return value * 17


def expand5(value: int) -> int:
    return (value << 3) | (value >> 2)


def decode_color(value: int) -> bytes:
    if value & 0x8000:
        return bytes((
            expand5((value >> 10) & 31),
            expand5((value >> 5) & 31),
            expand5(value & 31),
            255,
        ))
    return bytes((
        expand4((value >> 8) & 15),
        expand4((value >> 4) & 15),
        expand4(value & 15),
        expand3((value >> 12) & 7),
    ))


def decode_c4(image: bytes, palette: bytes, width: int) -> bytes:
    colors = [
        decode_color(int.from_bytes(palette[index:index + 2], "big"))
        for index in range(0, 32, 2)
    ]
    rgba = bytearray(width * width * 4)
    tiles = width // 8
    for tile_y in range(tiles):
        for tile_x in range(tiles):
            tile_base = (tile_y * tiles + tile_x) * 32
            for y in range(8):
                for x in range(8):
                    packed = image[tile_base + y * 4 + x // 2]
                    index = packed >> 4 if x % 2 == 0 else packed & 15
                    destination = (
                        ((tile_y * 8 + y) * width + tile_x * 8 + x)
                        * 4
                    )
                    rgba[destination:destination + 4] = colors[index]
    return bytes(rgba)


def validate_entry(
    payload: bytes, image: bytes, palette: bytes, width: int
) -> None:
    expected = decode_c4(image, palette, width)
    if len(payload) != 80 + len(expected):
        raise RuntimeError(f"unexpected OTEX size: {len(payload)}")
    if payload[:4] != b"\x01\0\0\0" or payload[4:8] != b"OTEX":
        raise RuntimeError("OTEX resource header is invalid")
    if payload[64:68] != b"ACTX":
        raise RuntimeError("OTEX payload magic is invalid")
    metadata = (
        width.to_bytes(2, "big") + width.to_bytes(2, "big")
        + (1).to_bytes(4, "big") + len(expected).to_bytes(4, "big")
    )
    if payload[68:80] != metadata or payload[80:] != expected:
        raise RuntimeError("OTEX decoded texture differs")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--torch", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    specs = [
        ("bag", 0xB6DC20, 0xB6DC00, 32),
        ("shell-a", 0xB72560, 0xB72540, 16),
    ]
    rel_size = max(
        max(texture + width * width // 2, palette + 32)
        for _, texture, palette, width in specs
    )
    rel = bytearray(rel_size)
    fixtures: dict[str, tuple[bytes, bytes, int]] = {}
    for item_index, (name, texture, palette, width) in enumerate(specs):
        palette_bytes = b"".join(
            (0x8000 | ((index * 2 + item_index) & 31) << 10
             | ((index * 3) & 31) << 5 | ((index * 5) & 31))
            .to_bytes(2, "big")
            for index in range(16)
        )
        image_bytes = bytes(
            (((index + item_index) & 15) << 4)
            | ((index * 3 + item_index) & 15)
            for index in range(width * width // 2)
        )
        rel[palette:palette + 32] = palette_bytes
        rel[texture:texture + len(image_bytes)] = image_bytes
        fixtures[name] = (image_bytes, palette_bytes, width)
    compressed = sparse_zero_yaz0(bytes(rel))

    try:
        positive = work / "positive"
        configure(
            positive,
            "\n".join(
                recipe(name, texture, palette, width)
                for name, texture, palette, width in specs
            ),
        )
        write_sparse(
            positive / "source.bin", [(SOURCE_OFFSET, compressed)]
        )
        result = run(args.torch.resolve(), positive)
        if result.returncode:
            raise RuntimeError(
                f"positive extraction failed (exit {result.returncode})\n"
                + result.stdout + result.stderr
            )
        with zipfile.ZipFile(positive / "out" / "game.o2r") as archive:
            expected_names = [
                "ac/texture/item/bag.OTEX",
                "ac/texture/item/shell-a.OTEX",
                "version",
            ]
            if archive.namelist() != expected_names:
                raise RuntimeError(
                    f"unexpected archive inventory/order: {archive.namelist()}"
                )
            for name, (image, palette, width) in fixtures.items():
                validate_entry(
                    archive.read(f"ac/texture/item/{name}.OTEX"),
                    image, palette, width,
                )

        name, texture, palette, width = specs[0]
        negatives = {
            "name": {"item_name": "Bag"},
            "destination": {
                "destination_path": "__OTR__ac/texture/item/present.OTEX"
            },
            "texture-offset": {"texture_offset": MAX_DECOMPRESSED_SIZE},
            "palette-offset": {"palette_offset": MAX_DECOMPRESSED_SIZE},
            "texture-size": {"texture_size": 511},
            "palette-size": {"palette_size": 30},
            "dimensions": {"height": 16},
            "format": {"format": "C8"},
            "source-member": {"source_member": "/static.str"},
            "range-offset": {"range_source_offset": SOURCE_OFFSET + 1},
            "range-size": {"range_size": STORED_SIZE - 1},
            "range-packed": {"range_packed_offset": 1},
            "generic-offset": {"offset": 1},
        }
        for case_name, edits in negatives.items():
            case = work / f"negative-{case_name}"
            configure(
                case, recipe(name, texture, palette, width, edits)
            )
            os.link(positive / "source.bin", case / "source.bin")
            if run(args.torch.resolve(), case).returncode == 0:
                raise RuntimeError(
                    f"negative case unexpectedly passed: {case_name}"
                )

        corrupt = work / "negative-yaz0"
        configure(corrupt, recipe(name, texture, palette, width))
        write_sparse(
            corrupt / "source.bin",
            [(SOURCE_OFFSET, b"Bad!" + compressed[4:])],
        )
        if run(args.torch.resolve(), corrupt).returncode == 0:
            raise RuntimeError("corrupt Yaz0 case unexpectedly passed")

        oversized = work / "negative-oversized-output"
        configure(oversized, recipe(name, texture, palette, width))
        oversized_source = bytearray(compressed)
        oversized_source[4:8] = (
            MAX_DECOMPRESSED_SIZE + 1
        ).to_bytes(4, "big")
        write_sparse(
            oversized / "source.bin",
            [(SOURCE_OFFSET, bytes(oversized_source))],
        )
        if run(args.torch.resolve(), oversized).returncode == 0:
            raise RuntimeError(
                "oversized Yaz0 output unexpectedly passed"
            )

        print(
            "AC:ITEM_BILLBOARD_TEXTURE validation passed: "
            f"entries={len(specs)} negatives={len(negatives) + 2}"
        )
        return 0
    except Exception as exc:
        print(
            f"AC:ITEM_BILLBOARD_TEXTURE validation failed: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
