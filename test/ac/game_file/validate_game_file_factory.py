#!/usr/bin/env python3
"""Validate strict raw AC:GAME_FILE export with source-free sparse data."""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DOL_OFFSET = 122880
DOL_SIZE = 918720
COPYDATE_OFFSET = 1447155360
COPYDATE_LOGICAL = 19
COPYDATE_STORED = 32


def write_sparse(path: Path, chunks: list[tuple[int, bytes]]) -> None:
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


def entry(name: str, role: str, source_offset: int, logical: int,
          stored: int, destination: str, edits: dict[str, object] | None = None) -> str:
    fields: dict[str, object] = {
        "type": "AC:GAME_FILE", "path": "source.bin", "offset": 0,
        "role": role, "logical_size": logical, "stored_size": stored,
        "destination_path": destination,
    }
    range_fields: dict[str, object] = {
        "source_offset": source_offset, "size": stored, "packed_offset": 0,
    }
    for key, value in (edits or {}).items():
        if key.startswith("range_"):
            range_fields[key.removeprefix("range_")] = value
        else:
            fields[key] = value
    lines = [f"{name}:", "  type: AC:GAME_FILE", "  path: source.bin",
             "  bounded_ranges:",
             f"    - source_offset: {range_fields['source_offset']}",
             f"      size: {range_fields['size']}",
             f"      packed_offset: {range_fields['packed_offset']}"]
    lines.extend(f"  {key}: {value}" for key, value in fields.items()
                 if key not in {"type", "path"})
    return "\n".join(lines)


def configure(root: Path, body: str) -> None:
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "root.yml").write_text(body + "\n", encoding="utf-8")
    (root / "config.yml").write_text(
        "mode: directory\nfolder: game-file\npath: assets\nconfig:\n"
        "  sort: OFFSET\n  logging: CRITICAL\n  output:\n    binary: game.o2r\n",
        encoding="utf-8")


def run(torch: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(torch), "o2r", "source.bin", "-s", ".", "-d", "out"],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=os.environ.copy(), check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--torch", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    dol = bytes((index * 17 + 3) & 0xFF for index in range(DOL_SIZE))
    copydate = bytes((index * 29 + 7) & 0xFF for index in range(COPYDATE_STORED))
    try:
        positive = work / "positive"
        configure(positive, "\n".join([
            entry("main_dol", "dol", DOL_OFFSET, DOL_SIZE, DOL_SIZE,
                  "__OTR__ac/executable/main.dol"),
            entry("copydate", "dvd", COPYDATE_OFFSET, COPYDATE_LOGICAL,
                  COPYDATE_STORED, "__OTR__ac/dvd/COPYDATE"),
        ]))
        write_sparse(positive / "source.bin", [
            (DOL_OFFSET, dol), (COPYDATE_OFFSET, copydate)])
        result = run(args.torch.resolve(), positive)
        if result.returncode:
            raise RuntimeError("positive extraction failed\n" + result.stdout + result.stderr)
        with zipfile.ZipFile(positive / "out" / "game.o2r") as archive:
            names = archive.namelist()
            if names != ["ac/executable/main.dol", "ac/dvd/COPYDATE", "version"]:
                raise RuntimeError(f"unexpected archive inventory/order: {names}")
            if archive.read("ac/executable/main.dol") != dol:
                raise RuntimeError("DOL raw bytes acquired a resource header or changed")
            if archive.read("ac/dvd/COPYDATE") != copydate:
                raise RuntimeError("DVD aligned physical bytes changed")

        negatives = {
            "role": {"role": "dol"},
            "logical": {"logical_size": COPYDATE_LOGICAL + 1},
            "stored": {"stored_size": COPYDATE_STORED - 1},
            "destination": {"destination_path": "__OTR__ac/dvd/static.str"},
            "range-offset": {"range_source_offset": COPYDATE_OFFSET + 1},
            "range-size": {"range_size": COPYDATE_STORED - 1},
            "range-packed": {"range_packed_offset": 1},
            "generic-offset": {"offset": 1},
        }
        for name, edits in negatives.items():
            case = work / f"negative-{name}"
            configure(case, entry(
                "copydate", "dvd", COPYDATE_OFFSET, COPYDATE_LOGICAL,
                COPYDATE_STORED, "__OTR__ac/dvd/COPYDATE", edits))
            write_sparse(case / "source.bin", [(COPYDATE_OFFSET, copydate)])
            if run(args.torch.resolve(), case).returncode == 0:
                raise RuntimeError(f"negative case unexpectedly passed: {name}")
        print(f"AC:GAME_FILE raw validation passed: entries=2 negatives={len(negatives)}")
        return 0
    except Exception as exc:
        print(f"AC:GAME_FILE validation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
