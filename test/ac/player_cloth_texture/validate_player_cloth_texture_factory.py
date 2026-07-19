#!/usr/bin/env python3
"""Exercise the bounded AC:PLAYER_CLOTH_TEXTURE factory with synthetic inputs."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SPECIFICATIONS = {
    0: {
        "entry": "ac/texture/forest_1st/player/cloth-000.OTEX",
        "image_source_offset": 1454014656,
        "palette_source_offset": 1453900320,
    },
    1: {
        "entry": "ac/texture/forest_1st/player/cloth-001.OTEX",
        "image_source_offset": 1454015168,
        "palette_source_offset": 1453900352,
    },
    2: {
        "entry": "ac/texture/forest_1st/player/cloth-002.OTEX",
        "image_source_offset": 1454015680,
        "palette_source_offset": 1453900384,
    },
    3: {
        "entry": "ac/texture/forest_1st/player/cloth-003.OTEX",
        "image_source_offset": 1454016192,
        "palette_source_offset": 1453900416,
    },
    4: {
        "entry": "ac/texture/forest_1st/player/cloth-004.OTEX",
        "image_source_offset": 1454016704,
        "palette_source_offset": 1453900448,
    },
}
EXPECTED_RGBA_SHA256 = "2ceef1598e28c0329d75887aa65d60a9dea92245f5bc9160ecbb29429fd5ed69"
EXPECTED_PIXELS = {
    (0, 0): (0, 0, 0, 255),
    (7, 0): (24, 49, 74, 255),
    (8, 0): (8, 16, 24, 255),
    (0, 8): (33, 66, 99, 255),
    (15, 17): (16, 33, 49, 255),
    (31, 31): (99, 198, 33, 255),
}


def synthetic_ranges() -> tuple[bytes, bytes]:
    image = bytearray()
    for tile in range(16):
        for pixel_pair in range(32):
            high = (tile + pixel_pair) & 15
            low = (tile * 3 + pixel_pair) & 15
            image.append((high << 4) | low)
    palette = bytearray()
    for index in range(16):
        value = 0x8000 | (index << 10) | ((index * 2 & 31) << 5) | (index * 3 & 31)
        palette += value.to_bytes(2, "big")
    return bytes(image), bytes(palette)


def write_sparse(path: Path, chunks: list[tuple[int, bytes]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w+b") as handle:
        if os.name == "nt":
            import msvcrt
            returned = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.DeviceIoControl(
                msvcrt.get_osfhandle(handle.fileno()), 0x000900C4,
                None, 0, None, 0, ctypes.byref(returned), None)
            if not ok:
                raise OSError(ctypes.get_last_error(), "FSCTL_SET_SPARSE failed")
        for offset, data in chunks:
            handle.seek(offset)
            handle.write(data)


def default_ranges(cloth_index: int) -> list[dict[str, int]]:
    specification = SPECIFICATIONS[cloth_index]
    return [
        {"source_offset": specification["image_source_offset"],
         "size": 512, "packed_offset": 0},
        {"source_offset": specification["palette_source_offset"],
         "size": 32, "packed_offset": 512},
    ]


def configure(root: Path, image: bytes, palette: bytes, *,
              cloth_index: int = 0,
              edits: dict[str, object] | None = None,
              ranges: list[dict[str, int]] | None = None,
              source_base: bool = False) -> None:
    specification = SPECIFICATIONS.get(cloth_index, SPECIFICATIONS[0])
    selected_ranges = (
        default_ranges(cloth_index)
        if ranges is None and cloth_index in SPECIFICATIONS
        else default_ranges(0) if ranges is None else ranges
    )
    (root / "assets").mkdir(parents=True)
    write_sparse(root / "source.bin", [
        (specification["palette_source_offset"], palette),
        (specification["image_source_offset"], image),
    ])
    fields: dict[str, object] = {
        "offset": 0, "image_offset": 0, "image_size": 512,
        "palette_offset": 512, "palette_size": 32, "cloth_index": cloth_index,
        "width": 32, "height": 32, "format": "C4",
        "palette_format": "RGB5A3", "palette_entries": 16,
        "destination_path": f"__OTR__{specification['entry']}",
    }
    if edits:
        fields.update(edits)
    lines = ["cloth:", "  type: AC:PLAYER_CLOTH_TEXTURE", "  path: source.bin",
             "  bounded_ranges:"]
    for item in selected_ranges:
        lines.append(f"    - source_offset: {item['source_offset']}")
        lines.append(f"      size: {item['size']}")
        lines.append(f"      packed_offset: {item['packed_offset']}")
    if source_base:
        lines.append("  source_base_offset: 0")
    lines += [f"  {key}: {value}" for key, value in fields.items()]
    (root / "assets" / "root.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "config.yml").write_text(
        "mode: directory\nfolder: cloth\npath: assets\nconfig:\n"
        "  sort: OFFSET\n  logging: CRITICAL\n  output:\n    binary: cloth.o2r\n",
        encoding="utf-8",
    )


def run(torch: Path, root: Path, destination: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(torch), "o2r", "source.bin", "-s", ".", "-d", destination],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=os.environ.copy(), check=False,
    )


def rgba(archive: Path, entry: str) -> bytes:
    with zipfile.ZipFile(archive) as handle:
        if handle.namelist() != [entry, "version"]:
            raise RuntimeError(f"unexpected archive order: {handle.namelist()}")
        data = handle.read(entry)
    if (len(data) != 4176 or data[:1] != b"\x01" or data[4:8] != b"OTEX"
            or data[8:12] != bytes(4) or data[64:68] != b"ACTX"
            or data[68:72] != b"\x00 \x00 " or data[72:76] != (1).to_bytes(4, "big")
            or data[76:80] != (4096).to_bytes(4, "big")):
        raise RuntimeError("cloth OTEX/ACTX shape mismatch")
    return data[80:]


def assert_oracle(data: bytes) -> None:
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_RGBA_SHA256:
        raise RuntimeError(f"fixed synthetic RGBA hash mismatch: {digest}")
    for (x, y), expected in EXPECTED_PIXELS.items():
        offset = (y * 32 + x) * 4
        actual = tuple(data[offset:offset + 4])
        if actual != expected:
            raise RuntimeError(f"fixed pixel oracle mismatch at {(x, y)}: {actual}")


def reject(torch: Path, work: Path, name: str, image: bytes, palette: bytes,
           **configuration) -> None:
    case = work / f"negative-{name}"
    configure(case, image, palette, **configuration)
    if run(torch, case, "out").returncode == 0:
        raise RuntimeError(f"negative case unexpectedly passed: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--torch", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        image, palette = synthetic_ranges()
        positive_outputs = {}
        for cloth_index, specification in SPECIFICATIONS.items():
            positive = work / f"positive-{cloth_index}"
            configure(positive, image, palette, cloth_index=cloth_index)
            first = run(args.torch.resolve(), positive, "out-a")
            second = run(args.torch.resolve(), positive, "out-b")
            if first.returncode or second.returncode:
                raise RuntimeError(
                    f"synthetic cloth-{cloth_index:03d} positive failed\n" +
                    first.stdout + first.stderr + second.stdout + second.stderr)
            first_rgba = rgba(
                positive / "out-a" / "cloth.o2r", specification["entry"])
            second_rgba = rgba(
                positive / "out-b" / "cloth.o2r", specification["entry"])
            assert_oracle(first_rgba)
            if first_rgba != second_rgba:
                raise RuntimeError(
                    f"synthetic cloth-{cloth_index:03d} outputs differed")
            positive_outputs[cloth_index] = first_rgba
        if any(output != positive_outputs[0]
               for output in positive_outputs.values()):
            raise RuntimeError("identical synthetic cloth inputs decoded differently by index")

        reject(args.torch.resolve(), work, "truncated-image", image[:-1], palette)
        field_negatives = {
            "generic-offset": {"offset": 1},
            "extra-image-range": {"image_size": 513},
            "extra-palette-range": {"palette_size": 33},
            "image-packed-offset": {"image_offset": 1},
            "palette-packed-offset": {"palette_offset": 513},
            "cloth-index-high": {"cloth_index": 5},
            "width": {"width": 31},
            "height": {"height": 31},
            "format": {"format": "C8"},
            "palette-format": {"palette_format": "RGB565"},
            "palette-entries": {"palette_entries": 15},
            "destination": {"destination_path": "__OTR__ac/texture/not-cloth.OTEX"},
        }
        for name, edits in field_negatives.items():
            reject(args.torch.resolve(), work, name, image, palette, edits=edits)
        reject(
            args.torch.resolve(), work, "cloth-index-far", image, palette,
            cloth_index=255)
        bounded_neighbor_negatives = 0
        for cloth_index in (1, 2, 3, 4):
            reject(
                args.torch.resolve(), work,
                f"cloth-{cloth_index:03d}-wrong-destination", image, palette,
                cloth_index=cloth_index,
                edits={"destination_path": f"__OTR__{SPECIFICATIONS[0]['entry']}"})
            reject(
                args.torch.resolve(), work,
                f"cloth-{cloth_index:03d}-wrong-image-source", image, palette,
                cloth_index=cloth_index,
                ranges=[
                    default_ranges(0)[0],
                    default_ranges(cloth_index)[1],
                ])
            reject(
                args.torch.resolve(), work,
                f"cloth-{cloth_index:03d}-wrong-palette-source", image, palette,
                cloth_index=cloth_index,
                ranges=[
                    default_ranges(cloth_index)[0],
                    default_ranges(0)[1],
                ])
            bounded_neighbor_negatives += 3
        reject(args.torch.resolve(), work, "source-base", image, palette, source_base=True)

        exact = default_ranges(0)
        range_negatives = {
            "range-count-short": exact[:1],
            "range-count-extra": exact + [
                {"source_offset": SPECIFICATIONS[0]["image_source_offset"],
                 "size": 1, "packed_offset": 544}],
            "range-order": [exact[1], exact[0]],
            "range-source-offset": [
                {**exact[0], "source_offset":
                    SPECIFICATIONS[0]["image_source_offset"] + 1}, exact[1]],
            "range-size-short": [{**exact[0], "size": 511}, exact[1]],
            "range-size-extra": [{**exact[0], "size": 513}, exact[1]],
            "range-packed-gap": [{**exact[0], "packed_offset": 1}, exact[1]],
            "range-overflow": [
                {"source_offset": 18446744073709551615, "size": 2, "packed_offset": 0},
                exact[1]],
        }
        for name, ranges in range_negatives.items():
            reject(args.torch.resolve(), work, name, image, palette, ranges=ranges)

        total_negatives = (
            1 + len(field_negatives) + 1 + bounded_neighbor_negatives +
            1 + len(range_negatives))
        print("AC:PLAYER_CLOTH_TEXTURE bounded validation passed: "
              f"indices=0,1,2,3,4 rgba_sha256={EXPECTED_RGBA_SHA256} "
              f"negatives={total_negatives}")
        return 0
    except Exception as exc:
        print(f"AC:PLAYER_CLOTH_TEXTURE validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
