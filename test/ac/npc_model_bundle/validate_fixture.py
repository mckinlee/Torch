#!/usr/bin/env python3
"""Validate the synthetic AC:NPC_MODEL_BUNDLE fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
EXPECTED_ARCHIVE_ENTRIES = {
    "resources/display.ODLT",
    "resources/matrix.OMTX",
    "resources/texture.OTEX",
    "resources/vertices.OVTX",
    "township/resource_slices.json",
    "version",
}
PLACEHOLDER_ENTRY = "root/npc_model_bundle"
OUTPUT_NAME = "ac_npc_model_bundle.o2r"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def synthetic_lus_resource(resource_type: bytes, body_size: int) -> bytes:
    if len(resource_type) != 4:
        raise ValueError("resource_type must be exactly four bytes")

    header = bytearray(64)
    header[0] = 1
    header[4:8] = resource_type
    body = bytes((index % 251 for index in range(body_size)))
    return bytes(header) + body


def materialize_case(case_name: str, work_root: Path) -> Path:
    case_root = work_root / case_name
    (case_root / "assets").mkdir(parents=True)
    (case_root / "archive" / "township").mkdir(parents=True)
    shutil.copyfile(FIXTURE_DIR / case_name / "root.yml", case_root / "assets" / "root.yml")
    shutil.copyfile(FIXTURE_DIR / "resource_slices.json", case_root / "archive" / "township" / "resource_slices.json")

    write_file(case_root / "source" / "source.bin", b"ACFX")
    write_file(case_root / "archive" / "resources" / "display.ODLT", synthetic_lus_resource(b"ODLT", 8))
    write_file(case_root / "archive" / "resources" / "vertices.OVTX", synthetic_lus_resource(b"OVTX", 4))
    write_file(case_root / "archive" / "resources" / "matrix.OMTX", synthetic_lus_resource(b"OMTX", 64))
    write_file(case_root / "archive" / "resources" / "texture.OTEX", synthetic_lus_resource(b"OTEX", 28))

    (case_root / "config.yml").write_text(
        "\n".join(
            [
                "mode: directory",
                "folder: synthetic-ac-npc-model-bundle",
                "path: assets",
                "config:",
                "  sort:",
                "    - AC:NPC_MODEL_BUNDLE",
                "  logging: CRITICAL",
                "  output:",
                f"    binary: {OUTPUT_NAME}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return case_root


def run_torch(torch: Path, case_root: Path, output_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(torch),
            "o2r",
            "source/source.bin",
            "-s",
            ".",
            "-d",
            output_name,
        ],
        cwd=case_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def read_archive_manifest(path: Path) -> dict[str, dict[str, object]]:
    with zipfile.ZipFile(path, "r") as archive:
        return {
            name: {
                "size": len(archive.read(name)),
                "sha256": sha256_bytes(archive.read(name)),
            }
            for name in sorted(archive.namelist())
        }


def normalized_manifest_digest(manifest: dict[str, dict[str, object]]) -> str:
    return sha256_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def validate_positive(torch: Path, case_root: Path) -> tuple[str, str, bool]:
    first = run_torch(torch, case_root, "out_first")
    if first.returncode != 0:
        raise RuntimeError("positive fixture run 1 failed\n" + first.stdout + first.stderr)

    second = run_torch(torch, case_root, "out_second")
    if second.returncode != 0:
        raise RuntimeError("positive fixture run 2 failed\n" + second.stdout + second.stderr)

    first_archive = case_root / "out_first" / OUTPUT_NAME
    second_archive = case_root / "out_second" / OUTPUT_NAME
    if not first_archive.exists() or not second_archive.exists():
        raise RuntimeError("positive fixture did not produce expected O2R output")

    first_manifest = read_archive_manifest(first_archive)
    second_manifest = read_archive_manifest(second_archive)
    if first_manifest != second_manifest:
        raise RuntimeError("positive fixture O2R entry manifests differ across runs")

    names = set(first_manifest)
    if names != EXPECTED_ARCHIVE_ENTRIES:
        raise RuntimeError(f"positive fixture produced unexpected O2R entries: {sorted(names)}")
    if PLACEHOLDER_ENTRY in names:
        raise RuntimeError("skip_asset_export failed; placeholder bundle entry was exported")

    first_hash = sha256_bytes(first_archive.read_bytes())
    second_hash = sha256_bytes(second_archive.read_bytes())
    normalized_hash = normalized_manifest_digest(first_manifest)
    raw_archive_match = first_hash == second_hash

    first_torch_hash = (case_root / "out_first" / "torch.hash.yml").read_bytes()
    second_torch_hash = (case_root / "out_second" / "torch.hash.yml").read_bytes()
    if first_torch_hash != second_torch_hash:
        raise RuntimeError("torch.hash.yml differs across positive fixture runs")

    return normalized_hash, first_hash, raw_archive_match


def validate_negative(torch: Path, case_root: Path) -> str:
    result = run_torch(torch, case_root, "out_negative")
    combined_output = result.stdout + result.stderr
    expected = "primary model_root is missing from manifest: missing_model"
    if result.returncode == 0:
        raise RuntimeError("negative fixture unexpectedly succeeded")
    if expected not in combined_output:
        raise RuntimeError("negative fixture failed without the expected diagnostic\n" + combined_output)
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--torch", required=True, type=Path, help="Path to the built torch executable")
    parser.add_argument("--work-dir", type=Path, help="Directory for generated validation inputs and outputs")
    parser.add_argument("--keep-work", action="store_true", help="Keep the generated work directory")
    args = parser.parse_args()

    torch = args.torch.resolve()
    if not torch.is_file():
        print(f"torch executable not found: {torch}", file=sys.stderr)
        return 2

    temp_context = None
    if args.work_dir:
        work_root = args.work_dir.resolve()
        if work_root.exists():
            shutil.rmtree(work_root)
        work_root.mkdir(parents=True)
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="torch-ac-fixture-")
        work_root = Path(temp_context.name)

    try:
        positive_root = materialize_case("positive", work_root)
        negative_root = materialize_case("negative", work_root)

        normalized_hash, raw_hash, raw_archive_match = validate_positive(torch, positive_root)
        negative_message = validate_negative(torch, negative_root)

        print("positive: pass")
        print(f"deterministic-entry-manifest-sha256: {normalized_hash}")
        print(f"first-archive-sha256: {raw_hash}")
        print(f"raw-archive-byte-match: {str(raw_archive_match).lower()}")
        print(f"negative: pass ({negative_message})")
        print("skip_asset_export: pass (placeholder entry absent)")
        print("fixture-data: synthetic")
        if args.keep_work or args.work_dir:
            print(f"work-dir: {work_root}")
    finally:
        if temp_context is not None and not args.keep_work:
            temp_context.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
