#!/usr/bin/env python3
"""Exercise AC:BTI_TEXTURE with synthetic cases and an optional audited boy1 member."""

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

ENTRY = "ac/texture/forest_2nd/data/boy1.OTEX"
EXPECTED_REAL = "fb0482588b4054b079ebba27fd1a92bcb9846733019f0d30c41d88d9f42ccff0"
EXPECTED_ISO = "ca870a9c11ae26cd4d3fb94befd7ecbd075c36244589061d22e3ddc4552dc379"
MEMBER_OFFSET = 1454147680
MEMBER_SIZE = 2432


def synthetic_bti() -> bytes:
    width, height, colors = 32, 64, 176
    image = bytes(i % colors for i in range(2048))
    palette = bytearray()
    for i in range(colors):
        value = 0x8000 | ((i & 31) << 10) | (((i * 3) & 31) << 5) | ((i * 5) & 31)
        palette += value.to_bytes(2, "big")
    header = bytearray(32)
    header[0] = 9
    header[1] = 2
    header[2:4] = width.to_bytes(2, "big")
    header[4:6] = height.to_bytes(2, "big")
    header[8] = 1
    header[9] = 2
    header[10:12] = colors.to_bytes(2, "big")
    header[12:16] = (2080).to_bytes(4, "big")
    header[24] = 1
    header[28:32] = (32).to_bytes(4, "big")
    return bytes(header) + image + bytes(palette)


def write_sparse(path: Path, offset: int, member: bytes) -> None:
    with path.open("w+b") as handle:
        if os.name == "nt":
            import msvcrt
            returned = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.DeviceIoControl(
                msvcrt.get_osfhandle(handle.fileno()), 0x000900C4,
                None, 0, None, 0, ctypes.byref(returned), None)
            if not ok:
                raise OSError(ctypes.get_last_error(), "FSCTL_SET_SPARSE failed")
        handle.seek(offset)
        handle.write(member)


def config(root: Path, member: bytes, *, offset: int = 0,
           ranges: list[dict[str, int]] | None = None,
           source_base: bool = False) -> None:
    (root / "assets").mkdir(parents=True)
    (root / "source").mkdir()
    write_sparse(root / "source" / "boy1.bti", MEMBER_OFFSET, member)
    (root / "config.yml").write_text(
        "mode: directory\nfolder: ac-bti-texture\npath: assets\nconfig:\n"
        "  sort:\n    - AC:BTI_TEXTURE\n  logging: CRITICAL\n"
        "  output:\n    binary: boy1.o2r\n", encoding="utf-8")
    selected = ([{"source_offset": MEMBER_OFFSET, "size": MEMBER_SIZE, "packed_offset": 0}]
                if ranges is None else ranges)
    lines = ["boy1_texture:", "  type: AC:BTI_TEXTURE", "  path: source/boy1.bti",
             "  bounded_ranges:"]
    for item in selected:
        lines.append(f"    - source_offset: {item['source_offset']}")
        lines.append(f"      size: {item['size']}")
        lines.append(f"      packed_offset: {item['packed_offset']}")
    if source_base:
        lines.append("  source_base_offset: 0")
    lines += [f"  offset: {offset}", f"  size: {MEMBER_SIZE}",
              f"  destination_path: __OTR__{ENTRY}"]
    (root / "assets" / "root.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(torch: Path, root: Path, out: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(torch), "o2r", "source/boy1.bti", "-s", ".", "-d", out],
                          cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=os.environ.copy(), check=False)


def payload(archive: Path) -> bytes:
    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
        if names != [ENTRY, "version"]:
            raise RuntimeError(f"archive entries differed: {names}")
        data = zf.read(ENTRY)
    if len(data) < 80 or data[0] != 1 or data[4:8] != b"OTEX" or data[8:12] != bytes(4):
        raise RuntimeError("OTEX header mismatch")
    if data[64:68] != b"ACTX" or data[68:72] != b"\x00 \x00@" or data[72:76] != (1).to_bytes(4, "big"):
        raise RuntimeError("ACTX metadata mismatch")
    if int.from_bytes(data[76:80], "big") != 8192 or len(data) != 8272:
        raise RuntimeError("ACTX length mismatch")
    return data[80:]


def emit_runtime_negatives(archive: Path, root: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        texture = bytearray(source.read(ENTRY))
        version = source.read("version")
    mutations = {
        "type": lambda data: data.__setitem__(slice(4, 8), b"OBLB"),
        "version": lambda data: data.__setitem__(slice(8, 12), (1).to_bytes(4, "big")),
        "truncation": lambda data: data.__delitem__(slice(-1, None)),
    }
    for name, mutate in mutations.items():
        data = bytearray(texture)
        mutate(data)
        output = root / f"runtime-negative-{name}.o2r"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as target:
            target.writestr(ENTRY, data)
            target.writestr("version", version)


def expect_reject(torch: Path, work: Path, name: str, mutate) -> None:
    case = work / ("negative-" + name)
    member = bytearray(synthetic_bti())
    mutate(member)
    config(case, bytes(member))
    result = run(torch, case, "out")
    if result.returncode == 0:
        raise RuntimeError(f"negative case unexpectedly passed: {name}")


def expect_schema_reject(torch: Path, work: Path, name: str, **configuration) -> None:
    case = work / ("negative-schema-" + name)
    config(case, synthetic_bti(), **configuration)
    result = run(torch, case, "out")
    if result.returncode == 0:
        raise RuntimeError(f"schema negative unexpectedly passed: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--torch", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--source-image", type=Path,
                        help="Canonical GAFE01_00 ISO; only the audited boy1 member range is extracted")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        positive = work / "synthetic-positive"
        config(positive, synthetic_bti())
        a, b = run(args.torch.resolve(), positive, "out-a"), run(args.torch.resolve(), positive, "out-b")
        if a.returncode or b.returncode:
            raise RuntimeError("synthetic positive failed\n" + a.stdout + a.stderr + b.stdout + b.stderr)
        rgba_a = payload(positive / "out-a" / "boy1.o2r")
        rgba_b = payload(positive / "out-b" / "boy1.o2r")
        if rgba_a != rgba_b:
            raise RuntimeError("synthetic A/B payload differed")

        negatives = [
            ("format", lambda m: m.__setitem__(0, 8)),
            ("palette-format", lambda m: m.__setitem__(9, 1)),
            ("zero-width", lambda m: m.__setitem__(slice(2, 4), b"\0\0")),
            ("image-range", lambda m: m.__setitem__(slice(28, 32), (2400).to_bytes(4, "big"))),
            ("palette-range", lambda m: m.__setitem__(slice(12, 16), (2400).to_bytes(4, "big"))),
            ("palette-index", lambda m: m.__setitem__(32, 255)),
        ]
        for name, mutate in negatives:
            expect_reject(args.torch.resolve(), work, name, mutate)

        exact_range = {"source_offset": MEMBER_OFFSET, "size": MEMBER_SIZE, "packed_offset": 0}
        schema_negatives = {
            "generic-offset": {"offset": 1},
            "source-base": {"source_base": True},
            "range-count": {"ranges": [exact_range, {
                "source_offset": MEMBER_OFFSET, "size": 1, "packed_offset": MEMBER_SIZE}]},
            "source-offset": {"ranges": [{**exact_range, "source_offset": MEMBER_OFFSET + 1}]},
            "size-short": {"ranges": [{**exact_range, "size": MEMBER_SIZE - 1}]},
            "size-extra": {"ranges": [{**exact_range, "size": MEMBER_SIZE + 1}]},
            "packed-offset": {"ranges": [{**exact_range, "packed_offset": 1}]},
            "overflow": {"ranges": [{
                "source_offset": 18446744073709551615, "size": 2, "packed_offset": 0}]},
        }
        for name, configuration in schema_negatives.items():
            expect_schema_reject(args.torch.resolve(), work, name, **configuration)
        truncated = work / "negative-schema-truncated"
        config(truncated, synthetic_bti()[:-1])
        if run(args.torch.resolve(), truncated, "out").returncode == 0:
            raise RuntimeError("schema negative unexpectedly passed: truncated")

        if args.source_image:
            source = args.source_image.resolve()
            if source.stat().st_size != 1459978240:
                raise RuntimeError("source image size mismatch")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            if source_hash != EXPECTED_ISO:
                raise RuntimeError("source image SHA-256 mismatch")
            with source.open("rb") as handle:
                handle.seek(MEMBER_OFFSET)
                member = handle.read(MEMBER_SIZE)
            if len(member) != MEMBER_SIZE:
                raise RuntimeError("source boy1 member extraction was short")
            real = work / "real-positive"
            config(real, member)
            a, b = run(args.torch.resolve(), real, "out-a"), run(args.torch.resolve(), real, "out-b")
            if a.returncode or b.returncode:
                raise RuntimeError("real positive failed\n" + a.stdout + a.stderr + b.stdout + b.stderr)
            pa = payload(real / "out-a" / "boy1.o2r")
            pb = payload(real / "out-b" / "boy1.o2r")
            digest = hashlib.sha256(pa).hexdigest()
            if pa != pb or digest != EXPECTED_REAL:
                raise RuntimeError(f"real A/B decode mismatch: {digest}")
            emit_runtime_negatives(real / "out-a" / "boy1.o2r", work)
            print(f"real decoded-rgba-sha256: {digest}")
            print(str(real / "out-a" / "boy1.o2r"))
        print("AC:BTI_TEXTURE bounded validation passed: "
              f"positives=2 negatives={len(negatives) + len(schema_negatives) + 1}")
        return 0
    except Exception as exc:
        print(f"AC:BTI_TEXTURE validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
