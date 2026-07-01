#!/usr/bin/env python3
"""Validate the AC DOL config-preview dry-run boundary."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


EXPECTED_PREVIEW_SHA256 = "42c2bb741ad33aadca2e30d7f36493b059626c9d88ded9f85107ce72e1252bb8"
EXPECTED_CONFIG_SCHEMA_VERSION = "phase6by-dol-pcasset-torch-input-config-preview-v1"
EXPECTED_CONFIG_SCHEMA_NAME = "dol_pcasset_torch_input_config_preview"
EXPECTED_CONFIG_KIND = "dol_pcasset_torch_input_config_preview"
EXPECTED_SOURCE_BOUNDARY_KIND = "dol_pcasset_report_to_torch_config_boundary_report"
EXPECTED_SOURCE_BOUNDARY_SHA256 = "4008492b4f59c848af61e37da1e960756de982e15ba6cb6a026cdc02259b5e87"
EXPECTED_SOURCE_MAPPING_SHA256 = "606d669a5e2b17d72eabfdfbf2449c885456016ef60cb535e8c8e2af68bac380"
EXPECTED_NORMALIZED_MANIFEST_SHA256 = "5477afd95f0e689e419db40bb1c01920f876e25be34a72233f4f94c2e904ee0b"
EXPECTED_FACTORY_NAME = "AC:DOL_REL_BINARY_SEGMENT"
EXPECTED_POLICY_FACTORY_NAME = "AC:DOL_REL_POLICY_METADATA"
EXPECTED_RESOURCE_TYPE_NAME = "AcDolBinarySegment"
EXPECTED_RESOURCE_TYPE_ID = "ADOL"
EXPECTED_RESOURCE_VERSION = 0
EXPECTED_ARCHIVE_VERSION = "ac-dol-rel-binary-segment-v0"
EXPECTED_SOURCE_LABEL = "GAFE01_00_user_supplied_disc_image"
EXPECTED_SOURCE_IMAGE_BYTE_SIZE = "1459978240"
EXPECTED_SOURCE_IMAGE_SHA256 = "ca870a9c11ae26cd4d3fb94befd7ecbd075c36244589061d22e3ddc4552dc379"
EXPECTED_DESTINATION_NAMESPACE = "__OTR__ac/dol_rel/binary_segment/dol"
EXPECTED_GENERATED_OUTPUT_POLICY = "ignored-local-only"
EXPECTED_LEGAL_PAYLOAD_POLICY = "legal-user-supplied-dol-slice-local-only"
EXPECTED_RUNTIME_STATUS = "blocked"
EXPECTED_RENDERER_UPLOAD_STATUS = "not executed"
EXPECTED_BACKEND_WINDOW_CONTEXT_STATUS = "not created"
EXPECTED_TYPED_ADOL_LOAD_STATUS = "blocked"
EXPECTED_NO_REL_STATUS = "absent"
EXPECTED_NO_AREL_STATUS = "absent"
EXPECTED_PAYLOAD_DUMP_STATUS = "absent"
EXPECTED_SOURCE_PATH_PUBLICATION_STATUS = "normalized-label-only"
EXPECTED_TORCH_INVOCATION_STATUSES = {"not_invoked", "dry_run_only"}
EXPECTED_PAYLOAD_GENERATION_STATUSES = {"blocked", "not_performed"}
EXPECTED_MAX_SLICES = 2
EXPECTED_MAX_BYTES_PER_SLICE = 64
EXPECTED_MAX_TOTAL_SERIALIZED_BYTES = 128
EXPECTED_ACTUAL_SERIALIZED_BYTES = 48

TOP_LEVEL_KEYS = {
    "archive_version",
    "byte_cap_summary",
    "config_kind",
    "config_row_count",
    "config_schema_name",
    "config_schema_version",
    "evidence_id_set",
    "factory_name",
    "generated_output_policy",
    "legal_payload_policy",
    "normalized_original_archive_manifest_sha256",
    "policy_factory_name",
    "resource_type_id",
    "resource_type_name",
    "resource_version",
    "rows",
    "runtime_boundary_summary",
    "source_boundary_report_kind",
    "source_boundary_report_sha256",
    "source_family_set",
    "source_mapping_report_sha256",
    "typed_load_boundary_summary",
}

ROW_KEYS = {
    "archive_version",
    "backend_window_context_status",
    "config_entry_id",
    "destination_namespace",
    "destination_path",
    "factory_name",
    "generated_output_policy",
    "legal_payload_policy",
    "lus_custom_registration_status",
    "no_arel_status",
    "no_rel_status",
    "normalized_source_label",
    "payload_dump_status",
    "payload_generation_status",
    "phase6n_readiness_status",
    "renderer_upload_status",
    "resource_type_id",
    "resource_type_name",
    "resource_version",
    "runtime_dvd_resource_replacement_status",
    "runtime_routing_status",
    "source_byte_count",
    "source_evidence_id",
    "source_family",
    "source_image_byte_size",
    "source_image_sha256",
    "source_offset",
    "source_path_publication_status",
    "source_sha256",
    "source_size",
    "texture_factory_readiness_status",
    "torch_invocation_status",
    "typed_adol_load_status",
}

BYTE_CAP_KEYS = {
    "actual_serialized_bytes",
    "max_bytes_per_slice",
    "max_slices",
    "max_total_serialized_bytes",
}

RUNTIME_BOUNDARY_KEYS = {
    "backend_window_context_status",
    "phase6n_readiness_status",
    "renderer_upload_status",
    "runtime_dvd_resource_replacement_status",
    "runtime_routing_status",
    "texture_factory_readiness_status",
}

TYPED_LOAD_BOUNDARY_KEYS = {
    "lus_custom_registration_status",
    "resource_type_id",
    "resource_type_name",
    "resource_version",
    "typed_adol_load_status",
}

EXPECTED_ROWS = [
    {
        "config_entry_id": "dol_source_header_slice_evidence",
        "source_evidence_id": "dol_source_header_slice_evidence",
        "source_offset": 122880,
        "source_size": 16,
        "source_sha256": "630c92a2e310b030e9f1ddbf5aea8e617b9d9b2af2daef70ff37a84e37f56c5b",
        "destination_path": "__OTR__ac/dol_rel/binary_segment/dol/dol_source_header_slice_evidence.ADOL",
    },
    {
        "config_entry_id": "dol_source_body_sample_slice_evidence",
        "source_evidence_id": "dol_source_body_sample_slice_evidence",
        "source_offset": 122944,
        "source_size": 32,
        "source_sha256": "83d562b265b659e236087730a630e4225687322a78d01eb4e287e36b678cbe1e",
        "destination_path": "__OTR__ac/dol_rel/binary_segment/dol/dol_source_body_sample_slice_evidence.ADOL",
    },
]

ABSOLUTE_PATH_RE = re.compile(r"(^[A-Za-z]:[\\/])|(^/)|(^\\\\)")


class ValidationError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{context} must be an object")
    return value


def require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{context} must be an array")
    return value


def require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValidationError(f"{context} missing keys: {', '.join(missing)}")
    if extra:
        raise ValidationError(f"{context} has unsupported keys: {', '.join(extra)}")


def require_value(value: dict[str, Any], key: str, expected: Any, context: str) -> None:
    if key not in value:
        raise ValidationError(f"{context} missing {key}")
    if value[key] != expected:
        raise ValidationError(f"{context} {key} must be {expected!r}: {value[key]!r}")


def require_one_of(value: dict[str, Any], key: str, expected: set[str], context: str) -> None:
    if key not in value:
        raise ValidationError(f"{context} missing {key}")
    if value[key] not in expected:
        raise ValidationError(f"{context} {key} must be one of {sorted(expected)!r}: {value[key]!r}")


def require_int(value: dict[str, Any], key: str, expected: int, context: str) -> None:
    if key not in value or not isinstance(value[key], int) or isinstance(value[key], bool):
        raise ValidationError(f"{context} {key} must be integer {expected}")
    if value[key] != expected:
        raise ValidationError(f"{context} {key} must be {expected}: {value[key]}")


def require_string_array(value: dict[str, Any], key: str, expected: list[str], context: str) -> None:
    items = require_list(value.get(key), f"{context} {key}")
    if items != expected:
        raise ValidationError(f"{context} {key} must be {expected!r}: {items!r}")
    if not all(isinstance(item, str) for item in items):
        raise ValidationError(f"{context} {key} must contain strings only")


def validate_relative_archive_path(path: str, context: str) -> None:
    normalized = path.replace("\\", "/")
    if ABSOLUTE_PATH_RE.search(path):
        raise ValidationError(f"{context} must not be absolute: {path}")
    if any(part == ".." for part in normalized.split("/")):
        raise ValidationError(f"{context} must not contain path traversal: {path}")
    if not normalized.startswith(EXPECTED_DESTINATION_NAMESPACE + "/"):
        raise ValidationError(f"{context} must use the DOL ADOL namespace: {path}")
    if "/rel/" in normalized or normalized.endswith(".AREL"):
        raise ValidationError(f"{context} must not contain REL or AREL output: {path}")
    if not normalized.endswith(".ADOL"):
        raise ValidationError(f"{context} must end in .ADOL: {path}")


def scan_for_forbidden_payload_or_source_paths(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"payload_bytes", "payload_byte_dump", "payload_byte_dump_base64", "source_image_path"}:
                raise ValidationError(f"{path}.{key} is not allowed in dry-run preview")
            scan_for_forbidden_payload_or_source_paths(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_for_forbidden_payload_or_source_paths(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if ".iso" in lowered or ".ciso" in lowered or ".gcm" in lowered or ".nkit.iso" in lowered:
            raise ValidationError(f"{path} must not contain a source-image path")
        if ABSOLUTE_PATH_RE.search(value):
            raise ValidationError(f"{path} must not contain an absolute local path")


def validate_byte_caps(preview: dict[str, Any]) -> None:
    byte_caps = require_dict(preview.get("byte_cap_summary"), "byte_cap_summary")
    require_exact_keys(byte_caps, BYTE_CAP_KEYS, "byte_cap_summary")
    require_int(byte_caps, "max_slices", EXPECTED_MAX_SLICES, "byte_cap_summary")
    require_int(byte_caps, "max_bytes_per_slice", EXPECTED_MAX_BYTES_PER_SLICE, "byte_cap_summary")
    require_int(byte_caps, "max_total_serialized_bytes", EXPECTED_MAX_TOTAL_SERIALIZED_BYTES, "byte_cap_summary")
    require_int(byte_caps, "actual_serialized_bytes", EXPECTED_ACTUAL_SERIALIZED_BYTES, "byte_cap_summary")


def validate_runtime_summary(preview: dict[str, Any]) -> None:
    runtime = require_dict(preview.get("runtime_boundary_summary"), "runtime_boundary_summary")
    require_exact_keys(runtime, RUNTIME_BOUNDARY_KEYS, "runtime_boundary_summary")
    require_value(runtime, "runtime_routing_status", EXPECTED_RUNTIME_STATUS, "runtime_boundary_summary")
    require_value(
        runtime,
        "runtime_dvd_resource_replacement_status",
        EXPECTED_RUNTIME_STATUS,
        "runtime_boundary_summary",
    )
    require_value(runtime, "texture_factory_readiness_status", EXPECTED_RUNTIME_STATUS, "runtime_boundary_summary")
    require_value(runtime, "phase6n_readiness_status", EXPECTED_RUNTIME_STATUS, "runtime_boundary_summary")
    require_value(runtime, "renderer_upload_status", EXPECTED_RENDERER_UPLOAD_STATUS, "runtime_boundary_summary")
    require_value(
        runtime,
        "backend_window_context_status",
        EXPECTED_BACKEND_WINDOW_CONTEXT_STATUS,
        "runtime_boundary_summary",
    )


def validate_typed_load_summary(preview: dict[str, Any]) -> None:
    typed = require_dict(preview.get("typed_load_boundary_summary"), "typed_load_boundary_summary")
    require_exact_keys(typed, TYPED_LOAD_BOUNDARY_KEYS, "typed_load_boundary_summary")
    require_value(typed, "typed_adol_load_status", EXPECTED_TYPED_ADOL_LOAD_STATUS, "typed_load_boundary_summary")
    require_value(typed, "lus_custom_registration_status", EXPECTED_RUNTIME_STATUS, "typed_load_boundary_summary")
    require_value(typed, "resource_type_name", EXPECTED_RESOURCE_TYPE_NAME, "typed_load_boundary_summary")
    require_value(typed, "resource_type_id", EXPECTED_RESOURCE_TYPE_ID, "typed_load_boundary_summary")
    require_int(typed, "resource_version", EXPECTED_RESOURCE_VERSION, "typed_load_boundary_summary")


def validate_row(row: dict[str, Any], expected: dict[str, Any], index: int) -> None:
    context = f"row[{index}]"
    require_exact_keys(row, ROW_KEYS, context)
    require_value(row, "config_entry_id", expected["config_entry_id"], context)
    require_value(row, "source_evidence_id", expected["source_evidence_id"], context)
    require_value(row, "source_family", "dol", context)
    require_value(row, "normalized_source_label", EXPECTED_SOURCE_LABEL, context)
    require_value(row, "source_image_byte_size", EXPECTED_SOURCE_IMAGE_BYTE_SIZE, context)
    require_value(row, "source_image_sha256", EXPECTED_SOURCE_IMAGE_SHA256, context)
    require_int(row, "source_offset", int(expected["source_offset"]), context)
    require_int(row, "source_size", int(expected["source_size"]), context)
    require_value(row, "source_sha256", expected["source_sha256"], context)
    require_int(row, "source_byte_count", int(expected["source_size"]), context)
    require_value(row, "destination_namespace", EXPECTED_DESTINATION_NAMESPACE, context)
    require_value(row, "destination_path", expected["destination_path"], context)
    require_value(row, "resource_type_name", EXPECTED_RESOURCE_TYPE_NAME, context)
    require_value(row, "resource_type_id", EXPECTED_RESOURCE_TYPE_ID, context)
    require_int(row, "resource_version", EXPECTED_RESOURCE_VERSION, context)
    require_value(row, "archive_version", EXPECTED_ARCHIVE_VERSION, context)
    require_value(row, "factory_name", EXPECTED_FACTORY_NAME, context)
    require_value(row, "generated_output_policy", EXPECTED_GENERATED_OUTPUT_POLICY, context)
    require_value(row, "legal_payload_policy", EXPECTED_LEGAL_PAYLOAD_POLICY, context)
    require_value(row, "runtime_routing_status", EXPECTED_RUNTIME_STATUS, context)
    require_value(row, "runtime_dvd_resource_replacement_status", EXPECTED_RUNTIME_STATUS, context)
    require_value(row, "texture_factory_readiness_status", EXPECTED_RUNTIME_STATUS, context)
    require_value(row, "phase6n_readiness_status", EXPECTED_RUNTIME_STATUS, context)
    require_value(row, "renderer_upload_status", EXPECTED_RENDERER_UPLOAD_STATUS, context)
    require_value(row, "backend_window_context_status", EXPECTED_BACKEND_WINDOW_CONTEXT_STATUS, context)
    require_value(row, "typed_adol_load_status", EXPECTED_TYPED_ADOL_LOAD_STATUS, context)
    require_value(row, "lus_custom_registration_status", EXPECTED_RUNTIME_STATUS, context)
    require_value(row, "no_rel_status", EXPECTED_NO_REL_STATUS, context)
    require_value(row, "no_arel_status", EXPECTED_NO_AREL_STATUS, context)
    require_value(row, "payload_dump_status", EXPECTED_PAYLOAD_DUMP_STATUS, context)
    require_value(row, "source_path_publication_status", EXPECTED_SOURCE_PATH_PUBLICATION_STATUS, context)
    require_one_of(row, "torch_invocation_status", EXPECTED_TORCH_INVOCATION_STATUSES, context)
    require_one_of(row, "payload_generation_status", EXPECTED_PAYLOAD_GENERATION_STATUSES, context)
    validate_relative_archive_path(str(row["destination_path"]), f"{context} destination_path")


def validate_preview_document(preview: dict[str, Any]) -> None:
    require_exact_keys(preview, TOP_LEVEL_KEYS, "preview")
    require_value(preview, "config_schema_name", EXPECTED_CONFIG_SCHEMA_NAME, "preview")
    require_value(preview, "config_schema_version", EXPECTED_CONFIG_SCHEMA_VERSION, "preview")
    require_value(preview, "config_kind", EXPECTED_CONFIG_KIND, "preview")
    require_value(preview, "source_boundary_report_kind", EXPECTED_SOURCE_BOUNDARY_KIND, "preview")
    require_value(preview, "source_boundary_report_sha256", EXPECTED_SOURCE_BOUNDARY_SHA256, "preview")
    require_value(preview, "source_mapping_report_sha256", EXPECTED_SOURCE_MAPPING_SHA256, "preview")
    require_value(
        preview,
        "normalized_original_archive_manifest_sha256",
        EXPECTED_NORMALIZED_MANIFEST_SHA256,
        "preview",
    )
    require_value(preview, "factory_name", EXPECTED_FACTORY_NAME, "preview")
    require_value(preview, "policy_factory_name", EXPECTED_POLICY_FACTORY_NAME, "preview")
    require_value(preview, "resource_type_name", EXPECTED_RESOURCE_TYPE_NAME, "preview")
    require_value(preview, "resource_type_id", EXPECTED_RESOURCE_TYPE_ID, "preview")
    require_int(preview, "resource_version", EXPECTED_RESOURCE_VERSION, "preview")
    require_value(preview, "archive_version", EXPECTED_ARCHIVE_VERSION, "preview")
    require_int(preview, "config_row_count", len(EXPECTED_ROWS), "preview")
    require_string_array(preview, "source_family_set", ["dol"], "preview")
    require_string_array(
        preview,
        "evidence_id_set",
        [str(row["source_evidence_id"]) for row in EXPECTED_ROWS],
        "preview",
    )
    require_value(preview, "generated_output_policy", EXPECTED_GENERATED_OUTPUT_POLICY, "preview")
    require_value(preview, "legal_payload_policy", EXPECTED_LEGAL_PAYLOAD_POLICY, "preview")
    validate_byte_caps(preview)
    validate_runtime_summary(preview)
    validate_typed_load_summary(preview)
    scan_for_forbidden_payload_or_source_paths(preview)

    rows = require_list(preview.get("rows"), "preview rows")
    if len(rows) != len(EXPECTED_ROWS):
        raise ValidationError(f"preview row count must be {len(EXPECTED_ROWS)}: {len(rows)}")

    seen_evidence_ids: set[str] = set()
    seen_destinations: set[str] = set()
    total_source_bytes = 0
    for index, expected in enumerate(EXPECTED_ROWS):
        row = require_dict(rows[index], f"row[{index}]")
        validate_row(row, expected, index)
        evidence_id = str(row["source_evidence_id"])
        if evidence_id in seen_evidence_ids:
            raise ValidationError(f"duplicate evidence id: {evidence_id}")
        seen_evidence_ids.add(evidence_id)
        destination = str(row["destination_path"]).replace("\\", "/")
        if destination in seen_destinations:
            raise ValidationError(f"duplicate destination path: {destination}")
        seen_destinations.add(destination)
        total_source_bytes += int(row["source_byte_count"])

    if total_source_bytes != EXPECTED_ACTUAL_SERIALIZED_BYTES:
        raise ValidationError(
            f"actual serialized source bytes must be {EXPECTED_ACTUAL_SERIALIZED_BYTES}: {total_source_bytes}"
        )


def load_preview(path: Path) -> tuple[dict[str, Any], str]:
    if not path:
        raise ValidationError("preview path is required")
    if not path.is_file():
        raise ValidationError(f"preview path is missing: {path}")
    data = path.read_bytes()
    preview_sha256 = sha256_bytes(data)
    if preview_sha256 != EXPECTED_PREVIEW_SHA256:
        raise ValidationError(f"preview sha256 must be {EXPECTED_PREVIEW_SHA256}: {preview_sha256}")
    try:
        preview = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"preview JSON is malformed: {exc}") from exc
    return require_dict(preview, "preview"), preview_sha256


def build_report(preview_sha256: str) -> dict[str, Any]:
    return {
        "report_kind": "dol_pcasset_torch_config_preview_dry_run_report",
        "report_schema_version": "phase6bz-dol-pcasset-torch-config-preview-dry-run-report-v1",
        "preview_sha256": preview_sha256,
        "config_schema_version": EXPECTED_CONFIG_SCHEMA_VERSION,
        "config_kind": EXPECTED_CONFIG_KIND,
        "config_row_count": len(EXPECTED_ROWS),
        "accepted_evidence_ids": [str(row["source_evidence_id"]) for row in EXPECTED_ROWS],
        "source_family_set": ["dol"],
        "resource_type_name": EXPECTED_RESOURCE_TYPE_NAME,
        "resource_type_id": EXPECTED_RESOURCE_TYPE_ID,
        "resource_version": EXPECTED_RESOURCE_VERSION,
        "archive_version": EXPECTED_ARCHIVE_VERSION,
        "factory_name": EXPECTED_FACTORY_NAME,
        "policy_factory_name": EXPECTED_POLICY_FACTORY_NAME,
        "byte_cap_summary": {
            "max_slices": EXPECTED_MAX_SLICES,
            "max_bytes_per_slice": EXPECTED_MAX_BYTES_PER_SLICE,
            "max_total_serialized_bytes": EXPECTED_MAX_TOTAL_SERIALIZED_BYTES,
            "actual_serialized_bytes": EXPECTED_ACTUAL_SERIALIZED_BYTES,
        },
        "dry_run_status": "accepted",
        "torch_invocation_status": "dry_run_only",
        "source_image_read_status": "not_performed",
        "source_byte_read_status": "not_performed",
        "payload_generation_status": "not_performed",
        "adol_output_status": "not_performed",
        "rel_row_status": "absent",
        "arel_output_status": "absent",
        "runtime_routing_status": "blocked",
        "runtime_dvd_resource_replacement_status": "blocked",
        "texture_factory_readiness_status": "blocked",
        "phase6n_readiness_status": "blocked",
        "renderer_upload_status": "not executed",
        "backend_window_context_status": "not created",
        "typed_adol_load_status": "blocked",
        "lus_custom_registration_status": "blocked",
        "payload_scan_status": "no_payload_bytes",
        "source_path_scan_status": "no_source_image_absolute_path",
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def valid_preview_fixture() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for expected in EXPECTED_ROWS:
        rows.append(
            {
                "archive_version": EXPECTED_ARCHIVE_VERSION,
                "backend_window_context_status": EXPECTED_BACKEND_WINDOW_CONTEXT_STATUS,
                "config_entry_id": expected["config_entry_id"],
                "destination_namespace": EXPECTED_DESTINATION_NAMESPACE,
                "destination_path": expected["destination_path"],
                "factory_name": EXPECTED_FACTORY_NAME,
                "generated_output_policy": EXPECTED_GENERATED_OUTPUT_POLICY,
                "legal_payload_policy": EXPECTED_LEGAL_PAYLOAD_POLICY,
                "lus_custom_registration_status": EXPECTED_RUNTIME_STATUS,
                "no_arel_status": EXPECTED_NO_AREL_STATUS,
                "no_rel_status": EXPECTED_NO_REL_STATUS,
                "normalized_source_label": EXPECTED_SOURCE_LABEL,
                "payload_dump_status": EXPECTED_PAYLOAD_DUMP_STATUS,
                "payload_generation_status": "blocked",
                "phase6n_readiness_status": EXPECTED_RUNTIME_STATUS,
                "renderer_upload_status": EXPECTED_RENDERER_UPLOAD_STATUS,
                "resource_type_id": EXPECTED_RESOURCE_TYPE_ID,
                "resource_type_name": EXPECTED_RESOURCE_TYPE_NAME,
                "resource_version": EXPECTED_RESOURCE_VERSION,
                "runtime_dvd_resource_replacement_status": EXPECTED_RUNTIME_STATUS,
                "runtime_routing_status": EXPECTED_RUNTIME_STATUS,
                "source_byte_count": expected["source_size"],
                "source_evidence_id": expected["source_evidence_id"],
                "source_family": "dol",
                "source_image_byte_size": EXPECTED_SOURCE_IMAGE_BYTE_SIZE,
                "source_image_sha256": EXPECTED_SOURCE_IMAGE_SHA256,
                "source_offset": expected["source_offset"],
                "source_path_publication_status": EXPECTED_SOURCE_PATH_PUBLICATION_STATUS,
                "source_sha256": expected["source_sha256"],
                "source_size": expected["source_size"],
                "texture_factory_readiness_status": EXPECTED_RUNTIME_STATUS,
                "torch_invocation_status": "not_invoked",
                "typed_adol_load_status": EXPECTED_TYPED_ADOL_LOAD_STATUS,
            }
        )

    return {
        "archive_version": EXPECTED_ARCHIVE_VERSION,
        "byte_cap_summary": {
            "actual_serialized_bytes": EXPECTED_ACTUAL_SERIALIZED_BYTES,
            "max_bytes_per_slice": EXPECTED_MAX_BYTES_PER_SLICE,
            "max_slices": EXPECTED_MAX_SLICES,
            "max_total_serialized_bytes": EXPECTED_MAX_TOTAL_SERIALIZED_BYTES,
        },
        "config_kind": EXPECTED_CONFIG_KIND,
        "config_row_count": len(EXPECTED_ROWS),
        "config_schema_name": EXPECTED_CONFIG_SCHEMA_NAME,
        "config_schema_version": EXPECTED_CONFIG_SCHEMA_VERSION,
        "evidence_id_set": [str(row["source_evidence_id"]) for row in EXPECTED_ROWS],
        "factory_name": EXPECTED_FACTORY_NAME,
        "generated_output_policy": EXPECTED_GENERATED_OUTPUT_POLICY,
        "legal_payload_policy": EXPECTED_LEGAL_PAYLOAD_POLICY,
        "normalized_original_archive_manifest_sha256": EXPECTED_NORMALIZED_MANIFEST_SHA256,
        "policy_factory_name": EXPECTED_POLICY_FACTORY_NAME,
        "resource_type_id": EXPECTED_RESOURCE_TYPE_ID,
        "resource_type_name": EXPECTED_RESOURCE_TYPE_NAME,
        "resource_version": EXPECTED_RESOURCE_VERSION,
        "rows": rows,
        "runtime_boundary_summary": {
            "backend_window_context_status": EXPECTED_BACKEND_WINDOW_CONTEXT_STATUS,
            "phase6n_readiness_status": EXPECTED_RUNTIME_STATUS,
            "renderer_upload_status": EXPECTED_RENDERER_UPLOAD_STATUS,
            "runtime_dvd_resource_replacement_status": EXPECTED_RUNTIME_STATUS,
            "runtime_routing_status": EXPECTED_RUNTIME_STATUS,
            "texture_factory_readiness_status": EXPECTED_RUNTIME_STATUS,
        },
        "source_boundary_report_kind": EXPECTED_SOURCE_BOUNDARY_KIND,
        "source_boundary_report_sha256": EXPECTED_SOURCE_BOUNDARY_SHA256,
        "source_family_set": ["dol"],
        "source_mapping_report_sha256": EXPECTED_SOURCE_MAPPING_SHA256,
        "typed_load_boundary_summary": {
            "lus_custom_registration_status": EXPECTED_RUNTIME_STATUS,
            "resource_type_id": EXPECTED_RESOURCE_TYPE_ID,
            "resource_type_name": EXPECTED_RESOURCE_TYPE_NAME,
            "resource_version": EXPECTED_RESOURCE_VERSION,
            "typed_adol_load_status": EXPECTED_TYPED_ADOL_LOAD_STATUS,
        },
    }


def expect_failure(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    preview = valid_preview_fixture()
    mutate(preview)
    try:
        validate_preview_document(preview)
    except ValidationError:
        return
    raise RuntimeError(f"negative case unexpectedly passed: {name}")


def expect_direct_failure(name: str, action: Callable[[], None]) -> None:
    try:
        action()
    except (ValidationError, json.JSONDecodeError):
        return
    raise RuntimeError(f"negative case unexpectedly passed: {name}")


def run_negative_self_tests() -> int:
    cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
        ("unsupported_schema_version", lambda p: p.__setitem__("config_schema_version", "unsupported")),
        ("unsupported_config_kind", lambda p: p.__setitem__("config_kind", "unsupported")),
        ("missing_factory_name", lambda p: p.pop("factory_name")),
        ("unsupported_factory_name", lambda p: p.__setitem__("factory_name", "AC:OTHER")),
        ("missing_policy_factory_name", lambda p: p.pop("policy_factory_name")),
        ("unsupported_policy_factory_name", lambda p: p.__setitem__("policy_factory_name", "AC:OTHER")),
        ("missing_resource_type_name", lambda p: p.pop("resource_type_name")),
        ("unsupported_resource_type_name", lambda p: p.__setitem__("resource_type_name", "OtherResource")),
        ("unsupported_resource_type_id", lambda p: p.__setitem__("resource_type_id", "AREL")),
        ("unsupported_resource_version", lambda p: p.__setitem__("resource_version", 1)),
        ("unsupported_archive_version", lambda p: p.__setitem__("archive_version", "bad-version")),
        ("missing_row", lambda p: (p["rows"].pop(), p.__setitem__("config_row_count", 1))),
        ("extra_row", lambda p: (p["rows"].append(copy.deepcopy(p["rows"][0])), p.__setitem__("config_row_count", 3))),
        ("duplicate_evidence_id", lambda p: p["rows"][1].__setitem__("source_evidence_id", p["rows"][0]["source_evidence_id"])),
        ("nondeterministic_row_order", lambda p: p["rows"].reverse()),
        ("unsupported_source_family", lambda p: p["rows"][0].__setitem__("source_family", "fst")),
        ("rel_row_present", lambda p: p["rows"][0].__setitem__("source_family", "rel")),
        ("arel_output_present", lambda p: p["rows"][0].__setitem__("destination_path", "__OTR__ac/dol_rel/binary_segment/rel/bad.AREL")),
        ("unsupported_evidence_id", lambda p: p["rows"][0].__setitem__("source_evidence_id", "unknown")),
        ("wrong_source_image_sha256", lambda p: p["rows"][0].__setitem__("source_image_sha256", "0" * 64)),
        ("wrong_source_image_byte_size", lambda p: p["rows"][0].__setitem__("source_image_byte_size", "1")),
        ("wrong_source_offset", lambda p: p["rows"][0].__setitem__("source_offset", 1)),
        ("wrong_source_size", lambda p: p["rows"][0].__setitem__("source_size", 65)),
        ("wrong_source_sha256", lambda p: p["rows"][0].__setitem__("source_sha256", "0" * 64)),
        ("byte_cap_exceeded", lambda p: p["byte_cap_summary"].__setitem__("max_bytes_per_slice", 65)),
        ("actual_serialized_byte_count_mismatch", lambda p: p["byte_cap_summary"].__setitem__("actual_serialized_bytes", 47)),
        ("absolute_destination_path", lambda p: p["rows"][0].__setitem__("destination_path", "C:/absolute/bad.ADOL")),
        ("path_traversal_destination_path", lambda p: p["rows"][0].__setitem__("destination_path", "__OTR__ac/dol_rel/binary_segment/dol/../bad.ADOL")),
        ("duplicate_destination_path", lambda p: p["rows"][1].__setitem__("destination_path", p["rows"][0]["destination_path"])),
        ("missing_generated_output_policy", lambda p: p.pop("generated_output_policy")),
        ("missing_legal_payload_policy", lambda p: p.pop("legal_payload_policy")),
        ("runtime_routing_active", lambda p: p["runtime_boundary_summary"].__setitem__("runtime_routing_status", "active")),
        ("runtime_dvd_resource_replacement_active", lambda p: p["runtime_boundary_summary"].__setitem__("runtime_dvd_resource_replacement_status", "active")),
        ("texture_factory_readiness_ready", lambda p: p["runtime_boundary_summary"].__setitem__("texture_factory_readiness_status", "ready")),
        ("phase6n_readiness_ready", lambda p: p["runtime_boundary_summary"].__setitem__("phase6n_readiness_status", "ready")),
        ("renderer_upload_executed", lambda p: p["runtime_boundary_summary"].__setitem__("renderer_upload_status", "executed")),
        ("backend_window_context_created", lambda p: p["runtime_boundary_summary"].__setitem__("backend_window_context_status", "created")),
        ("typed_adol_load_success_claimed", lambda p: p["typed_load_boundary_summary"].__setitem__("typed_adol_load_status", "loaded")),
        ("lus_custom_registration_claimed", lambda p: p["typed_load_boundary_summary"].__setitem__("lus_custom_registration_status", "registered")),
        ("torch_generation_claimed", lambda p: p["rows"][0].__setitem__("torch_invocation_status", "generated")),
        ("payload_generation_claimed", lambda p: p["rows"][0].__setitem__("payload_generation_status", "generated")),
        ("payload_byte_dump_present", lambda p: p["rows"][0].__setitem__("payload_bytes", "bad")),
        ("source_image_absolute_path_present", lambda p: p["rows"][0].__setitem__("source_image_path", "C:/local/source_image")),
    ]

    expect_direct_failure("missing_preview_path", lambda: load_preview(None))  # type: ignore[arg-type]
    expect_direct_failure("malformed_preview_json", lambda: json.loads("{"))

    for name, mutate in cases:
        expect_failure(name, mutate)
    return len(cases) + 2


def validate_preview_path(preview_path: Path, report_path: Path | None) -> str:
    preview, preview_sha256 = load_preview(preview_path)
    validate_preview_document(preview)
    report = build_report(preview_sha256)
    if report_path is not None:
        write_report(report_path, report)
    return preview_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", type=Path, help="Phase 6BY config-preview JSON path")
    parser.add_argument("--report", type=Path, help="Optional deterministic dry-run report JSON path")
    parser.add_argument("--self-test-negatives", action="store_true", help="Run malformed-preview negative coverage")
    args = parser.parse_args()

    if args.self_test_negatives:
        try:
            count = run_negative_self_tests()
        except Exception as exc:
            print(f"negative: fail ({exc})", file=sys.stderr)
            return 1
        print(f"negative: pass ({count}/{count})")
        return 0

    if args.preview is None:
        print("preview: fail (preview path is required)", file=sys.stderr)
        return 2

    try:
        preview_sha256 = validate_preview_path(args.preview, args.report)
    except ValidationError as exc:
        print(f"preview: reject ({exc})", file=sys.stderr)
        return 1

    print("preview: accepted")
    print(f"preview-sha256: {preview_sha256}")
    print(f"config-row-count: {len(EXPECTED_ROWS)}")
    print("source-family: dol")
    print("evidence-ids: dol_source_header_slice_evidence,dol_source_body_sample_slice_evidence")
    print("source-image-read: not_performed")
    print("source-byte-read: not_performed")
    print("payload-generation: not_performed")
    print("adol-output: not_performed")
    print("rel-rows: absent")
    print("arel-output: absent")
    print("runtime-routing: blocked")
    print("typed-adol-load: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
