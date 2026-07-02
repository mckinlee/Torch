#!/usr/bin/env python3
"""Validate the AC boy1 BTI C8/RGB5A3 local decode parity fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable


REPORT_KIND = "boy1_bti_torch_decode_preview_report"
REPORT_SCHEMA_VERSION = "phase6cf-torch-boy1-bti-local-decode-parity-v1"

EXPECTED_NORMALIZED_SOURCE_LABEL = "GAFE01_00_user_supplied_disc_image"
EXPECTED_SOURCE_IMAGE_SHA256 = "ca870a9c11ae26cd4d3fb94befd7ecbd075c36244589061d22e3ddc4552dc379"
EXPECTED_SOURCE_IMAGE_BYTE_SIZE = 1459978240
EXPECTED_GAME_ID = "GAFE01"
EXPECTED_CANONICAL_VERSION_LABEL = "GAFE01_00"
EXPECTED_GC_MAGIC = 0xC2339F3D

SOURCE_ARCHIVE_PATH = "forest_2nd.arc"
SOURCE_MEMBER_PATH = "forest_2nd.arc/data/boy1.bti"
SELECTED_MEMBER_SOURCE_OFFSET = 1454147680
SELECTED_MEMBER_DECLARED_SIZE = 2432
BTI_HEADER_SOURCE_OFFSET = 1454147680
BTI_HEADER_SIZE = 32
IMAGE_DATA_SOURCE_OFFSET = 1454147712
IMAGE_DATA_OFFSET_WITHIN_MEMBER = 32
IMAGE_DATA_RANGE_SIZE = 2048
PALETTE_SOURCE_OFFSET = 1454149760
PALETTE_OFFSET_WITHIN_MEMBER = 2080
PALETTE_RANGE_SIZE = 352

EXPECTED_BTI_FORMAT = "GX_TF_C8"
EXPECTED_BTI_FORMAT_CATEGORY = "c8"
EXPECTED_PALETTE_FORMAT = "GX_TL_RGB5A3"
EXPECTED_WIDTH = 32
EXPECTED_HEIGHT = 64
EXPECTED_ALPHA_SETTING = 2
EXPECTED_WRAP_S = 0
EXPECTED_WRAP_T = 0
EXPECTED_MIPMAP_OR_LOD_STATUS = "single_image_no_mipmap"
EXPECTED_PALETTE_ENTRY_COUNT = 176
EXPECTED_FUTURE_TEXTURE_RESOURCE_HINT = "possible_palette_texture_resource"
EXPECTED_DECODE_PATH = "gx_tf_c8_indices_to_gx_tl_rgb5a3_palette_rgba32_local"

EXPECTED_HEADER_SHA256 = "765cdc45862318e912b481276efb237a30c7f2afecf5b1b6301857d1db4ee249"
EXPECTED_IMAGE_INDEX_SHA256 = "d23dc64135863f8d0dd840227705b68ce772c2b13f1fc5cca9f0806ac320e949"
EXPECTED_PALETTE_SHA256 = "a8580b43e1886025d1630c43f32e0dfee6b7a4b328b60990f62571cf3deb2e6a"
EXPECTED_DECODED_RGBA_SHA256 = "fb0482588b4054b079ebba27fd1a92bcb9846733019f0d30c41d88d9f42ccff0"
EXPECTED_PREVIEW_IMAGE_SHA256 = "0f7134cf898a07d6c91205d1582258bea3b0b389846a5425b2ea5fd8b0ea8407"
EXPECTED_PREVIEW_IMAGE_FORMAT = "tga32_bgra_uncompressed_top_left"

DECODE_STATUS = "performed_local_ignored_preview_only"
PREVIEW_EMIT_STATUS = "emitted_ignored_local_preview"
PAYLOAD_EXTRACTION_STATUS = "not_performed"
RAW_MEMBER_EMIT_STATUS = "not_performed"
IMAGE_PAYLOAD_HASH_STATUS = "hash_metadata_only"
PALETTE_PAYLOAD_HASH_STATUS = "hash_metadata_only"
TEXTURE_PAYLOAD_EMIT_STATUS = "not_performed"
TEXTURE_FACTORY_READINESS_STATUS = "blocked"
RENDERER_UPLOAD_STATUS = "not_executed"
PHASE6N_READINESS_STATUS = "blocked"
BACKEND_WINDOW_CONTEXT_STATUS = "not_created"
VISUAL_ASSET_READINESS_STATUS = "local_preview_only_not_runtime_ready"
BROAD_ASSET_COVERAGE_STATUS = "not_proven"
RUNTIME_ROUTING_STATUS = "blocked"
RUNTIME_DVD_RESOURCE_REPLACEMENT_STATUS = "blocked"
GAMEPLAY_O2R_ROUTING_STATUS = "blocked"
PUBLIC_PATH_POLICY = "normalized_labels_no_local_absolute_paths"
LEGAL_PAYLOAD_POLICY = "user_supplied_source_local_ignored_preview_only"
GENERATED_OUTPUT_POLICY = "ignored_local_only"

REPORT_OUTPUT_MARKER = "generated/bti-local-decode-preview/phase6cf-torch/reports/"
PREVIEW_OUTPUT_MARKER = "generated/bti-local-decode-preview/phase6cf-torch/previews/"

ABSOLUTE_PATH_RE = re.compile(r"(^[A-Za-z]:[\\/])|(^/)|(^\\\\)")
SOURCE_IMAGE_SUFFIX_RE = re.compile(r"\.(iso|gcm|ciso|nkit\.iso)\b", re.IGNORECASE)
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{120,}={0,2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REPORT_KEYS = {
    "alpha_setting",
    "backend_window_context_status",
    "broad_asset_coverage_status",
    "bti_format",
    "bti_format_category",
    "bti_header_sha256",
    "bti_image_index_sha256",
    "bti_palette_sha256",
    "canonical_version_label",
    "decode_path",
    "decode_status",
    "decoded_rgba_sha256",
    "future_texture_resource_hint",
    "game_id",
    "gameplay_o2r_routing_status",
    "generated_output_policy",
    "height",
    "image_data_offset_within_member",
    "image_data_range_size",
    "image_payload_hash_status",
    "legal_payload_policy",
    "mipmap_or_lod_status",
    "normalized_source_label",
    "palette_entry_count",
    "palette_format",
    "palette_offset_within_member",
    "palette_payload_hash_status",
    "palette_range_size",
    "payload_extraction_status",
    "phase6n_readiness_status",
    "preview_emit_status",
    "preview_image_format",
    "preview_image_sha256",
    "public_path_policy",
    "raw_member_emit_status",
    "renderer_upload_status",
    "report_kind",
    "report_schema_version",
    "runtime_dvd_resource_replacement_status",
    "runtime_routing_status",
    "selected_member_declared_size",
    "selected_member_source_offset",
    "source_archive_path",
    "source_image_byte_size",
    "source_image_sha256",
    "source_member_path",
    "texture_factory_readiness_status",
    "texture_payload_emit_status",
    "visual_asset_readiness_status",
    "width",
    "wrap_s",
    "wrap_t",
}


class ValidationError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_path(path: Path | str) -> str:
    return str(path).replace("\\", "/").lower()


def read_exact_range(path: Path, offset: int, size: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read(size)
    if len(data) != size:
        raise ValidationError(f"source range read was short at offset {offset}")
    return data


def validate_source_image_path(path: Path | None) -> None:
    if path is None:
        raise ValidationError("source image path is required")
    if not path.is_file():
        raise ValidationError("source image path is unreadable or not a file")


def validate_source_identity_fields(size: int, sha256: str) -> None:
    if size != EXPECTED_SOURCE_IMAGE_BYTE_SIZE:
        raise ValidationError("source image byte size mismatch")
    if sha256 != EXPECTED_SOURCE_IMAGE_SHA256:
        raise ValidationError("source image SHA-256 mismatch")


def read_disc_identity(path: Path) -> dict[str, Any]:
    header = read_exact_range(path, 0, 0x20)
    game_id = header[:6].decode("ascii", errors="strict")
    revision = header[7]
    magic = int.from_bytes(header[0x1C:0x20], "big")
    canonical = f"{game_id}_{revision:02d}"
    if magic != EXPECTED_GC_MAGIC:
        raise ValidationError("not a valid GameCube disc image")
    if game_id != EXPECTED_GAME_ID or canonical != EXPECTED_CANONICAL_VERSION_LABEL:
        raise ValidationError("source game/version identity mismatch")
    return {
        "normalized_source_label": EXPECTED_NORMALIZED_SOURCE_LABEL,
        "source_image_sha256": EXPECTED_SOURCE_IMAGE_SHA256,
        "source_image_byte_size": EXPECTED_SOURCE_IMAGE_BYTE_SIZE,
        "game_id": game_id,
        "canonical_version_label": canonical,
    }


def validate_source_image(path: Path | None) -> dict[str, Any]:
    validate_source_image_path(path)
    assert path is not None
    size = path.stat().st_size
    source_sha256 = sha256_file(path)
    validate_source_identity_fields(size, source_sha256)
    identity = read_disc_identity(path)
    identity["source_image_sha256"] = source_sha256
    identity["source_image_byte_size"] = size
    return identity


def texture_format_name(value: int) -> tuple[str, str]:
    if value == 9:
        return EXPECTED_BTI_FORMAT, EXPECTED_BTI_FORMAT_CATEGORY
    return f"unsupported_{value}", "unsupported"


def palette_format_name(palette_flag: int, color_format: int) -> str:
    if palette_flag == 0:
        return "not_applicable_no_palette"
    if color_format == 2:
        return EXPECTED_PALETTE_FORMAT
    return "unsupported"


def ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def c8_image_size(width: int, height: int) -> int:
    return ceil_div(width, 8) * ceil_div(height, 4) * 32


def range_inside_member(offset: int, size: int, member_size: int) -> bool:
    return offset >= 0 and size >= 0 and offset <= member_size and offset + size <= member_size


def parse_bti_header(header: bytes) -> dict[str, Any]:
    if len(header) != BTI_HEADER_SIZE:
        raise ValidationError("BTI header must be exactly 32 bytes")

    bti_format, bti_category = texture_format_name(header[0x00])
    palette_format = palette_format_name(header[0x08], header[0x09])
    width = int.from_bytes(header[0x02:0x04], "big")
    height = int.from_bytes(header[0x04:0x06], "big")
    palette_entry_count = int.from_bytes(header[0x0A:0x0C], "big")
    palette_offset = int.from_bytes(header[0x0C:0x10], "big")
    image_data_offset = int.from_bytes(header[0x1C:0x20], "big")
    mipmap_enabled = header[0x10]
    total_image_count = header[0x18]
    mipmap_status = (
        "single_image_no_mipmap"
        if mipmap_enabled == 0 and total_image_count == 1
        else "mipmap_or_lod_metadata_present_not_expanded"
    )

    image_range_size = c8_image_size(width, height) if width > 0 and height > 0 else 0
    palette_range_size = palette_entry_count * 2 if header[0x08] != 0 else 0

    return {
        "source_archive_path": SOURCE_ARCHIVE_PATH,
        "source_member_path": SOURCE_MEMBER_PATH,
        "selected_member_source_offset": SELECTED_MEMBER_SOURCE_OFFSET,
        "selected_member_declared_size": SELECTED_MEMBER_DECLARED_SIZE,
        "bti_format": bti_format,
        "bti_format_category": bti_category,
        "palette_format": palette_format,
        "width": width,
        "height": height,
        "alpha_setting": header[0x01],
        "wrap_s": header[0x06],
        "wrap_t": header[0x07],
        "mipmap_or_lod_status": mipmap_status,
        "image_data_offset_within_member": image_data_offset,
        "image_data_range_size": image_range_size,
        "palette_offset_within_member": palette_offset,
        "palette_range_size": palette_range_size,
        "palette_entry_count": palette_entry_count,
        "future_texture_resource_hint": EXPECTED_FUTURE_TEXTURE_RESOURCE_HINT,
    }


def valid_metadata_fixture() -> dict[str, Any]:
    return {
        "source_archive_path": SOURCE_ARCHIVE_PATH,
        "source_member_path": SOURCE_MEMBER_PATH,
        "selected_member_source_offset": SELECTED_MEMBER_SOURCE_OFFSET,
        "selected_member_declared_size": SELECTED_MEMBER_DECLARED_SIZE,
        "bti_format": EXPECTED_BTI_FORMAT,
        "bti_format_category": EXPECTED_BTI_FORMAT_CATEGORY,
        "palette_format": EXPECTED_PALETTE_FORMAT,
        "width": EXPECTED_WIDTH,
        "height": EXPECTED_HEIGHT,
        "alpha_setting": EXPECTED_ALPHA_SETTING,
        "wrap_s": EXPECTED_WRAP_S,
        "wrap_t": EXPECTED_WRAP_T,
        "mipmap_or_lod_status": EXPECTED_MIPMAP_OR_LOD_STATUS,
        "image_data_offset_within_member": IMAGE_DATA_OFFSET_WITHIN_MEMBER,
        "image_data_range_size": IMAGE_DATA_RANGE_SIZE,
        "palette_offset_within_member": PALETTE_OFFSET_WITHIN_MEMBER,
        "palette_range_size": PALETTE_RANGE_SIZE,
        "palette_entry_count": EXPECTED_PALETTE_ENTRY_COUNT,
        "future_texture_resource_hint": EXPECTED_FUTURE_TEXTURE_RESOURCE_HINT,
    }


def require_value(value: dict[str, Any], key: str, expected: Any, context: str) -> None:
    if value.get(key) != expected:
        raise ValidationError(f"{context} {key} must be {expected!r}: {value.get(key)!r}")


def validate_selected_metadata(metadata: dict[str, Any]) -> None:
    require_value(metadata, "source_archive_path", SOURCE_ARCHIVE_PATH, "metadata")
    require_value(metadata, "source_member_path", SOURCE_MEMBER_PATH, "metadata")
    require_value(metadata, "selected_member_source_offset", SELECTED_MEMBER_SOURCE_OFFSET, "metadata")
    require_value(metadata, "selected_member_declared_size", SELECTED_MEMBER_DECLARED_SIZE, "metadata")
    require_value(metadata, "bti_format", EXPECTED_BTI_FORMAT, "metadata")
    require_value(metadata, "bti_format_category", EXPECTED_BTI_FORMAT_CATEGORY, "metadata")
    require_value(metadata, "palette_format", EXPECTED_PALETTE_FORMAT, "metadata")
    require_value(metadata, "width", EXPECTED_WIDTH, "metadata")
    require_value(metadata, "height", EXPECTED_HEIGHT, "metadata")
    require_value(metadata, "alpha_setting", EXPECTED_ALPHA_SETTING, "metadata")
    require_value(metadata, "wrap_s", EXPECTED_WRAP_S, "metadata")
    require_value(metadata, "wrap_t", EXPECTED_WRAP_T, "metadata")
    require_value(metadata, "mipmap_or_lod_status", EXPECTED_MIPMAP_OR_LOD_STATUS, "metadata")
    require_value(metadata, "image_data_offset_within_member", IMAGE_DATA_OFFSET_WITHIN_MEMBER, "metadata")
    require_value(metadata, "image_data_range_size", IMAGE_DATA_RANGE_SIZE, "metadata")
    require_value(metadata, "palette_offset_within_member", PALETTE_OFFSET_WITHIN_MEMBER, "metadata")
    require_value(metadata, "palette_range_size", PALETTE_RANGE_SIZE, "metadata")
    require_value(metadata, "palette_entry_count", EXPECTED_PALETTE_ENTRY_COUNT, "metadata")
    require_value(metadata, "future_texture_resource_hint", EXPECTED_FUTURE_TEXTURE_RESOURCE_HINT, "metadata")

    width = int(metadata["width"])
    height = int(metadata["height"])
    if width <= 0:
        raise ValidationError("BTI width is zero")
    if height <= 0:
        raise ValidationError("BTI height is zero")

    image_offset = int(metadata["image_data_offset_within_member"])
    image_size = int(metadata["image_data_range_size"])
    palette_offset = int(metadata["palette_offset_within_member"])
    palette_size = int(metadata["palette_range_size"])
    member_size = int(metadata["selected_member_declared_size"])

    if not range_inside_member(image_offset, image_size, member_size):
        raise ValidationError("BTI image data range is outside the selected member bounds")
    if not range_inside_member(palette_offset, palette_size, member_size):
        raise ValidationError("BTI palette/TLUT range is outside the selected member bounds")
    if image_size != c8_image_size(width, height):
        raise ValidationError("image data size mismatch for C8 width/height")
    if palette_size != int(metadata["palette_entry_count"]) * 2:
        raise ValidationError("palette/TLUT data size mismatch")
    if palette_offset != image_offset + image_size:
        raise ValidationError("palette/TLUT range must immediately follow the C8 image index range")
    if palette_offset + palette_size != member_size:
        raise ValidationError("BTI header, image index data, and palette/TLUT ranges do not cover the selected member")


def expand3_to_8(value: int) -> int:
    return (value * 255 + 3) // 7


def expand4_to_8(value: int) -> int:
    return (value << 4) | value


def expand5_to_8(value: int) -> int:
    return (value << 3) | (value >> 2)


def decode_rgb5a3_entry(entry: int) -> tuple[int, int, int, int]:
    if (entry & 0x8000) == 0:
        a = expand3_to_8((entry >> 12) & 0x7)
        r = expand4_to_8((entry >> 8) & 0xF)
        g = expand4_to_8((entry >> 4) & 0xF)
        b = expand4_to_8(entry & 0xF)
        return r, g, b, a
    r = expand5_to_8((entry >> 10) & 0x1F)
    g = expand5_to_8((entry >> 5) & 0x1F)
    b = expand5_to_8(entry & 0x1F)
    return r, g, b, 255


def decode_c8_rgb5a3_to_rgba(metadata: dict[str, Any], image_indices: bytes, palette_bytes: bytes) -> bytes:
    if metadata["bti_format"] != EXPECTED_BTI_FORMAT or metadata["bti_format_category"] != EXPECTED_BTI_FORMAT_CATEGORY:
        raise ValidationError("attempted decode of unsupported BTI format")
    if metadata["palette_format"] != EXPECTED_PALETTE_FORMAT:
        raise ValidationError("attempted decode of unsupported palette/TLUT format")
    if metadata["source_member_path"] != SOURCE_MEMBER_PATH:
        raise ValidationError("attempted decode of another member")
    if int(metadata["width"]) <= 0:
        raise ValidationError("BTI width is zero")
    if int(metadata["height"]) <= 0:
        raise ValidationError("BTI height is zero")

    width = int(metadata["width"])
    height = int(metadata["height"])
    tiles_per_row = ceil_div(width, 8)
    tiles_per_col = ceil_div(height, 4)
    expected_image_bytes = tiles_per_row * tiles_per_col * 32
    if expected_image_bytes != int(metadata["image_data_range_size"]) or len(image_indices) != expected_image_bytes:
        raise ValidationError("image data size mismatch for C8 width/height")

    palette_entry_count = int(metadata["palette_entry_count"])
    if palette_entry_count == 0 or len(palette_bytes) != palette_entry_count * 2:
        raise ValidationError("palette/TLUT data size mismatch")

    rgba = bytearray(width * height * 4)
    for tile_y in range(tiles_per_col):
        for tile_x in range(tiles_per_row):
            tile_base = (tile_y * tiles_per_row + tile_x) * 32
            for y in range(4):
                for x in range(8):
                    dst_x = tile_x * 8 + x
                    dst_y = tile_y * 4 + y
                    if dst_x >= width or dst_y >= height:
                        continue
                    palette_index = image_indices[tile_base + y * 8 + x]
                    if palette_index >= palette_entry_count:
                        raise ValidationError("C8 index data references palette entry outside reported palette count")
                    entry_offset = palette_index * 2
                    entry = int.from_bytes(palette_bytes[entry_offset:entry_offset + 2], "big")
                    r, g, b, a = decode_rgb5a3_entry(entry)
                    dst = (dst_y * width + dst_x) * 4
                    rgba[dst:dst + 4] = bytes((r, g, b, a))
    return bytes(rgba)


def build_tga32_bgra_top_left(width: int, height: int, rgba: bytes) -> bytes:
    header = bytearray(18)
    header[2] = 2
    header[12:14] = width.to_bytes(2, "little")
    header[14:16] = height.to_bytes(2, "little")
    header[16] = 32
    header[17] = 0x28
    out = bytearray(header)
    for index in range(0, len(rgba), 4):
        r, g, b, a = rgba[index:index + 4]
        out.extend((b, g, r, a))
    return bytes(out)


def validate_output_path(path: Path, marker: str, extension: str, label: str) -> None:
    normalized = normalize_path(path)
    if marker not in normalized or path.suffix.lower() != extension:
        raise ValidationError(f"{label} must be under the ignored Phase 6CF generated output root")


def scan_for_forbidden_payload_or_source_paths(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered in {
                "payload_bytes",
                "payload_byte_dump",
                "payload_byte_dump_base64",
                "source_image_path",
                "raw_bti_member_bytes",
                "image_index_bytes",
                "palette_bytes",
                "byte_array",
            }:
                raise ValidationError(f"{path}.{key} is not allowed in the decode report")
            scan_for_forbidden_payload_or_source_paths(child, f"{path}.{key}")
    elif isinstance(value, list):
        raise ValidationError(f"{path} must not contain byte arrays or lists")
    elif isinstance(value, str):
        lowered = value.lower()
        if SOURCE_IMAGE_SUFFIX_RE.search(lowered):
            raise ValidationError(f"{path} must not contain a source-image path")
        if ABSOLUTE_PATH_RE.search(value):
            raise ValidationError(f"{path} must not contain an absolute local path")
        key_name = path.rsplit(".", 1)[-1].lower()
        if len(value) >= 96 and HEX_RE.fullmatch(value) and not key_name.endswith("sha256"):
            raise ValidationError(f"{path} must not contain a long hex dump")
        if "base64" in key_name or "dump" in key_name or BASE64_RE.fullmatch(value):
            raise ValidationError(f"{path} must not contain a base64 payload dump")


def require_sha256(report: dict[str, Any], key: str, expected: str) -> None:
    value = report.get(key)
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValidationError(f"report {key} must be a lowercase SHA-256 string")
    if value != expected:
        raise ValidationError(f"report {key} must match Phase 6CE: {value}")


def validate_report_document(report: dict[str, Any]) -> None:
    actual_keys = set(report)
    missing = sorted(REPORT_KEYS - actual_keys)
    extra = sorted(actual_keys - REPORT_KEYS)
    if missing:
        raise ValidationError(f"report missing keys: {', '.join(missing)}")
    if extra:
        raise ValidationError(f"report has unsupported keys: {', '.join(extra)}")

    require_value(report, "report_kind", REPORT_KIND, "report")
    require_value(report, "report_schema_version", REPORT_SCHEMA_VERSION, "report")
    require_value(report, "normalized_source_label", EXPECTED_NORMALIZED_SOURCE_LABEL, "report")
    require_value(report, "source_image_byte_size", EXPECTED_SOURCE_IMAGE_BYTE_SIZE, "report")
    require_value(report, "game_id", EXPECTED_GAME_ID, "report")
    require_value(report, "canonical_version_label", EXPECTED_CANONICAL_VERSION_LABEL, "report")
    require_value(report, "source_archive_path", SOURCE_ARCHIVE_PATH, "report")
    require_value(report, "source_member_path", SOURCE_MEMBER_PATH, "report")
    require_value(report, "selected_member_source_offset", SELECTED_MEMBER_SOURCE_OFFSET, "report")
    require_value(report, "selected_member_declared_size", SELECTED_MEMBER_DECLARED_SIZE, "report")
    require_value(report, "preview_image_format", EXPECTED_PREVIEW_IMAGE_FORMAT, "report")
    require_value(report, "bti_format", EXPECTED_BTI_FORMAT, "report")
    require_value(report, "bti_format_category", EXPECTED_BTI_FORMAT_CATEGORY, "report")
    require_value(report, "palette_format", EXPECTED_PALETTE_FORMAT, "report")
    require_value(report, "width", EXPECTED_WIDTH, "report")
    require_value(report, "height", EXPECTED_HEIGHT, "report")
    require_value(report, "alpha_setting", EXPECTED_ALPHA_SETTING, "report")
    require_value(report, "wrap_s", EXPECTED_WRAP_S, "report")
    require_value(report, "wrap_t", EXPECTED_WRAP_T, "report")
    require_value(report, "mipmap_or_lod_status", EXPECTED_MIPMAP_OR_LOD_STATUS, "report")
    require_value(report, "image_data_offset_within_member", IMAGE_DATA_OFFSET_WITHIN_MEMBER, "report")
    require_value(report, "image_data_range_size", IMAGE_DATA_RANGE_SIZE, "report")
    require_value(report, "palette_offset_within_member", PALETTE_OFFSET_WITHIN_MEMBER, "report")
    require_value(report, "palette_range_size", PALETTE_RANGE_SIZE, "report")
    require_value(report, "palette_entry_count", EXPECTED_PALETTE_ENTRY_COUNT, "report")
    require_value(report, "decode_path", EXPECTED_DECODE_PATH, "report")
    require_value(report, "decode_status", DECODE_STATUS, "report")
    require_value(report, "preview_emit_status", PREVIEW_EMIT_STATUS, "report")
    require_value(report, "future_texture_resource_hint", EXPECTED_FUTURE_TEXTURE_RESOURCE_HINT, "report")
    require_value(report, "payload_extraction_status", PAYLOAD_EXTRACTION_STATUS, "report")
    require_value(report, "raw_member_emit_status", RAW_MEMBER_EMIT_STATUS, "report")
    require_value(report, "image_payload_hash_status", IMAGE_PAYLOAD_HASH_STATUS, "report")
    require_value(report, "palette_payload_hash_status", PALETTE_PAYLOAD_HASH_STATUS, "report")
    require_value(report, "texture_payload_emit_status", TEXTURE_PAYLOAD_EMIT_STATUS, "report")
    require_value(report, "texture_factory_readiness_status", TEXTURE_FACTORY_READINESS_STATUS, "report")
    require_value(report, "renderer_upload_status", RENDERER_UPLOAD_STATUS, "report")
    require_value(report, "phase6n_readiness_status", PHASE6N_READINESS_STATUS, "report")
    require_value(report, "backend_window_context_status", BACKEND_WINDOW_CONTEXT_STATUS, "report")
    require_value(report, "visual_asset_readiness_status", VISUAL_ASSET_READINESS_STATUS, "report")
    require_value(report, "broad_asset_coverage_status", BROAD_ASSET_COVERAGE_STATUS, "report")
    require_value(report, "runtime_routing_status", RUNTIME_ROUTING_STATUS, "report")
    require_value(
        report,
        "runtime_dvd_resource_replacement_status",
        RUNTIME_DVD_RESOURCE_REPLACEMENT_STATUS,
        "report",
    )
    require_value(report, "gameplay_o2r_routing_status", GAMEPLAY_O2R_ROUTING_STATUS, "report")
    require_value(report, "public_path_policy", PUBLIC_PATH_POLICY, "report")
    require_value(report, "legal_payload_policy", LEGAL_PAYLOAD_POLICY, "report")
    require_value(report, "generated_output_policy", GENERATED_OUTPUT_POLICY, "report")

    require_sha256(report, "source_image_sha256", EXPECTED_SOURCE_IMAGE_SHA256)
    require_sha256(report, "bti_header_sha256", EXPECTED_HEADER_SHA256)
    require_sha256(report, "bti_image_index_sha256", EXPECTED_IMAGE_INDEX_SHA256)
    require_sha256(report, "bti_palette_sha256", EXPECTED_PALETTE_SHA256)
    require_sha256(report, "decoded_rgba_sha256", EXPECTED_DECODED_RGBA_SHA256)
    require_sha256(report, "preview_image_sha256", EXPECTED_PREVIEW_IMAGE_SHA256)
    scan_for_forbidden_payload_or_source_paths(report)


def validate_report_text(text: str) -> None:
    if "source_image_path" in text:
        raise ValidationError("report must not contain source_image_path")
    if "payload_bytes" in text or "image_index_bytes" in text or "palette_bytes" in text:
        raise ValidationError("report must not contain payload byte fields")
    if SOURCE_IMAGE_SUFFIX_RE.search(text):
        raise ValidationError("report must not contain a source-image filename")


def write_report(path: Path, report: dict[str, Any]) -> str:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    validate_report_text(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return sha256_bytes(text.encode("utf-8"))


def write_preview(path: Path, preview: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(preview)


def build_report(identity: dict[str, Any], metadata: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "report_kind": REPORT_KIND,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "normalized_source_label": identity["normalized_source_label"],
        "source_image_sha256": identity["source_image_sha256"],
        "source_image_byte_size": identity["source_image_byte_size"],
        "game_id": identity["game_id"],
        "canonical_version_label": identity["canonical_version_label"],
        "source_archive_path": metadata["source_archive_path"],
        "source_member_path": metadata["source_member_path"],
        "selected_member_source_offset": metadata["selected_member_source_offset"],
        "selected_member_declared_size": metadata["selected_member_declared_size"],
        "bti_header_sha256": hashes["header_sha256"],
        "bti_image_index_sha256": hashes["image_index_sha256"],
        "bti_palette_sha256": hashes["palette_sha256"],
        "decoded_rgba_sha256": hashes["decoded_rgba_sha256"],
        "preview_image_sha256": hashes["preview_image_sha256"],
        "preview_image_format": EXPECTED_PREVIEW_IMAGE_FORMAT,
        "bti_format": metadata["bti_format"],
        "bti_format_category": metadata["bti_format_category"],
        "palette_format": metadata["palette_format"],
        "width": metadata["width"],
        "height": metadata["height"],
        "alpha_setting": metadata["alpha_setting"],
        "wrap_s": metadata["wrap_s"],
        "wrap_t": metadata["wrap_t"],
        "mipmap_or_lod_status": metadata["mipmap_or_lod_status"],
        "image_data_offset_within_member": metadata["image_data_offset_within_member"],
        "image_data_range_size": metadata["image_data_range_size"],
        "palette_offset_within_member": metadata["palette_offset_within_member"],
        "palette_range_size": metadata["palette_range_size"],
        "palette_entry_count": metadata["palette_entry_count"],
        "decode_path": EXPECTED_DECODE_PATH,
        "decode_status": DECODE_STATUS,
        "preview_emit_status": PREVIEW_EMIT_STATUS,
        "future_texture_resource_hint": metadata["future_texture_resource_hint"],
        "payload_extraction_status": PAYLOAD_EXTRACTION_STATUS,
        "raw_member_emit_status": RAW_MEMBER_EMIT_STATUS,
        "image_payload_hash_status": IMAGE_PAYLOAD_HASH_STATUS,
        "palette_payload_hash_status": PALETTE_PAYLOAD_HASH_STATUS,
        "texture_payload_emit_status": TEXTURE_PAYLOAD_EMIT_STATUS,
        "texture_factory_readiness_status": TEXTURE_FACTORY_READINESS_STATUS,
        "renderer_upload_status": RENDERER_UPLOAD_STATUS,
        "phase6n_readiness_status": PHASE6N_READINESS_STATUS,
        "backend_window_context_status": BACKEND_WINDOW_CONTEXT_STATUS,
        "visual_asset_readiness_status": VISUAL_ASSET_READINESS_STATUS,
        "broad_asset_coverage_status": BROAD_ASSET_COVERAGE_STATUS,
        "runtime_routing_status": RUNTIME_ROUTING_STATUS,
        "runtime_dvd_resource_replacement_status": RUNTIME_DVD_RESOURCE_REPLACEMENT_STATUS,
        "gameplay_o2r_routing_status": GAMEPLAY_O2R_ROUTING_STATUS,
        "public_path_policy": PUBLIC_PATH_POLICY,
        "legal_payload_policy": LEGAL_PAYLOAD_POLICY,
        "generated_output_policy": GENERATED_OUTPUT_POLICY,
    }


def validate_generated_output_staging_policy(staged: bool) -> None:
    if staged:
        raise ValidationError("generated preview/report must not be staged")


def validate_positive(source_image: Path, report_path: Path, preview_path: Path) -> dict[str, Any]:
    validate_output_path(report_path, REPORT_OUTPUT_MARKER, ".json", "report path")
    validate_output_path(preview_path, PREVIEW_OUTPUT_MARKER, ".tga", "preview path")

    identity = validate_source_image(source_image)
    header = read_exact_range(source_image, BTI_HEADER_SOURCE_OFFSET, BTI_HEADER_SIZE)
    image_indices = read_exact_range(source_image, IMAGE_DATA_SOURCE_OFFSET, IMAGE_DATA_RANGE_SIZE)
    palette = read_exact_range(source_image, PALETTE_SOURCE_OFFSET, PALETTE_RANGE_SIZE)

    metadata = parse_bti_header(header)
    validate_selected_metadata(metadata)

    header_sha256 = sha256_bytes(header)
    image_index_sha256 = sha256_bytes(image_indices)
    palette_sha256 = sha256_bytes(palette)
    if header_sha256 != EXPECTED_HEADER_SHA256:
        raise ValidationError(f"BTI header SHA-256 mismatch: {header_sha256}")
    if image_index_sha256 != EXPECTED_IMAGE_INDEX_SHA256:
        raise ValidationError(f"BTI image index SHA-256 mismatch: {image_index_sha256}")
    if palette_sha256 != EXPECTED_PALETTE_SHA256:
        raise ValidationError(f"BTI palette SHA-256 mismatch: {palette_sha256}")

    rgba = decode_c8_rgb5a3_to_rgba(metadata, image_indices, palette)
    if len(rgba) != EXPECTED_WIDTH * EXPECTED_HEIGHT * 4:
        raise ValidationError("decoded RGBA buffer size mismatch")
    decoded_rgba_sha256 = sha256_bytes(rgba)
    if decoded_rgba_sha256 != EXPECTED_DECODED_RGBA_SHA256:
        raise ValidationError(f"decoded RGBA SHA-256 mismatch: {decoded_rgba_sha256}")

    preview = build_tga32_bgra_top_left(EXPECTED_WIDTH, EXPECTED_HEIGHT, rgba)
    preview_sha256 = sha256_bytes(preview)
    if preview_sha256 != EXPECTED_PREVIEW_IMAGE_SHA256:
        raise ValidationError(f"preview TGA SHA-256 mismatch: {preview_sha256}")

    write_preview(preview_path, preview)
    hashes = {
        "header_sha256": header_sha256,
        "image_index_sha256": image_index_sha256,
        "palette_sha256": palette_sha256,
        "decoded_rgba_sha256": decoded_rgba_sha256,
        "preview_image_sha256": preview_sha256,
    }
    report = build_report(identity, metadata, hashes)
    validate_report_document(report)
    report_sha256 = write_report(report_path, report)
    validate_generated_output_staging_policy(False)
    return {
        "report_sha256": report_sha256,
        "preview_sha256": preview_sha256,
        "decoded_rgba_sha256": decoded_rgba_sha256,
        "selected_bti_bytes_read": BTI_HEADER_SIZE + IMAGE_DATA_RANGE_SIZE + PALETTE_RANGE_SIZE,
    }


def valid_identity_fixture() -> dict[str, Any]:
    return {
        "normalized_source_label": EXPECTED_NORMALIZED_SOURCE_LABEL,
        "source_image_sha256": EXPECTED_SOURCE_IMAGE_SHA256,
        "source_image_byte_size": EXPECTED_SOURCE_IMAGE_BYTE_SIZE,
        "game_id": EXPECTED_GAME_ID,
        "canonical_version_label": EXPECTED_CANONICAL_VERSION_LABEL,
    }


def valid_hashes_fixture() -> dict[str, str]:
    return {
        "header_sha256": EXPECTED_HEADER_SHA256,
        "image_index_sha256": EXPECTED_IMAGE_INDEX_SHA256,
        "palette_sha256": EXPECTED_PALETTE_SHA256,
        "decoded_rgba_sha256": EXPECTED_DECODED_RGBA_SHA256,
        "preview_image_sha256": EXPECTED_PREVIEW_IMAGE_SHA256,
    }


def valid_report_fixture() -> dict[str, Any]:
    return build_report(valid_identity_fixture(), valid_metadata_fixture(), valid_hashes_fixture())


def valid_image_indices_fixture() -> bytes:
    return bytes(index % EXPECTED_PALETTE_ENTRY_COUNT for index in range(IMAGE_DATA_RANGE_SIZE))


def valid_palette_fixture() -> bytes:
    out = bytearray()
    for index in range(EXPECTED_PALETTE_ENTRY_COUNT):
        r = index & 0x1F
        g = (index * 3) & 0x1F
        b = (index * 5) & 0x1F
        out.extend((0x8000 | (r << 10) | (g << 5) | b).to_bytes(2, "big"))
    return bytes(out)


def expect_failure(name: str, action: Callable[[], None]) -> None:
    try:
        action()
    except ValidationError as exc:
        if not str(exc):
            raise RuntimeError(f"negative case failed without diagnostic: {name}") from exc
        return
    raise RuntimeError(f"negative case unexpectedly passed: {name}")


def expect_metadata_failure(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    def action() -> None:
        metadata = valid_metadata_fixture()
        mutate(metadata)
        validate_selected_metadata(metadata)

    expect_failure(name, action)


def expect_decode_failure(name: str, mutate: Callable[[dict[str, Any], bytearray, bytearray], None]) -> None:
    def action() -> None:
        metadata = valid_metadata_fixture()
        image = bytearray(valid_image_indices_fixture())
        palette = bytearray(valid_palette_fixture())
        mutate(metadata, image, palette)
        decode_c8_rgb5a3_to_rgba(metadata, bytes(image), bytes(palette))

    expect_failure(name, action)


def expect_report_failure(name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    def action() -> None:
        report = valid_report_fixture()
        mutate(report)
        validate_report_document(report)

    expect_failure(name, action)


def run_negative_self_tests() -> int:
    cases: list[tuple[str, Callable[[], None]]] = [
        ("missing_source_image_path", lambda: expect_failure("missing_source_image_path", lambda: validate_source_image_path(None))),
        ("unreadable_source_image_path", lambda: expect_failure("unreadable_source_image_path", lambda: validate_source_image_path(Path("generated/bti-local-decode-preview/phase6cf-torch/missing.iso")))),
        ("wrong_source_image_byte_size", lambda: expect_failure("wrong_source_image_byte_size", lambda: validate_source_identity_fields(1, EXPECTED_SOURCE_IMAGE_SHA256))),
        ("wrong_source_image_sha256", lambda: expect_failure("wrong_source_image_sha256", lambda: validate_source_identity_fields(EXPECTED_SOURCE_IMAGE_BYTE_SIZE, "0" * 64))),
        ("wrong_selected_member_path", lambda: expect_metadata_failure("wrong_selected_member_path", lambda m: m.__setitem__("source_member_path", "forest_2nd.arc/data/girl1.bti"))),
        ("wrong_member_source_offset", lambda: expect_metadata_failure("wrong_member_source_offset", lambda m: m.__setitem__("selected_member_source_offset", 1))),
        ("wrong_member_declared_size", lambda: expect_metadata_failure("wrong_member_declared_size", lambda m: m.__setitem__("selected_member_declared_size", 1))),
        ("unsupported_bti_format", lambda: expect_metadata_failure("unsupported_bti_format", lambda m: (m.__setitem__("bti_format", "GX_TF_C4"), m.__setitem__("bti_format_category", "c4")))),
        ("unsupported_palette_format", lambda: expect_metadata_failure("unsupported_palette_format", lambda m: m.__setitem__("palette_format", "GX_TL_RGB565"))),
        ("zero_width", lambda: expect_metadata_failure("zero_width", lambda m: m.__setitem__("width", 0))),
        ("zero_height", lambda: expect_metadata_failure("zero_height", lambda m: m.__setitem__("height", 0))),
        ("image_data_range_outside_member", lambda: expect_metadata_failure("image_data_range_outside_member", lambda m: m.__setitem__("image_data_offset_within_member", 2300))),
        ("palette_range_outside_member", lambda: expect_metadata_failure("palette_range_outside_member", lambda m: m.__setitem__("palette_offset_within_member", 2300))),
        ("image_data_size_mismatch_for_c8_width_height", lambda: expect_metadata_failure("image_data_size_mismatch_for_c8_width_height", lambda m: m.__setitem__("image_data_range_size", 2047))),
        ("palette_entry_count_too_small_for_observed_c8_index", lambda: expect_decode_failure("palette_entry_count_too_small_for_observed_c8_index", lambda m, i, p: (m.__setitem__("palette_entry_count", 10), p.__delitem__(slice(20, None))))),
        ("attempted_decode_of_unsupported_format", lambda: expect_decode_failure("attempted_decode_of_unsupported_format", lambda m, i, p: (m.__setitem__("bti_format", "GX_TF_C4"), m.__setitem__("bti_format_category", "c4")))),
        ("attempted_decode_of_another_member", lambda: expect_decode_failure("attempted_decode_of_another_member", lambda m, i, p: m.__setitem__("source_member_path", "forest_2nd.arc/data/girl1.bti"))),
        ("attempted_raw_bti_member_emission", lambda: expect_report_failure("attempted_raw_bti_member_emission", lambda r: r.__setitem__("raw_member_emit_status", "performed"))),
        ("attempted_raw_image_index_byte_emission", lambda: expect_report_failure("attempted_raw_image_index_byte_emission", lambda r: r.__setitem__("image_index_bytes", "00"))),
        ("attempted_raw_palette_byte_emission", lambda: expect_report_failure("attempted_raw_palette_byte_emission", lambda r: r.__setitem__("palette_bytes", "00"))),
        ("attempted_o2r_payload_resource_generation", lambda: expect_report_failure("attempted_o2r_payload_resource_generation", lambda r: r.__setitem__("texture_payload_emit_status", "performed"))),
        ("texture_factory_readiness_claimed", lambda: expect_report_failure("texture_factory_readiness_claimed", lambda r: r.__setitem__("texture_factory_readiness_status", "ready"))),
        ("visual_asset_readiness_claimed_beyond_local_preview", lambda: expect_report_failure("visual_asset_readiness_claimed_beyond_local_preview", lambda r: r.__setitem__("visual_asset_readiness_status", "runtime_ready"))),
        ("broad_asset_coverage_claimed", lambda: expect_report_failure("broad_asset_coverage_claimed", lambda r: r.__setitem__("broad_asset_coverage_status", "proven"))),
        ("renderer_upload_attempted", lambda: expect_report_failure("renderer_upload_attempted", lambda r: r.__setitem__("renderer_upload_status", "executed"))),
        ("runtime_routing_active", lambda: expect_report_failure("runtime_routing_active", lambda r: r.__setitem__("runtime_routing_status", "active"))),
        ("runtime_dvd_resource_replacement_active", lambda: expect_report_failure("runtime_dvd_resource_replacement_active", lambda r: r.__setitem__("runtime_dvd_resource_replacement_status", "active"))),
        ("gameplay_o2r_routing_active", lambda: expect_report_failure("gameplay_o2r_routing_active", lambda r: r.__setitem__("gameplay_o2r_routing_status", "active"))),
        ("phase6n_readiness_ready", lambda: expect_report_failure("phase6n_readiness_ready", lambda r: r.__setitem__("phase6n_readiness_status", "ready"))),
        ("backend_window_context_created", lambda: expect_report_failure("backend_window_context_created", lambda r: r.__setitem__("backend_window_context_status", "created"))),
        ("rel_source_read", lambda: expect_report_failure("rel_source_read", lambda r: r.__setitem__("rel_source_read_status", "performed"))),
        ("arel_emitted", lambda: expect_report_failure("arel_emitted", lambda r: r.__setitem__("arel_emit_status", "emitted"))),
        ("source_image_absolute_path_in_report", lambda: expect_report_failure("source_image_absolute_path_in_report", lambda r: r.__setitem__("source_image_path", "C:/local/source.iso"))),
        ("payload_bytes_in_report", lambda: expect_report_failure("payload_bytes_in_report", lambda r: r.__setitem__("payload_bytes", "00"))),
        ("long_hex_dump_in_report", lambda: expect_report_failure("long_hex_dump_in_report", lambda r: r.__setitem__("payload_hex_dump", "a" * 160))),
        ("base64_payload_dump_in_report", lambda: expect_report_failure("base64_payload_dump_in_report", lambda r: r.__setitem__("payload_base64", "A" * 170 + "=="))),
        ("generated_preview_or_report_staged", lambda: expect_failure("generated_preview_or_report_staged", lambda: validate_generated_output_staging_policy(True))),
    ]

    for name, action in cases:
        action()
    return len(cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-image", type=Path, help="Legal GAFE01_00 source image path")
    parser.add_argument("--report", type=Path, help="Ignored deterministic metadata report JSON path")
    parser.add_argument("--preview", type=Path, help="Ignored deterministic 32-bit TGA preview path")
    parser.add_argument("--self-test-negatives", action="store_true", help="Run malformed metadata/report coverage")
    args = parser.parse_args()

    if args.self_test_negatives:
        if args.source_image is not None or args.report is not None or args.preview is not None:
            print("negative: fail (--self-test-negatives does not accept positive inputs)", file=sys.stderr)
            return 2
        try:
            count = run_negative_self_tests()
        except Exception as exc:
            print(f"negative: fail ({exc})", file=sys.stderr)
            return 1
        print(f"negative: pass ({count}/{count})")
        return 0

    if args.source_image is None or args.report is None or args.preview is None:
        print("positive: fail (--source-image, --report, and --preview are required)", file=sys.stderr)
        return 2

    try:
        result = validate_positive(args.source_image, args.report, args.preview)
    except ValidationError as exc:
        print(f"positive: reject ({exc})", file=sys.stderr)
        return 1

    print("positive: pass")
    print(f"source-label: {EXPECTED_NORMALIZED_SOURCE_LABEL}")
    print(f"source-image-sha256: {EXPECTED_SOURCE_IMAGE_SHA256}")
    print(f"selected-member: {SOURCE_MEMBER_PATH}")
    print(f"selected-member-source-offset: {SELECTED_MEMBER_SOURCE_OFFSET}")
    print(f"selected-member-declared-size: {SELECTED_MEMBER_DECLARED_SIZE}")
    print(f"bti-format: {EXPECTED_BTI_FORMAT}/{EXPECTED_BTI_FORMAT_CATEGORY}")
    print(f"palette-format: {EXPECTED_PALETTE_FORMAT}")
    print(f"dimensions: {EXPECTED_WIDTH}x{EXPECTED_HEIGHT}")
    print(f"image-range: offset={IMAGE_DATA_OFFSET_WITHIN_MEMBER} size={IMAGE_DATA_RANGE_SIZE}")
    print(f"palette-range: offset={PALETTE_OFFSET_WITHIN_MEMBER} size={PALETTE_RANGE_SIZE}")
    print(f"bti-header-sha256: {EXPECTED_HEADER_SHA256}")
    print(f"bti-image-index-sha256: {EXPECTED_IMAGE_INDEX_SHA256}")
    print(f"bti-palette-sha256: {EXPECTED_PALETTE_SHA256}")
    print(f"decoded-rgba-sha256: {result['decoded_rgba_sha256']}")
    print(f"preview-image-sha256: {result['preview_sha256']}")
    print(f"report-sha256: {result['report_sha256']}")
    print(f"selected-bti-bytes-read: {result['selected_bti_bytes_read']}")
    print("phase6ce-parity: pass")
    print("payload-extraction: not_performed")
    print("raw-member-emission: not_performed")
    print("texture-payload-o2r: not_performed")
    print("rel-source-read: not_performed")
    print("arel-output: not_performed")
    print("runtime-routing: blocked")
    print("runtime-dvd-resource-replacement: blocked")
    print("gameplay-o2r-routing: blocked")
    print("renderer-upload: not_executed")
    print("backend-window-context: not_created")
    print("texture-factory-readiness: blocked")
    print("phase6n-readiness: blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
