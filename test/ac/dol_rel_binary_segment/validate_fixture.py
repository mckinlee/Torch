#!/usr/bin/env python3
"""Validate the synthetic AC DOL/REL binary-segment fixture."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
OUTPUT_NAME = "ac_dol_rel_binary_segment.o2r"
SYNTHETIC_SOURCE = b"AC_DOL_REL_SYNTHETIC_FIXTURE\n"
RESOURCE_TYPES = {
    "ADOL": 0x41444F4C,
    "AREL": 0x4152454C,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def fnv1a64(text: str) -> int:
    value = 1469598103934665603
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 1099511628211) & ((1 << 64) - 1)
    return value


def synthetic_bytes(entry: dict[str, object]) -> bytes:
    config_entry_id = str(entry["config_entry_id"])
    family = str(entry["synthetic_source_family"])
    kind = str(entry["synthetic_segment_kind"])
    offset = int(entry["synthetic_offset"])
    size = int(entry["synthetic_size"])
    seed = fnv1a64(f"{config_entry_id}|{family}|{kind}|{offset}")
    return bytes(((seed + offset + index * 37) & 0xFF) for index in range(size))


def parse_scalar(text: str) -> object:
    value = text.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("-") and value[1:].isdigit():
        return int(value)
    if value.isdigit():
        return int(value)
    return value


def quote_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def parse_root(text: str) -> dict[str, dict[str, object]]:
    root: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if not raw_line.startswith("  ") and raw_line.endswith(":"):
            name = raw_line[:-1]
            current = {}
            root[name] = current
            continue
        if raw_line.startswith("  ") and current is not None:
            key, value = raw_line.strip().split(":", 1)
            current[key] = parse_scalar(value)
            continue
        raise RuntimeError(f"unsupported fixture YAML line: {raw_line}")
    return root


def dump_yaml(root: dict[str, dict[str, object]]) -> str:
    lines: list[str] = []
    for name, entry in root.items():
        lines.append(f"{name}:")
        for key, value in entry.items():
            lines.append(f"  {key}: {quote_scalar(value)}")
        lines.append("")
    return "\n".join(lines)


def load_positive_root() -> dict[str, dict[str, object]]:
    return parse_root((FIXTURE_DIR / "positive" / "root.yml").read_text(encoding="utf-8"))


def dump_root(path: Path, root: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(root), encoding="utf-8")


def write_config(case_root: Path) -> None:
    (case_root / "config.yml").write_text(
        "\n".join(
            [
                "mode: directory",
                "folder: synthetic-ac-dol-rel-binary-segment",
                "path: assets",
                "config:",
                "  sort:",
                "    - AC:DOL_REL_BINARY_SEGMENT",
                "    - AC:DOL_REL_POLICY_METADATA",
                "  logging: CRITICAL",
                "  output:",
                f"    binary: {OUTPUT_NAME}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def materialize_case(case_name: str, work_root: Path, root: dict[str, dict[str, object]]) -> Path:
    case_root = work_root / case_name
    (case_root / "assets").mkdir(parents=True)
    (case_root / "source").mkdir(parents=True)
    dump_root(case_root / "assets" / "root.yml", root)
    (case_root / "source" / "synthetic.bin").write_bytes(SYNTHETIC_SOURCE)
    write_config(case_root)
    return case_root


def run_torch(torch: Path, case_root: Path, output_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(torch),
            "o2r",
            "source/synthetic.bin",
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


def binary_entries(root: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        name: entry
        for name, entry in root.items()
        if entry.get("type") == "AC:DOL_REL_BINARY_SEGMENT"
    }


def metadata_entries(root: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        name: entry
        for name, entry in root.items()
        if entry.get("type") == "AC:DOL_REL_POLICY_METADATA"
    }


def expected_archive_entries(root: dict[str, dict[str, object]]) -> set[str]:
    entries = {normalize_path(str(entry["destination_path"])) for entry in root.values()}
    entries.add("version")
    return entries


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


def resource_endian(header: bytes) -> str:
    byte_order = header[0]
    if byte_order == 0:
        return "little"
    if byte_order == 1:
        return "big"
    raise RuntimeError(f"unexpected resource byte order: {byte_order}")


def validate_binary_resource(archive: zipfile.ZipFile, entry: dict[str, object]) -> None:
    archive_path = normalize_path(str(entry["destination_path"]))
    data = archive.read(archive_path)
    if len(data) < 68:
        raise RuntimeError(f"binary resource too small: {archive_path}")

    endian = resource_endian(data)
    expected_type = RESOURCE_TYPES[str(entry["resource_type_id"])]
    actual_type = int.from_bytes(data[4:8], endian)
    if actual_type != expected_type:
        raise RuntimeError(f"resource type mismatch for {archive_path}: {actual_type:08X}")

    actual_version = int.from_bytes(data[8:12], endian, signed=True)
    if actual_version != int(entry["resource_version"]):
        raise RuntimeError(f"resource version mismatch for {archive_path}: {actual_version}")

    actual_size = int.from_bytes(data[64:68], endian)
    expected = synthetic_bytes(entry)
    if actual_size != len(expected):
        raise RuntimeError(f"resource size mismatch for {archive_path}: {actual_size}")
    if data[68:] != expected:
        raise RuntimeError(f"synthetic data mismatch for {archive_path}")
    if sha256_bytes(expected) != entry["synthetic_sha256"]:
        raise RuntimeError(f"synthetic sha256 mismatch for {archive_path}")


def validate_metadata_resource(archive: zipfile.ZipFile, entry: dict[str, object]) -> None:
    archive_path = normalize_path(str(entry["destination_path"]))
    document = json.loads(archive.read(archive_path).decode("utf-8"))
    expected_fields = [
        "archive_version",
        "backend_window_context_status",
        "config_entry_id",
        "destination_path",
        "game_payload_status",
        "generated_output_policy",
        "generated_output_root",
        "legal_payload_policy",
        "phase6n_readiness_status",
        "policy_kind",
        "real_source_read_status",
        "renderer_upload_status",
        "resource_type_id",
        "resource_type_name",
        "resource_version",
        "runtime_routing_status",
        "synthetic_source_family",
        "texture_factory_readiness_status",
        "township_runtime_routing_status",
    ]
    for field in expected_fields:
        if field not in document:
            raise RuntimeError(f"metadata field missing for {archive_path}: {field}")
    if document["destination_path"] != archive_path:
        raise RuntimeError(f"metadata destination mismatch for {archive_path}")
    if document["config_entry_id"] != entry["config_entry_id"]:
        raise RuntimeError(f"metadata config entry mismatch for {archive_path}")
    if document["policy_kind"] != entry["policy_kind"]:
        raise RuntimeError(f"metadata policy kind mismatch for {archive_path}")


def validate_positive(torch: Path, case_root: Path, root: dict[str, dict[str, object]]) -> tuple[str, str, bool]:
    if "source_image_path" in (FIXTURE_DIR / "positive" / "root.yml").read_text(encoding="utf-8"):
        raise RuntimeError("positive fixture unexpectedly contains source_image_path")

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
    expected = expected_archive_entries(root)
    if names != expected:
        raise RuntimeError(f"positive fixture produced unexpected O2R entries: {sorted(names)}")

    with zipfile.ZipFile(first_archive, "r") as archive:
        for entry in binary_entries(root).values():
            validate_binary_resource(archive, entry)
        for entry in metadata_entries(root).values():
            validate_metadata_resource(archive, entry)

    first_hash = sha256_bytes(first_archive.read_bytes())
    second_hash = sha256_bytes(second_archive.read_bytes())
    raw_archive_match = first_hash == second_hash

    first_torch_hash = (case_root / "out_first" / "torch.hash.yml").read_bytes()
    second_torch_hash = (case_root / "out_second" / "torch.hash.yml").read_bytes()
    if first_torch_hash != second_torch_hash:
        raise RuntimeError("torch.hash.yml differs across positive fixture runs")

    return normalized_manifest_digest(first_manifest), first_hash, raw_archive_match


def first_binary(root: dict[str, dict[str, object]]) -> dict[str, object]:
    return root["dol_header_binary_segment"]


def run_negative_case(torch: Path, work_root: Path, name: str, root: dict[str, dict[str, object]], expected: str) -> None:
    case_root = materialize_case(f"negative_{name}", work_root, root)
    result = run_torch(torch, case_root, "out_negative")
    combined_output = result.stdout + result.stderr
    archive = case_root / "out_negative" / OUTPUT_NAME
    if result.returncode == 0:
        raise RuntimeError(f"negative fixture unexpectedly succeeded: {name}")
    if expected not in combined_output:
        raise RuntimeError(f"negative fixture failed without expected diagnostic for {name}\n{combined_output}")
    if archive.exists():
        raise RuntimeError(f"negative fixture left an archive behind: {name}")


def negative_cases(base: dict[str, dict[str, object]]) -> list[tuple[str, dict[str, dict[str, object]], str]]:
    cases: list[tuple[str, dict[str, dict[str, object]], str]] = []

    def add(name: str, mutate, expected: str) -> None:
        root = copy.deepcopy(base)
        mutate(root)
        cases.append((name, root, expected))

    add("missing_config_entry_id", lambda root: first_binary(root).pop("config_entry_id"), "config_entry_id")
    add("missing_synthetic_source_family", lambda root: first_binary(root).pop("synthetic_source_family"), "synthetic_source_family")
    add("unsupported_synthetic_source_family", lambda root: first_binary(root).__setitem__("synthetic_source_family", "fst"), "unsupported synthetic_source_family")
    add("missing_segment_kind", lambda root: first_binary(root).pop("synthetic_segment_kind"), "synthetic_segment_kind")
    add("unsupported_segment_kind", lambda root: first_binary(root).__setitem__("synthetic_segment_kind", "unknown_segment"), "unsupported synthetic_segment_kind")
    add("missing_resource_type_placeholder", lambda root: first_binary(root).pop("resource_type_id"), "resource_type_id")
    add("unsupported_resource_type_placeholder", lambda root: first_binary(root).__setitem__("resource_type_id", "XXXX"), "resource_type_id must be")
    add("invalid_resource_version", lambda root: first_binary(root).__setitem__("resource_version", 1), "resource_version must be 0")
    add("missing_archive_version", lambda root: first_binary(root).pop("archive_version"), "archive_version")
    add("invalid_archive_version", lambda root: first_binary(root).__setitem__("archive_version", "bad-version"), "archive_version must be")
    add("invalid_synthetic_offset", lambda root: first_binary(root).__setitem__("synthetic_offset", -1), "invalid synthetic_offset")
    add("invalid_synthetic_size", lambda root: first_binary(root).__setitem__("synthetic_size", 0), "synthetic_size must be")
    add("offset_size_overflow", lambda root: (first_binary(root).__setitem__("synthetic_offset", 18446744073709551610), first_binary(root).__setitem__("synthetic_size", 16)), "overflows")
    add("missing_synthetic_sha256", lambda root: first_binary(root).pop("synthetic_sha256"), "synthetic_sha256")
    add("malformed_synthetic_sha256", lambda root: first_binary(root).__setitem__("synthetic_sha256", "abc"), "synthetic_sha256 must be")
    add("path_traversal", lambda root: first_binary(root).__setitem__("destination_path", "__OTR__ac/dol_rel/../bad.ADOL"), "escapes output root")
    add("absolute_output_path", lambda root: first_binary(root).__setitem__("destination_path", "C:/absolute/bad.ADOL"), "destination_path must be relative")
    add("duplicate_output_path", lambda root: root["dol_body_sample_binary_segment"].__setitem__("destination_path", root["dol_header_binary_segment"]["destination_path"]), "duplicate output path")
    add("missing_generated_output_policy", lambda root: first_binary(root).pop("generated_output_policy"), "generated_output_policy")
    add("missing_legal_payload_policy", lambda root: first_binary(root).pop("legal_payload_policy"), "legal_payload_policy")
    add("policy_claims_real_payload", lambda root: first_binary(root).__setitem__("legal_payload_policy", "real-payload"), "legal_payload_policy must be")
    add("real_source_read_claim", lambda root: first_binary(root).__setitem__("real_source_read_status", "read"), "real_source_read_status must be")
    add("game_payload_claim", lambda root: first_binary(root).__setitem__("game_payload_status", "present"), "game_payload_status must be")
    add("runtime_routing_active", lambda root: first_binary(root).__setitem__("runtime_routing_status", "active"), "runtime_routing_status must be")
    add("texture_factory_ready", lambda root: first_binary(root).__setitem__("texture_factory_readiness_status", "ready"), "texture_factory_readiness_status must be")
    add("phase6n_ready", lambda root: first_binary(root).__setitem__("phase6n_readiness_status", "ready"), "phase6n_readiness_status must be")
    add("renderer_upload_executed", lambda root: first_binary(root).__setitem__("renderer_upload_status", "executed"), "renderer_upload_status must be")
    add("backend_window_context_created", lambda root: first_binary(root).__setitem__("backend_window_context_status", "created"), "backend_window_context_status must be")
    add("generated_output_outside_root", lambda root: first_binary(root).__setitem__("generated_output_root", "../outside"), "generated_output_root escapes")
    add("source_image_required", lambda root: first_binary(root).__setitem__("source_image_required", True), "source_image_required must be false")
    add("source_image_path_set", lambda root: first_binary(root).__setitem__("source_image_path", "local-game-source"), "source_image_path must not be set")
    add("township_runtime_dependency", lambda root: first_binary(root).__setitem__("requires_township_runtime", True), "requires_township_runtime must be false")
    return cases


def validate_negative(torch: Path, work_root: Path, root: dict[str, dict[str, object]]) -> int:
    cases = negative_cases(root)
    for name, mutated_root, expected in cases:
        run_negative_case(torch, work_root, name, mutated_root, expected)
    return len(cases)


def assert_no_source_image_required(work_root: Path) -> None:
    forbidden_suffixes = {"." + "iso", "." + "gcm", "." + "ciso", "." + "nkit" + "." + "iso"}
    for path in work_root.rglob("*"):
        if path.is_file() and any(path.name.endswith(suffix) for suffix in forbidden_suffixes):
            raise RuntimeError(f"unexpected source image file in fixture work tree: {path}")


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
        temp_context = tempfile.TemporaryDirectory(prefix="torch-ac-dol-rel-fixture-")
        work_root = Path(temp_context.name)

    try:
        root = load_positive_root()
        positive_root = materialize_case("positive", work_root, root)

        normalized_hash, raw_hash, raw_archive_match = validate_positive(torch, positive_root, root)
        negative_count = validate_negative(torch, work_root, root)
        assert_no_source_image_required(work_root)

        print("positive: pass")
        print(f"binary-segment-count: {len(binary_entries(root))}")
        print(f"policy-metadata-count: {len(metadata_entries(root))}")
        print(f"negative: pass ({negative_count}/{negative_count})")
        print(f"deterministic-entry-manifest-sha256: {normalized_hash}")
        print(f"first-archive-sha256: {raw_hash}")
        print(f"raw-archive-byte-match: {str(raw_archive_match).lower()}")
        print("source-image-required: false")
        print("real-source-read: absent")
        print("game-payload: absent")
        print("runtime-routing: blocked")
        print("texture-factory-readiness: blocked")
        print("phase6n-readiness: blocked")
        print("renderer-upload: not executed")
        print("backend-window-context: not created")
        print("fixture-data: synthetic")
        if args.keep_work or args.work_dir:
            print(f"work-dir: {work_root}")
    finally:
        if temp_context is not None and not args.keep_work:
            temp_context.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
