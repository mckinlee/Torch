#!/usr/bin/env python3
"""Validate the synthetic AC DOL/REL binary-segment fixture."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
OUTPUT_NAME = "ac_dol_rel_binary_segment.o2r"
REAL_OUTPUT_NAME = "ac_dol_real_source.o2r"
SYNTHETIC_SOURCE = b"AC_DOL_REL_SYNTHETIC_FIXTURE\n"
RESOURCE_TYPES = {
    "ADOL": 0x41444F4C,
    "AREL": 0x4152454C,
}
REAL_SOURCE_LABEL = "GAFE01_00_user_supplied_disc_image"
REAL_SOURCE_IMAGE_SHA256 = "ca870a9c11ae26cd4d3fb94befd7ecbd075c36244589061d22e3ddc4552dc379"
REAL_SOURCE_IMAGE_SIZE = 1459978240
REAL_GAME_ID = "GAFE01"
REAL_CANONICAL_VERSION = "GAFE01_00"
REAL_GENERATED_ROOT = "generated/dol-rel-first-factory"
REAL_LEGAL_POLICY = "legal-user-supplied-dol-slice-local-only"
REAL_SOURCE_READ_STATUS = "verified-before-serialization"
REAL_GAME_PAYLOAD_STATUS = "bounded-dol-slice-local-only"
REAL_DOL_NAMESPACE = "__OTR__ac/dol_rel/binary_segment/dol"
REAL_TOTAL_SOURCE_BYTES = 48
REAL_SOURCE_ENV_VAR = "AC_DOL_REAL_SOURCE_IMAGE"
REAL_EVIDENCE = {
    "dol_source_header_slice_evidence": {
        "offset": 122880,
        "size": 16,
        "sha256": "630c92a2e310b030e9f1ddbf5aea8e617b9d9b2af2daef70ff37a84e37f56c5b",
        "classification": "dol_header",
        "destination_path": "__OTR__ac/dol_rel/binary_segment/dol/dol_source_header_slice_evidence.ADOL",
    },
    "dol_source_body_sample_slice_evidence": {
        "offset": 122944,
        "size": 32,
        "sha256": "83d562b265b659e236087730a630e4225687322a78d01eb4e287e36b678cbe1e",
        "classification": "dol_body_sample",
        "destination_path": "__OTR__ac/dol_rel/binary_segment/dol/dol_source_body_sample_slice_evidence.ADOL",
    },
}
REAL_POLICY_PATHS = {
    "policy_generated_output_boundary": (
        "generated_output_boundary",
        "__OTR__ac/validation/dol_rel/policy/generated_output_boundary.json",
    ),
    "policy_legal_payload_boundary": (
        "legal_payload_boundary",
        "__OTR__ac/validation/dol_rel/policy/legal_payload_boundary.json",
    ),
    "policy_runtime_routing_blocker": (
        "runtime_routing_blocker",
        "__OTR__ac/validation/dol_rel/policy/runtime_routing_blocker.json",
    ),
    "factory_output_first_dol_only_report": (
        "first_dol_only_factory_report",
        "__OTR__ac/validation/dol_rel/factory_output/first_dol_only_factory_report.json",
    ),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def read_source_slice(source: Path, offset: int, size: int) -> bytes:
    with source.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(size)
    if len(data) != size:
        raise RuntimeError(f"source slice read was short at offset {offset}")
    return data


def real_source_identity(source: Path) -> dict[str, object]:
    size = source.stat().st_size
    source_hash = sha256_file(source)
    if size != REAL_SOURCE_IMAGE_SIZE:
        raise RuntimeError(f"unexpected source image size: {size}")
    if source_hash != REAL_SOURCE_IMAGE_SHA256:
        raise RuntimeError(f"unexpected source image sha256: {source_hash}")
    for evidence_id, evidence in REAL_EVIDENCE.items():
        data = read_source_slice(source, int(evidence["offset"]), int(evidence["size"]))
        actual = sha256_bytes(data)
        if actual != evidence["sha256"]:
            raise RuntimeError(f"source slice sha256 mismatch for {evidence_id}")
    return {
        "normalized_source_path_label": REAL_SOURCE_LABEL,
        "source_image_byte_size": size,
        "source_image_sha256": source_hash,
        "game_id": REAL_GAME_ID,
        "canonical_version": REAL_CANONICAL_VERSION,
    }


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


def write_config(case_root: Path, output_name: str = OUTPUT_NAME) -> None:
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
                f"    binary: {output_name}",
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


def run_torch(
    torch: Path,
    case_root: Path,
    output_dir: Path | str,
    source_arg: str = "source/synthetic.bin",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [
            str(torch),
            "o2r",
            source_arg,
            "-s",
            ".",
            "-d",
            str(output_dir),
        ],
        cwd=case_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=run_env,
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


def real_binary_entry(evidence_id: str, source: Path, identity: dict[str, object]) -> dict[str, object]:
    evidence = REAL_EVIDENCE[evidence_id]
    return {
        "type": "AC:DOL_REL_BINARY_SEGMENT",
        "path": "source/placeholder.bin",
        "offset": 0,
        "size": 1,
        "config_entry_id": evidence_id,
        "real_source_mode": True,
        "source_image_required": True,
        "source_image_env_var": REAL_SOURCE_ENV_VAR,
        "source_family": "dol",
        "source_family_count": 1,
        "source_slice_count": 2,
        "total_source_byte_count": REAL_TOTAL_SOURCE_BYTES,
        "normalized_source_path_label": identity["normalized_source_path_label"],
        "source_image_sha256": identity["source_image_sha256"],
        "source_image_byte_size": identity["source_image_byte_size"],
        "game_id": identity["game_id"],
        "canonical_version": identity["canonical_version"],
        "source_evidence_id": evidence_id,
        "source_offset": evidence["offset"],
        "source_size": evidence["size"],
        "source_sha256": evidence["sha256"],
        "source_byte_count": evidence["size"],
        "endian_policy": "big_endian_resource_header",
        "byte_swap_policy": "no_byte_swap",
        "dol_classification": evidence["classification"],
        "destination_namespace": REAL_DOL_NAMESPACE,
        "destination_path": evidence["destination_path"],
        "generated_output_root": REAL_GENERATED_ROOT,
        "generated_output_policy": "ignored-local-only",
        "legal_payload_policy": REAL_LEGAL_POLICY,
        "factory_name": "AC:DOL_REL_BINARY_SEGMENT",
        "resource_class": "dol_binary_segment",
        "resource_type_name": "AcDolBinarySegment",
        "resource_type_id": "ADOL",
        "resource_version": 0,
        "archive_version": "ac-dol-rel-binary-segment-v0",
        "runtime_routing_status": "blocked",
        "runtime_dvd_resource_replacement_status": "blocked",
        "texture_factory_readiness_status": "blocked",
        "phase6n_readiness_status": "blocked",
        "renderer_upload_status": "not executed",
        "backend_window_context_status": "not created",
        "real_source_read_status": REAL_SOURCE_READ_STATUS,
        "game_payload_status": REAL_GAME_PAYLOAD_STATUS,
        "township_runtime_routing_status": "not implied",
        "report_log_payload_status": "absent",
        "lus_typed_registration_status": "blocked",
        "requires_township_runtime": False,
    }


def real_policy_entry(name: str, identity: dict[str, object]) -> dict[str, object]:
    policy_kind, destination_path = REAL_POLICY_PATHS[name]
    return {
        "type": "AC:DOL_REL_POLICY_METADATA",
        "path": "source/placeholder.bin",
        "offset": 0,
        "size": 1,
        "config_entry_id": name,
        "real_source_mode": True,
        "source_image_required": False,
        "source_family": "dol",
        "source_family_count": 1,
        "source_slice_count": 2,
        "total_source_byte_count": REAL_TOTAL_SOURCE_BYTES,
        "source_byte_cap_per_slice": 64,
        "source_total_byte_cap": 128,
        "normalized_source_path_label": identity["normalized_source_path_label"],
        "source_image_sha256": identity["source_image_sha256"],
        "source_image_byte_size": identity["source_image_byte_size"],
        "game_id": identity["game_id"],
        "canonical_version": identity["canonical_version"],
        "source_evidence_id": ",".join(REAL_EVIDENCE.keys()),
        "policy_kind": policy_kind,
        "destination_path": destination_path,
        "generated_output_root": REAL_GENERATED_ROOT,
        "generated_output_policy": "ignored-local-only",
        "legal_payload_policy": REAL_LEGAL_POLICY,
        "resource_type_name": "AcDolRelPolicyMetadata",
        "resource_type_id": "AMET",
        "resource_version": 0,
        "archive_version": "ac-dol-rel-policy-metadata-v0",
        "runtime_routing_status": "blocked",
        "runtime_dvd_resource_replacement_status": "blocked",
        "texture_factory_readiness_status": "blocked",
        "phase6n_readiness_status": "blocked",
        "renderer_upload_status": "not executed",
        "backend_window_context_status": "not created",
        "real_source_read_status": REAL_SOURCE_READ_STATUS,
        "game_payload_status": REAL_GAME_PAYLOAD_STATUS,
        "township_runtime_routing_status": "not implied",
        "report_log_payload_status": "absent",
        "lus_typed_registration_status": "blocked",
        "requires_township_runtime": False,
    }


def real_source_root(source: Path) -> dict[str, dict[str, object]]:
    identity = real_source_identity(source)
    root: dict[str, dict[str, object]] = {
        "dol_source_header_slice_evidence": real_binary_entry("dol_source_header_slice_evidence", source, identity),
        "dol_source_body_sample_slice_evidence": real_binary_entry(
            "dol_source_body_sample_slice_evidence", source, identity
        ),
    }
    for name in REAL_POLICY_PATHS:
        root[name] = real_policy_entry(name, identity)
    return root


def materialize_real_case(case_name: str, work_root: Path, root: dict[str, dict[str, object]]) -> Path:
    case_root = work_root / case_name
    (case_root / "assets").mkdir(parents=True)
    (case_root / "source").mkdir(parents=True)
    dump_root(case_root / "assets" / "root.yml", root)
    (case_root / "source" / "placeholder.bin").write_bytes(b"AC_DOL_REAL_SOURCE_LOCAL_PLACEHOLDER\n")
    write_config(case_root, REAL_OUTPUT_NAME)
    return case_root


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


def validate_binary_resource(archive: zipfile.ZipFile, entry: dict[str, object], source: Path | None = None) -> None:
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
    if entry.get("real_source_mode") is True:
        if source is None:
            raise RuntimeError(f"source path missing for real-source validation: {archive_path}")
        expected = read_source_slice(
            source,
            int(entry["source_offset"]),
            int(entry["source_size"]),
        )
        if sha256_bytes(expected) != entry["source_sha256"]:
            raise RuntimeError(f"source sha256 mismatch for {archive_path}")
    else:
        expected = synthetic_bytes(entry)
    if actual_size != len(expected):
        raise RuntimeError(f"resource size mismatch for {archive_path}: {actual_size}")
    if data[68:] != expected:
        raise RuntimeError(f"binary payload mismatch for {archive_path}")
    if entry.get("real_source_mode") is not True and sha256_bytes(expected) != entry["synthetic_sha256"]:
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
        "texture_factory_readiness_status",
        "township_runtime_routing_status",
    ]
    if entry.get("real_source_mode") is True:
        expected_fields.extend(
            [
                "real_source_mode",
                "source_family",
                "normalized_source_path_label",
                "source_image_sha256",
                "source_image_byte_size",
                "game_id",
                "canonical_version",
                "source_evidence_id",
                "source_family_count",
                "source_slice_count",
                "total_source_byte_count",
                "source_byte_cap_per_slice",
                "source_total_byte_cap",
                "runtime_dvd_resource_replacement_status",
                "report_log_payload_status",
                "lus_typed_registration_status",
            ]
        )
    else:
        expected_fields.append("synthetic_source_family")
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


def write_run_log(path: Path, result: subprocess.CompletedProcess[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"returncode: {result.returncode}",
                "stdout:",
                result.stdout,
                "stderr:",
                result.stderr,
            ]
        ),
        encoding="utf-8",
    )


def write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def public_entry_manifest(archive_path: Path) -> dict[str, dict[str, object]]:
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest: dict[str, dict[str, object]] = {}
        for name in sorted(archive.namelist()):
            payload = archive.read(name)
            resource_type = ""
            version = None
            if name.endswith(".ADOL"):
                endian = resource_endian(payload)
                resource_type = f"{int.from_bytes(payload[4:8], endian):08X}"
                version = int.from_bytes(payload[8:12], endian, signed=True)
            manifest[name] = {
                "byte_count": len(payload),
                "payload_sha256": sha256_bytes(payload),
                "resource_type_id": resource_type,
                "version": version,
            }
    return manifest


def archive_container_difference_reason(first_archive: Path, second_archive: Path) -> str:
    with zipfile.ZipFile(first_archive, "r") as first, zipfile.ZipFile(second_archive, "r") as second:
        first_infos = {info.filename: info for info in first.infolist()}
        second_infos = {info.filename: info for info in second.infolist()}
        if set(first_infos) != set(second_infos):
            return "archive_entry_name_mismatch"
        timestamp_difference = False
        for name in sorted(first_infos):
            left = first_infos[name]
            right = second_infos[name]
            left_fields = (
                left.compress_type,
                left.comment,
                left.extra,
                left.create_system,
                left.extract_version,
                getattr(left, "reserved", None),
                left.flag_bits,
                getattr(left, "volume", None),
                left.internal_attr,
                left.external_attr,
                left.header_offset,
                left.CRC,
                left.compress_size,
                left.file_size,
            )
            right_fields = (
                right.compress_type,
                right.comment,
                right.extra,
                right.create_system,
                right.extract_version,
                getattr(right, "reserved", None),
                right.flag_bits,
                getattr(right, "volume", None),
                right.internal_attr,
                right.external_attr,
                right.header_offset,
                right.CRC,
                right.compress_size,
                right.file_size,
            )
            if left_fields != right_fields:
                return "zip_entry_metadata_mismatch"
            if left.date_time != right.date_time:
                timestamp_difference = True
        if timestamp_difference:
            return "zip_entry_timestamps_only"
    return "unknown_raw_o2r_difference"


def scan_no_payload_leakage(paths: list[Path], source: Path) -> None:
    markers: set[str] = set()
    for evidence in REAL_EVIDENCE.values():
        payload = read_source_slice(source, int(evidence["offset"]), int(evidence["size"]))
        markers.add(payload.hex())
        markers.add(base64.b64encode(payload).decode("ascii"))
    hex_dump = re.compile(r"(?i)(?:[0-9a-f]{2}[\s,:\"]+){16,}")
    base64_dump = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in markers:
            if marker and marker in text:
                raise RuntimeError(f"payload marker leaked into {path}")
        if hex_dump.search(text):
            raise RuntimeError(f"long hex dump found in {path}")
        if base64_dump.search(text):
            raise RuntimeError(f"long base64 payload found in {path}")


def validate_real_positive(
    torch: Path,
    source: Path,
    work_root: Path,
    archive_root: Path,
    reports_dir: Path,
    logs_dir: Path,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    root = real_source_root(source)
    case_root = materialize_real_case("real_source_positive", work_root, root)

    for output in [archive_root / "run-a", archive_root / "run-b"]:
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)

    source_env = {REAL_SOURCE_ENV_VAR: str(source)}
    first = run_torch(torch, case_root, archive_root / "run-a", "source/placeholder.bin", source_env)
    write_run_log(logs_dir / "real_source_run_a.log", first)
    if first.returncode != 0:
        raise RuntimeError("real-source fixture run 1 failed\n" + first.stdout + first.stderr)

    second = run_torch(torch, case_root, archive_root / "run-b", "source/placeholder.bin", source_env)
    write_run_log(logs_dir / "real_source_run_b.log", second)
    if second.returncode != 0:
        raise RuntimeError("real-source fixture run 2 failed\n" + second.stdout + second.stderr)

    first_archive = archive_root / "run-a" / REAL_OUTPUT_NAME
    second_archive = archive_root / "run-b" / REAL_OUTPUT_NAME
    if not first_archive.exists() or not second_archive.exists():
        raise RuntimeError("real-source fixture did not produce expected O2R output")

    first_manifest = read_archive_manifest(first_archive)
    second_manifest = read_archive_manifest(second_archive)
    if first_manifest != second_manifest:
        raise RuntimeError("real-source O2R entry manifests differ across runs")

    names = set(first_manifest)
    expected = expected_archive_entries(root)
    if names != expected:
        raise RuntimeError(f"real-source fixture produced unexpected O2R entries: {sorted(names)}")
    if any(name.endswith(".AREL") or "/rel/" in name for name in names):
        raise RuntimeError("real-source fixture produced REL output")

    with zipfile.ZipFile(first_archive, "r") as archive:
        for entry in binary_entries(root).values():
            validate_binary_resource(archive, entry, source)
        for entry in metadata_entries(root).values():
            validate_metadata_resource(archive, entry)

    first_hash = sha256_bytes(first_archive.read_bytes())
    second_hash = sha256_bytes(second_archive.read_bytes())
    raw_archive_match = first_hash == second_hash
    container_nondeterminism = "none"
    if not raw_archive_match:
        container_nondeterminism = archive_container_difference_reason(first_archive, second_archive)
        if container_nondeterminism != "zip_entry_timestamps_only":
            raise RuntimeError(f"real-source raw O2R bytes differ: {container_nondeterminism}")

    entry_manifest = public_entry_manifest(first_archive)
    entry_manifest_hash = normalized_manifest_digest(entry_manifest)
    write_json(reports_dir / "real_source_entry_manifest_run_a.json", entry_manifest)
    write_json(reports_dir / "real_source_entry_manifest_run_b.json", public_entry_manifest(second_archive))
    write_json(
        reports_dir / "first_dol_only_factory_report.json",
        {
            "archive_version": "ac-dol-rel-binary-segment-v0",
            "approved_source_evidence_ids": sorted(REAL_EVIDENCE),
            "archive_entry_paths": sorted(name for name in names if name != "version"),
            "canonical_version": REAL_CANONICAL_VERSION,
            "deterministic_entry_manifest_sha256": entry_manifest_hash,
            "game_id": REAL_GAME_ID,
            "generated_output_root": REAL_GENERATED_ROOT,
            "metadata_entry_count": len(metadata_entries(root)),
            "normalized_source_path_label": REAL_SOURCE_LABEL,
            "raw_archive_byte_match": raw_archive_match,
            "raw_archive_sha256": first_hash,
            "raw_archive_sha256_run_b": second_hash,
            "raw_o2r_nondeterminism": container_nondeterminism,
            "resource_type_id": "ADOL",
            "resource_type_name": "AcDolBinarySegment",
            "resource_version": 0,
            "source_family": "dol",
            "source_image_byte_size": REAL_SOURCE_IMAGE_SIZE,
            "source_image_sha256": REAL_SOURCE_IMAGE_SHA256,
            "source_slice_count": len(REAL_EVIDENCE),
            "source_total_byte_count": REAL_TOTAL_SOURCE_BYTES,
        },
    )

    scan_no_payload_leakage(
        [
            reports_dir / "real_source_entry_manifest_run_a.json",
            reports_dir / "real_source_entry_manifest_run_b.json",
            reports_dir / "first_dol_only_factory_report.json",
            logs_dir / "real_source_run_a.log",
            logs_dir / "real_source_run_b.log",
        ],
        source,
    )

    return {
        "deterministic_entry_manifest_sha256": entry_manifest_hash,
        "raw_archive_sha256": first_hash,
        "raw_archive_sha256_run_b": second_hash,
        "raw_archive_byte_match": raw_archive_match,
        "raw_o2r_nondeterminism": container_nondeterminism,
        "archive_path": str(first_archive),
    }, root


def first_binary(root: dict[str, dict[str, object]]) -> dict[str, object]:
    return root["dol_header_binary_segment"]


def first_real_binary(root: dict[str, dict[str, object]]) -> dict[str, object]:
    return root["dol_source_header_slice_evidence"]


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


def run_real_negative_case(
    torch: Path,
    work_root: Path,
    source: Path,
    name: str,
    root: dict[str, dict[str, object]],
    expected: str,
) -> None:
    case_root = materialize_real_case(f"real_negative_{name}", work_root, root)
    output_dir = case_root / "out_negative"
    result = run_torch(
        torch,
        case_root,
        output_dir,
        "source/placeholder.bin",
        {REAL_SOURCE_ENV_VAR: str(source)},
    )
    combined_output = result.stdout + result.stderr
    archive = output_dir / REAL_OUTPUT_NAME
    if result.returncode == 0:
        raise RuntimeError(f"real-source negative fixture unexpectedly succeeded: {name}")
    if expected not in combined_output:
        raise RuntimeError(f"real-source negative fixture failed without expected diagnostic for {name}\n{combined_output}")
    if archive.exists():
        raise RuntimeError(f"real-source negative fixture left an archive behind: {name}")


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


def real_negative_cases(base: dict[str, dict[str, object]]) -> list[tuple[str, dict[str, dict[str, object]], str]]:
    cases: list[tuple[str, dict[str, dict[str, object]], str]] = []

    def add(name: str, mutate, expected: str) -> None:
        root = copy.deepcopy(base)
        mutate(root)
        cases.append((name, root, expected))

    add("missing_source_image", lambda root: first_real_binary(root).pop("source_image_env_var"), "source_image_env_var")
    add("serialized_source_image_path", lambda root: first_real_binary(root).__setitem__("source_image_path", "local-source"), "source_image_path must not be serialized")
    add("wrong_source_image_hash", lambda root: first_real_binary(root).__setitem__("source_image_sha256", "0" * 64), "source_image_sha256 does not match")
    add("unsupported_source_family", lambda root: first_real_binary(root).__setitem__("source_family", "fst"), "source_family must be")
    add("rel_source_family_requested", lambda root: first_real_binary(root).__setitem__("source_family", "rel"), "source_family must be")
    add("mixed_dol_rel_requested", lambda root: first_real_binary(root).__setitem__("source_families", "dol,rel"), "mixed DOL/REL source families")
    add("missing_source_evidence_id", lambda root: first_real_binary(root).pop("source_evidence_id"), "source_evidence_id")
    add("unsupported_source_evidence_id", lambda root: first_real_binary(root).__setitem__("source_evidence_id", "rel_module_header_slice_evidence"), "unsupported source_evidence_id")
    add("missing_source_offset", lambda root: first_real_binary(root).pop("source_offset"), "source_offset")
    add("invalid_source_offset", lambda root: first_real_binary(root).__setitem__("source_offset", -1), "invalid source_offset")
    add("missing_source_size", lambda root: first_real_binary(root).pop("source_size"), "source_size")
    add("invalid_source_size", lambda root: first_real_binary(root).__setitem__("source_size", 0), "source_size must be")
    add(
        "offset_plus_size_overflow",
        lambda root: (first_real_binary(root).__setitem__("source_offset", 18446744073709551610), first_real_binary(root).__setitem__("source_size", 16)),
        "source_offset plus source_size overflows",
    )
    add("source_size_above_cap", lambda root: first_real_binary(root).__setitem__("source_size", 65), "source_size must be")
    add("total_source_bytes_above_cap", lambda root: first_real_binary(root).__setitem__("total_source_byte_count", 129), "total_source_byte_count must be")
    add("more_than_two_slices", lambda root: first_real_binary(root).__setitem__("source_slice_count", 3), "source_slice_count must be")
    add("source_sha_mismatch", lambda root: first_real_binary(root).__setitem__("source_sha256", "0" * 64), "source_sha256 does not match")
    add("missing_legal_payload_policy", lambda root: first_real_binary(root).pop("legal_payload_policy"), "legal_payload_policy")
    add("missing_generated_output_policy", lambda root: first_real_binary(root).pop("generated_output_policy"), "generated_output_policy")
    add("generated_output_outside_ignored_root", lambda root: first_real_binary(root).__setitem__("generated_output_root", "../outside"), "generated_output_root escapes")
    add("absolute_archive_path", lambda root: first_real_binary(root).__setitem__("destination_path", "C:/absolute/bad.ADOL"), "destination_path must be relative")
    add("path_traversal", lambda root: first_real_binary(root).__setitem__("destination_path", "__OTR__ac/dol_rel/../bad.ADOL"), "escapes output root")
    add(
        "duplicate_archive_path",
        lambda root: root["policy_legal_payload_boundary"].__setitem__(
            "destination_path",
            root["policy_generated_output_boundary"]["destination_path"],
        ),
        "duplicate output path",
    )
    add("report_log_payload_dump_attempt", lambda root: first_real_binary(root).__setitem__("report_log_payload_status", "present"), "report_log_payload_status must be")
    add("unsupported_archive_version", lambda root: first_real_binary(root).__setitem__("archive_version", "bad-version"), "archive_version must be")
    add("arel_output_attempted", lambda root: first_real_binary(root).__setitem__("resource_type_id", "AREL"), "resource_type_id must be")
    add("runtime_routing_active", lambda root: first_real_binary(root).__setitem__("runtime_routing_status", "active"), "runtime_routing_status must be")
    add(
        "runtime_dvd_resource_replacement_active",
        lambda root: first_real_binary(root).__setitem__("runtime_dvd_resource_replacement_status", "active"),
        "runtime_dvd_resource_replacement_status must be",
    )
    add("texture_factory_ready", lambda root: first_real_binary(root).__setitem__("texture_factory_readiness_status", "ready"), "texture_factory_readiness_status must be")
    add("phase6n_ready", lambda root: first_real_binary(root).__setitem__("phase6n_readiness_status", "ready"), "phase6n_readiness_status must be")
    add("renderer_upload_executed", lambda root: first_real_binary(root).__setitem__("renderer_upload_status", "executed"), "renderer_upload_status must be")
    add("backend_window_context_created", lambda root: first_real_binary(root).__setitem__("backend_window_context_status", "created"), "backend_window_context_status must be")
    add("lus_typed_registration_attempted", lambda root: first_real_binary(root).__setitem__("lus_typed_registration_status", "attempted"), "lus_typed_registration_status must be")
    add("township_runtime_dependency_claimed", lambda root: first_real_binary(root).__setitem__("requires_township_runtime", True), "requires_township_runtime must be false")
    return cases


def validate_negative(torch: Path, work_root: Path, root: dict[str, dict[str, object]]) -> int:
    cases = negative_cases(root)
    for name, mutated_root, expected in cases:
        run_negative_case(torch, work_root, name, mutated_root, expected)
    return len(cases)


def validate_real_negative(torch: Path, work_root: Path, source: Path, root: dict[str, dict[str, object]]) -> int:
    cases = real_negative_cases(root)
    for name, mutated_root, expected in cases:
        run_real_negative_case(torch, work_root, source, name, mutated_root, expected)
    return len(cases)


def validate_payload_leak_scan_negative(work_root: Path, source: Path) -> None:
    leak_dir = work_root / "leak_scan_negative"
    leak_dir.mkdir(parents=True, exist_ok=True)
    evidence = REAL_EVIDENCE["dol_source_header_slice_evidence"]
    marker = read_source_slice(source, int(evidence["offset"]), int(evidence["size"])).hex()
    leak_file = leak_dir / "payload_dump_report.txt"
    leak_file.write_text(marker, encoding="utf-8")
    try:
        scan_no_payload_leakage([leak_file], source)
    except RuntimeError:
        return
    raise RuntimeError("payload leakage scan negative unexpectedly passed")


def assert_no_source_image_required(work_root: Path) -> None:
    forbidden_suffixes = {"." + "iso", "." + "gcm", "." + "ciso", "." + "nkit" + "." + "iso"}
    for path in work_root.rglob("*"):
        if path.is_file() and any(path.name.endswith(suffix) for suffix in forbidden_suffixes):
            raise RuntimeError(f"unexpected source image file in fixture work tree: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--torch", required=True, type=Path, help="Path to the built torch executable")
    parser.add_argument("--work-dir", type=Path, help="Directory for generated validation inputs and outputs")
    parser.add_argument("--real-source", type=Path, help="Legal GAFE01_00 ISO source for the DOL-only prototype")
    parser.add_argument("--archive-root", type=Path, help="Ignored root for generated real-source O2R outputs")
    parser.add_argument("--reports-dir", type=Path, help="Ignored root for generated real-source reports")
    parser.add_argument("--logs-dir", type=Path, help="Ignored root for generated real-source logs")
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

        if args.real_source:
            if not args.archive_root or not args.reports_dir or not args.logs_dir:
                print("--real-source requires --archive-root, --reports-dir, and --logs-dir", file=sys.stderr)
                return 2
            source = args.real_source.resolve()
            archive_root = args.archive_root.resolve()
            reports_dir = args.reports_dir.resolve()
            logs_dir = args.logs_dir.resolve()
            archive_root.mkdir(parents=True, exist_ok=True)
            reports_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)

            real_summary, real_root = validate_real_positive(
                torch,
                source,
                work_root,
                archive_root,
                reports_dir,
                logs_dir,
            )
            real_negative_count = validate_real_negative(torch, work_root, source, real_root)
            validate_payload_leak_scan_negative(work_root, source)
            assert_no_source_image_required(work_root)

            print("real-source-positive: pass")
            print(f"real-source-family: dol")
            print(f"real-source-evidence-ids: {','.join(sorted(REAL_EVIDENCE))}")
            print("real-source-byte-caps: slices=2 per-slice=64 total=128")
            print(f"real-source-byte-count: {REAL_TOTAL_SOURCE_BYTES}")
            print(f"real-source-binary-segment-count: {len(binary_entries(real_root))}")
            print(f"real-source-policy-metadata-count: {len(metadata_entries(real_root))}")
            print(f"real-source-negative: pass ({real_negative_count}/{real_negative_count})")
            print(f"real-source-deterministic-entry-manifest-sha256: {real_summary['deterministic_entry_manifest_sha256']}")
            print(f"real-source-archive-sha256: {real_summary['raw_archive_sha256']}")
            print(f"real-source-archive-sha256-run-b: {real_summary['raw_archive_sha256_run_b']}")
            print(f"real-source-raw-archive-byte-match: {str(real_summary['raw_archive_byte_match']).lower()}")
            print(f"real-source-raw-o2r-nondeterminism: {real_summary['raw_o2r_nondeterminism']}")
            print("real-source-payload-leakage-scan: pass")
            print("real-source-no-rel-output: pass")
            print("real-source-no-runtime-routing: pass")
            print("real-source-no-texture-readiness: pass")
            print("real-source-no-phase6n-readiness: pass")
            print("real-source-no-renderer-upload: pass")
            print("real-source-no-backend-window-context: pass")

        if args.keep_work or args.work_dir:
            print(f"work-dir: {work_root}")
    finally:
        if temp_context is not None and not args.keep_work:
            temp_context.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
