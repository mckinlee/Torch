#include "DolRelBinarySegmentFactory.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <set>
#include <sstream>

namespace AC {
namespace {

constexpr const char* kBinaryFactoryName = "AC:DOL_REL_BINARY_SEGMENT";
constexpr const char* kMetadataFactoryName = "AC:DOL_REL_POLICY_METADATA";
constexpr const char* kSyntheticGeneratedRoot = "fixture-output/dol-rel-binary-segment";
constexpr const char* kRealGeneratedRoot = "generated/dol-rel-first-factory";
constexpr const char* kGeneratedPolicy = "ignored-local-only";
constexpr const char* kSyntheticLegalPolicy = "synthetic-only-no-game-payload";
constexpr const char* kRealLegalPolicy = "legal-user-supplied-dol-slice-local-only";
constexpr const char* kBinaryArchiveVersion = "ac-dol-rel-binary-segment-v0";
constexpr const char* kMetadataArchiveVersion = "ac-dol-rel-policy-metadata-v0";
constexpr const char* kRuntimeBlocked = "blocked";
constexpr const char* kTextureBlocked = "blocked";
constexpr const char* kPhase6NBlocked = "blocked";
constexpr const char* kRendererNotExecuted = "not executed";
constexpr const char* kBackendNotCreated = "not created";
constexpr const char* kRealSourceAbsent = "absent";
constexpr const char* kRealSourceVerified = "verified-before-serialization";
constexpr const char* kGamePayloadAbsent = "absent";
constexpr const char* kRealGamePayloadStatus = "bounded-dol-slice-local-only";
constexpr const char* kTownshipRuntimeNotImplied = "not implied";
constexpr size_t kMaxSyntheticSize = 64;
constexpr uint64_t kMaxRealSourceSize = 64;
constexpr uint64_t kMaxRealSourceSlices = 2;
constexpr uint64_t kMaxRealSourceTotalBytes = 128;

std::set<std::string> gArchivePaths;

struct CommonPolicyFields {
    bool realSourceMode = false;
    std::string configEntryId;
    std::string sourceFamily;
    std::string archivePath;
    std::string generatedOutputRoot;
    std::string generatedOutputPolicy;
    std::string legalPayloadPolicy;
    std::string resourceTypeName;
    std::string resourceTypeId;
    uint64_t resourceVersion;
    std::string archiveVersion;
    std::string runtimeRoutingStatus;
    std::string textureFactoryReadinessStatus;
    std::string phase6nReadinessStatus;
    std::string rendererUploadStatus;
    std::string backendWindowContextStatus;
    std::string realSourceReadStatus;
    std::string gamePayloadStatus;
    std::string townshipRuntimeRoutingStatus;
};

struct RealSourceFields {
    std::string sourceImagePath;
    std::string sourceImageEnvVar;
    std::string normalizedSourcePathLabel;
    std::string sourceImageSha256;
    uint64_t sourceImageByteSize = 0;
    std::string gameId;
    std::string canonicalVersion;
    std::string sourceEvidenceId;
    uint64_t sourceFamilyCount = 0;
    uint64_t sourceSliceCount = 0;
    uint64_t totalSourceByteCount = 0;
    uint64_t sourceOffset = 0;
    uint64_t sourceSize = 0;
    std::string sourceSha256;
    uint64_t sourceByteCount = 0;
    std::string endianPolicy;
    std::string byteSwapPolicy;
    std::string dolClassification;
    std::string destinationNamespace;
    std::string factoryName;
    std::string resourceClass;
    std::string runtimeDvdResourceReplacementStatus;
    std::string reportLogPayloadStatus;
    std::string lusTypedRegistrationStatus;
};

struct SourceIdentity {
    uint64_t size = 0;
    std::string sha256;
};

std::map<std::string, SourceIdentity> gSourceIdentityCache;

bool ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() &&
           value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool starts_with(const std::string& value, const std::string& prefix) {
    return value.rfind(prefix, 0) == 0;
}

bool optional_bool(YAML::Node node, const std::string& key, bool fallback) {
    if (!node[key]) {
        return fallback;
    }
    if (!node[key].IsScalar()) {
        throw std::runtime_error("asset entry has invalid boolean '" + key + "'");
    }
    return node[key].as<bool>();
}

std::string require_scalar(YAML::Node node, const std::string& key, const std::string& context) {
    if (!node[key] || !node[key].IsScalar()) {
        throw std::runtime_error(context + " is missing required scalar '" + key + "'");
    }
    const std::string value = node[key].as<std::string>();
    if (value.empty()) {
        throw std::runtime_error(context + " has empty scalar '" + key + "'");
    }
    return value;
}

bool require_bool(YAML::Node node, const std::string& key, const std::string& context) {
    if (!node[key] || !node[key].IsScalar()) {
        throw std::runtime_error(context + " is missing required boolean '" + key + "'");
    }
    return node[key].as<bool>();
}

uint64_t require_u64(YAML::Node node, const std::string& key, const std::string& context) {
    const std::string value = require_scalar(node, key, context);
    if (value.empty() || value[0] == '-') {
        throw std::runtime_error(context + " has invalid " + key + ": " + value);
    }
    for (const char c : value) {
        if (!std::isdigit(static_cast<unsigned char>(c))) {
            throw std::runtime_error(context + " has invalid " + key + ": " + value);
        }
    }

    try {
        size_t parsedLength = 0;
        const uint64_t parsed = std::stoull(value, &parsedLength, 10);
        if (parsedLength != value.size()) {
            throw std::runtime_error(context + " has invalid " + key + ": " + value);
        }
        return parsed;
    } catch (const std::out_of_range&) {
        throw std::runtime_error(context + " has invalid " + key + ": " + value);
    }
}

void require_value(const std::string& actual, const std::string& expected, const std::string& key,
                   const std::string& context) {
    if (actual != expected) {
        throw std::runtime_error(context + " " + key + " must be '" + expected + "': " + actual);
    }
}

void require_sha256(const std::string& value, const std::string& key, const std::string& context) {
    if (value.size() != 64) {
        throw std::runtime_error(context + " " + key + " must be 64 lowercase hex characters");
    }
    for (const char c : value) {
        if (!std::isdigit(static_cast<unsigned char>(c)) && (c < 'a' || c > 'f')) {
            throw std::runtime_error(context + " " + key + " must be 64 lowercase hex characters");
        }
    }
}

uint32_t rotr32(uint32_t value, uint32_t bits) {
    return (value >> bits) | (value << (32U - bits));
}

class Sha256 {
public:
    void Update(const uint8_t* data, size_t size) {
        bitLength += static_cast<uint64_t>(size) * 8ULL;
        size_t index = 0;
        while (index < size) {
            const size_t available = 64 - bufferSize;
            const size_t copied = std::min(available, size - index);
            std::copy(data + index, data + index + copied, buffer.begin() + static_cast<std::ptrdiff_t>(bufferSize));
            bufferSize += copied;
            index += copied;
            if (bufferSize == 64) {
                Transform(buffer.data());
                bufferSize = 0;
            }
        }
    }

    std::string Finish() {
        buffer[bufferSize++] = 0x80;
        if (bufferSize > 56) {
            while (bufferSize < 64) {
                buffer[bufferSize++] = 0;
            }
            Transform(buffer.data());
            bufferSize = 0;
        }
        while (bufferSize < 56) {
            buffer[bufferSize++] = 0;
        }
        for (int shift = 56; shift >= 0; shift -= 8) {
            buffer[bufferSize++] = static_cast<uint8_t>((bitLength >> shift) & 0xFFU);
        }
        Transform(buffer.data());

        std::ostringstream out;
        out << std::hex << std::setfill('0');
        for (const uint32_t word : state) {
            out << std::setw(8) << word;
        }
        return out.str();
    }

private:
    void Transform(const uint8_t block[64]) {
        static constexpr std::array<uint32_t, 64> k = {
            0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U,
            0xab1c5ed5U, 0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU,
            0x9bdc06a7U, 0xc19bf174U, 0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU,
            0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU, 0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
            0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U, 0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU,
            0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U, 0xa2bfe8a1U, 0xa81a664bU,
            0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U, 0x19a4c116U,
            0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
            0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U,
            0xc67178f2U,
        };

        std::array<uint32_t, 64> w {};
        for (size_t i = 0; i < 16; ++i) {
            const size_t offset = i * 4;
            w[i] = (static_cast<uint32_t>(block[offset]) << 24U) |
                   (static_cast<uint32_t>(block[offset + 1]) << 16U) |
                   (static_cast<uint32_t>(block[offset + 2]) << 8U) |
                   static_cast<uint32_t>(block[offset + 3]);
        }
        for (size_t i = 16; i < 64; ++i) {
            const uint32_t s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^ (w[i - 15] >> 3U);
            const uint32_t s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^ (w[i - 2] >> 10U);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }

        uint32_t a = state[0];
        uint32_t b = state[1];
        uint32_t c = state[2];
        uint32_t d = state[3];
        uint32_t e = state[4];
        uint32_t f = state[5];
        uint32_t g = state[6];
        uint32_t h = state[7];

        for (size_t i = 0; i < 64; ++i) {
            const uint32_t s1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
            const uint32_t ch = (e & f) ^ ((~e) & g);
            const uint32_t temp1 = h + s1 + ch + k[i] + w[i];
            const uint32_t s0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
            const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t temp2 = s0 + maj;
            h = g;
            g = f;
            f = e;
            e = d + temp1;
            d = c;
            c = b;
            b = a;
            a = temp1 + temp2;
        }

        state[0] += a;
        state[1] += b;
        state[2] += c;
        state[3] += d;
        state[4] += e;
        state[5] += f;
        state[6] += g;
        state[7] += h;
    }

    std::array<uint32_t, 8> state {
        0x6a09e667U,
        0xbb67ae85U,
        0x3c6ef372U,
        0xa54ff53aU,
        0x510e527fU,
        0x9b05688cU,
        0x1f83d9abU,
        0x5be0cd19U,
    };
    std::array<uint8_t, 64> buffer {};
    size_t bufferSize = 0;
    uint64_t bitLength = 0;
};

std::string sha256_bytes(const std::vector<uint8_t>& data) {
    Sha256 sha;
    if (!data.empty()) {
        sha.Update(data.data(), data.size());
    }
    return sha.Finish();
}

SourceIdentity identify_source_image(const std::string& sourceImagePath, const std::string& context) {
    const auto cached = gSourceIdentityCache.find(sourceImagePath);
    if (cached != gSourceIdentityCache.end()) {
        return cached->second;
    }

    std::error_code ec;
    const uint64_t size = fs::file_size(sourceImagePath, ec);
    if (ec) {
        throw std::runtime_error(context + " source_image_path is not readable");
    }

    std::ifstream input(sourceImagePath, std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error(context + " source_image_path is not readable");
    }

    Sha256 sha;
    std::array<char, 65536> block {};
    while (input.good()) {
        input.read(block.data(), static_cast<std::streamsize>(block.size()));
        const std::streamsize count = input.gcount();
        if (count > 0) {
            sha.Update(reinterpret_cast<const uint8_t*>(block.data()), static_cast<size_t>(count));
        }
    }

    SourceIdentity identity;
    identity.size = size;
    identity.sha256 = sha.Finish();
    gSourceIdentityCache[sourceImagePath] = identity;
    return identity;
}

std::vector<uint8_t> read_source_slice(const std::string& sourceImagePath, uint64_t sourceOffset, uint64_t sourceSize,
                                       const std::string& context) {
    std::ifstream input(sourceImagePath, std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error(context + " source_image_path is not readable");
    }
    input.seekg(static_cast<std::streamoff>(sourceOffset), std::ios::beg);
    if (!input.good()) {
        throw std::runtime_error(context + " source_offset is outside source image");
    }

    std::vector<uint8_t> data(static_cast<size_t>(sourceSize));
    input.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(data.size()));
    if (input.gcount() != static_cast<std::streamsize>(data.size())) {
        throw std::runtime_error(context + " source slice could not be fully read");
    }
    return data;
}

std::string normalize_config_path(std::string path, const std::string& key, const std::string& context) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (path.empty()) {
        throw std::runtime_error(context + " " + key + " is empty");
    }
    if (path[0] == '/' || (path.size() >= 2 && path[1] == ':')) {
        throw std::runtime_error(context + " " + key + " must be relative: " + path);
    }

    fs::path parsed(path);
    for (const fs::path& part : parsed) {
        const std::string text = part.generic_string();
        if (text == "..") {
            throw std::runtime_error(context + " " + key + " escapes output root: " + path);
        }
    }
    return parsed.generic_string();
}

void reserve_archive_path(const std::string& path, const std::string& context) {
    if (!gArchivePaths.insert(path).second) {
        throw std::runtime_error(context + " duplicate output path: " + path);
    }
}

void validate_no_external_source(YAML::Node node, const std::string& context) {
    if (node["source_image_path"]) {
        throw std::runtime_error(context + " source_image_path must not be set for the synthetic fixture");
    }
    if (require_bool(node, "source_image_required", context)) {
        throw std::runtime_error(context + " source_image_required must be false for the synthetic fixture");
    }
    if (require_bool(node, "requires_township_runtime", context)) {
        throw std::runtime_error(context + " requires_township_runtime must be false for the synthetic fixture");
    }
    const std::string path = normalize_config_path(require_scalar(node, "path", context), "path", context);
    if (path.empty()) {
        throw std::runtime_error(context + " path is empty");
    }
}

void validate_local_placeholder_path(YAML::Node node, const std::string& context) {
    if (require_bool(node, "requires_township_runtime", context)) {
        throw std::runtime_error(context + " requires_township_runtime must be false");
    }
    const std::string path = normalize_config_path(require_scalar(node, "path", context), "path", context);
    if (path.empty()) {
        throw std::runtime_error(context + " path is empty");
    }
}

CommonPolicyFields read_common_fields(YAML::Node node, const std::string& context, const std::string& archiveVersion) {
    CommonPolicyFields fields;
    fields.realSourceMode = optional_bool(node, "real_source_mode", false);
    fields.configEntryId = require_scalar(node, "config_entry_id", context);
    fields.sourceFamily = fields.realSourceMode ? require_scalar(node, "source_family", context)
                                                : require_scalar(node, "synthetic_source_family", context);
    fields.archivePath = normalize_config_path(require_scalar(node, "destination_path", context), "destination_path", context);
    fields.generatedOutputRoot =
        normalize_config_path(require_scalar(node, "generated_output_root", context), "generated_output_root", context);
    fields.generatedOutputPolicy = require_scalar(node, "generated_output_policy", context);
    fields.legalPayloadPolicy = require_scalar(node, "legal_payload_policy", context);
    fields.resourceTypeName = require_scalar(node, "resource_type_name", context);
    fields.resourceTypeId = require_scalar(node, "resource_type_id", context);
    fields.resourceVersion = require_u64(node, "resource_version", context);
    fields.archiveVersion = require_scalar(node, "archive_version", context);
    fields.runtimeRoutingStatus = require_scalar(node, "runtime_routing_status", context);
    fields.textureFactoryReadinessStatus = require_scalar(node, "texture_factory_readiness_status", context);
    fields.phase6nReadinessStatus = require_scalar(node, "phase6n_readiness_status", context);
    fields.rendererUploadStatus = require_scalar(node, "renderer_upload_status", context);
    fields.backendWindowContextStatus = require_scalar(node, "backend_window_context_status", context);
    fields.realSourceReadStatus = require_scalar(node, "real_source_read_status", context);
    fields.gamePayloadStatus = require_scalar(node, "game_payload_status", context);
    fields.townshipRuntimeRoutingStatus = require_scalar(node, "township_runtime_routing_status", context);

    require_value(fields.generatedOutputRoot, fields.realSourceMode ? kRealGeneratedRoot : kSyntheticGeneratedRoot,
                  "generated_output_root", context);
    require_value(fields.generatedOutputPolicy, kGeneratedPolicy, "generated_output_policy", context);
    require_value(fields.legalPayloadPolicy, fields.realSourceMode ? kRealLegalPolicy : kSyntheticLegalPolicy,
                  "legal_payload_policy", context);
    require_value(fields.archiveVersion, archiveVersion, "archive_version", context);
    require_value(fields.runtimeRoutingStatus, kRuntimeBlocked, "runtime_routing_status", context);
    require_value(fields.textureFactoryReadinessStatus, kTextureBlocked, "texture_factory_readiness_status", context);
    require_value(fields.phase6nReadinessStatus, kPhase6NBlocked, "phase6n_readiness_status", context);
    require_value(fields.rendererUploadStatus, kRendererNotExecuted, "renderer_upload_status", context);
    require_value(fields.backendWindowContextStatus, kBackendNotCreated, "backend_window_context_status", context);
    require_value(fields.realSourceReadStatus, fields.realSourceMode ? kRealSourceVerified : kRealSourceAbsent,
                  "real_source_read_status", context);
    require_value(fields.gamePayloadStatus, fields.realSourceMode ? kRealGamePayloadStatus : kGamePayloadAbsent,
                  "game_payload_status", context);
    require_value(fields.townshipRuntimeRoutingStatus, kTownshipRuntimeNotImplied,
                  "township_runtime_routing_status", context);

    if (fields.resourceVersion != 0) {
        throw std::runtime_error(context + " resource_version must be 0");
    }
    if (fields.realSourceMode) {
        validate_local_placeholder_path(node, context);
    } else {
        validate_no_external_source(node, context);
    }
    return fields;
}

uint64_t fnv1a64(const std::string& value) {
    uint64_t hash = 1469598103934665603ULL;
    for (const unsigned char c : value) {
        hash ^= static_cast<uint64_t>(c);
        hash *= 1099511628211ULL;
    }
    return hash;
}

std::vector<uint8_t> make_synthetic_data(const std::string& configEntryId, const std::string& family,
                                         const std::string& segmentKind, uint64_t offset, uint64_t size) {
    const uint64_t seed = fnv1a64(configEntryId + "|" + family + "|" + segmentKind + "|" + std::to_string(offset));
    std::vector<uint8_t> data;
    data.reserve(static_cast<size_t>(size));
    for (uint64_t index = 0; index < size; ++index) {
        data.push_back(static_cast<uint8_t>((seed + offset + (index * 37ULL)) & 0xFFU));
    }
    return data;
}

bool is_allowed_segment_kind(const std::string& family, const std::string& segmentKind) {
    static const std::set<std::string> dolKinds = {
        "dol_header",
        "dol_body_sample",
    };
    static const std::set<std::string> relKinds = {
        "rel_module_header",
        "rel_section_table",
        "rel_body_sample",
        "rel_relocation_reference",
    };

    if (family == "dol") {
        return dolKinds.find(segmentKind) != dolKinds.end();
    }
    if (family == "rel") {
        return relKinds.find(segmentKind) != relKinds.end();
    }
    return false;
}

Torch::ResourceType validate_binary_type(const CommonPolicyFields& fields, const std::string& segmentKind,
                                         const std::string& context) {
    const std::string familyKey = fields.realSourceMode ? "source_family" : "synthetic_source_family";
    if (fields.realSourceMode && fields.sourceFamily != "dol") {
        throw std::runtime_error(context + " source_family must be 'dol': " + fields.sourceFamily);
    }
    if (!fields.realSourceMode && fields.sourceFamily != "dol" && fields.sourceFamily != "rel") {
        throw std::runtime_error(context + " has unsupported synthetic_source_family: " + fields.sourceFamily);
    }
    if (!is_allowed_segment_kind(fields.sourceFamily, segmentKind)) {
        throw std::runtime_error(context + " has unsupported synthetic_segment_kind: " + segmentKind);
    }

    if (fields.sourceFamily == "dol") {
        require_value(fields.resourceTypeName, "AcDolBinarySegment", "resource_type_name", context);
        require_value(fields.resourceTypeId, "ADOL", "resource_type_id", context);
        if (!starts_with(fields.archivePath, "__OTR__ac/dol_rel/binary_segment/dol/") ||
            !ends_with(fields.archivePath, ".ADOL")) {
            throw std::runtime_error(context + " destination_path must use the DOL ADOL namespace: " +
                                     fields.archivePath);
        }
        return Torch::ResourceType::AcDolBinarySegment;
    }

    if (fields.realSourceMode) {
        throw std::runtime_error(context + " " + familyKey + " must be 'dol': " + fields.sourceFamily);
    }
    require_value(fields.resourceTypeName, "AcRelBinarySegment", "resource_type_name", context);
    require_value(fields.resourceTypeId, "AREL", "resource_type_id", context);
    if (!starts_with(fields.archivePath, "__OTR__ac/dol_rel/binary_segment/rel/") ||
        !ends_with(fields.archivePath, ".AREL")) {
        throw std::runtime_error(context + " destination_path must use the REL AREL namespace: " + fields.archivePath);
    }
    return Torch::ResourceType::AcRelBinarySegment;
}

std::string expected_real_destination_path(const std::string& sourceEvidenceId) {
    if (sourceEvidenceId == "dol_source_header_slice_evidence") {
        return "__OTR__ac/dol_rel/binary_segment/dol/dol_source_header_slice_evidence.ADOL";
    }
    if (sourceEvidenceId == "dol_source_body_sample_slice_evidence") {
        return "__OTR__ac/dol_rel/binary_segment/dol/dol_source_body_sample_slice_evidence.ADOL";
    }
    return {};
}

std::string expected_real_dol_classification(const std::string& sourceEvidenceId) {
    if (sourceEvidenceId == "dol_source_header_slice_evidence") {
        return "dol_header";
    }
    if (sourceEvidenceId == "dol_source_body_sample_slice_evidence") {
        return "dol_body_sample";
    }
    return {};
}

RealSourceFields read_real_source_fields(YAML::Node node, const CommonPolicyFields& fields,
                                         const std::string& context) {
    if (node["source_families"]) {
        throw std::runtime_error(context + " mixed DOL/REL source families are not supported");
    }
    if (!require_bool(node, "source_image_required", context)) {
        throw std::runtime_error(context + " source_image_required must be true for real-source DOL entries");
    }

    RealSourceFields real;
    if (node["source_image_path"]) {
        throw std::runtime_error(context + " source_image_path must not be serialized in real-source config");
    }
    real.sourceImageEnvVar = require_scalar(node, "source_image_env_var", context);
    const char* sourceImagePath = std::getenv(real.sourceImageEnvVar.c_str());
    if (sourceImagePath == nullptr || sourceImagePath[0] == '\0') {
        throw std::runtime_error(context + " source image is missing");
    }
    real.sourceImagePath = sourceImagePath;
    real.normalizedSourcePathLabel = require_scalar(node, "normalized_source_path_label", context);
    real.sourceImageSha256 = require_scalar(node, "source_image_sha256", context);
    real.sourceImageByteSize = require_u64(node, "source_image_byte_size", context);
    real.gameId = require_scalar(node, "game_id", context);
    real.canonicalVersion = require_scalar(node, "canonical_version", context);
    real.sourceEvidenceId = require_scalar(node, "source_evidence_id", context);
    real.sourceFamilyCount = require_u64(node, "source_family_count", context);
    real.sourceSliceCount = require_u64(node, "source_slice_count", context);
    real.totalSourceByteCount = require_u64(node, "total_source_byte_count", context);
    real.sourceOffset = require_u64(node, "source_offset", context);
    real.sourceSize = require_u64(node, "source_size", context);
    real.sourceSha256 = require_scalar(node, "source_sha256", context);
    real.sourceByteCount = require_u64(node, "source_byte_count", context);
    real.endianPolicy = require_scalar(node, "endian_policy", context);
    real.byteSwapPolicy = require_scalar(node, "byte_swap_policy", context);
    real.dolClassification = require_scalar(node, "dol_classification", context);
    real.destinationNamespace = require_scalar(node, "destination_namespace", context);
    real.factoryName = require_scalar(node, "factory_name", context);
    real.resourceClass = require_scalar(node, "resource_class", context);
    real.runtimeDvdResourceReplacementStatus =
        require_scalar(node, "runtime_dvd_resource_replacement_status", context);
    real.reportLogPayloadStatus = require_scalar(node, "report_log_payload_status", context);
    real.lusTypedRegistrationStatus = require_scalar(node, "lus_typed_registration_status", context);

    require_sha256(real.sourceImageSha256, "source_image_sha256", context);
    require_sha256(real.sourceSha256, "source_sha256", context);
    require_value(fields.sourceFamily, "dol", "source_family", context);
    require_value(real.factoryName, kBinaryFactoryName, "factory_name", context);
    require_value(real.resourceClass, "dol_binary_segment", "resource_class", context);
    require_value(real.destinationNamespace, "__OTR__ac/dol_rel/binary_segment/dol", "destination_namespace", context);
    require_value(real.endianPolicy, "big_endian_resource_header", "endian_policy", context);
    require_value(real.byteSwapPolicy, "no_byte_swap", "byte_swap_policy", context);
    require_value(real.runtimeDvdResourceReplacementStatus, kRuntimeBlocked,
                  "runtime_dvd_resource_replacement_status", context);
    require_value(real.reportLogPayloadStatus, "absent", "report_log_payload_status", context);
    require_value(real.lusTypedRegistrationStatus, kRuntimeBlocked, "lus_typed_registration_status", context);

    const std::string expectedPath = expected_real_destination_path(real.sourceEvidenceId);
    if (expectedPath.empty()) {
        throw std::runtime_error(context + " has unsupported source_evidence_id: " + real.sourceEvidenceId);
    }
    require_value(fields.archivePath, expectedPath, "destination_path", context);
    require_value(real.dolClassification, expected_real_dol_classification(real.sourceEvidenceId),
                  "dol_classification", context);

    if (real.sourceFamilyCount != 1) {
        throw std::runtime_error(context + " source_family_count must be 1");
    }
    if (real.sourceSliceCount == 0 || real.sourceSliceCount > kMaxRealSourceSlices) {
        throw std::runtime_error(context + " source_slice_count must be between 1 and 2");
    }
    if (real.sourceSize == 0 || real.sourceSize > kMaxRealSourceSize) {
        throw std::runtime_error(context + " source_size must be between 1 and 64");
    }
    if (real.sourceByteCount != real.sourceSize) {
        throw std::runtime_error(context + " source_byte_count must match source_size");
    }
    if (real.totalSourceByteCount == 0 || real.totalSourceByteCount > kMaxRealSourceTotalBytes) {
        throw std::runtime_error(context + " total_source_byte_count must be between 1 and 128");
    }
    if (real.sourceOffset > std::numeric_limits<uint64_t>::max() - real.sourceSize) {
        throw std::runtime_error(context + " source_offset plus source_size overflows");
    }

    const SourceIdentity identity = identify_source_image(real.sourceImagePath, context);
    if (identity.size != real.sourceImageByteSize) {
        throw std::runtime_error(context + " source_image_byte_size does not match source image");
    }
    if (identity.sha256 != real.sourceImageSha256) {
        throw std::runtime_error(context + " source_image_sha256 does not match source image");
    }
    if (real.sourceOffset + real.sourceSize > identity.size) {
        throw std::runtime_error(context + " source_offset plus source_size is outside source image");
    }

    return real;
}

std::vector<uint8_t> read_verified_real_source_payload(const RealSourceFields& real, const std::string& context) {
    std::vector<uint8_t> payload = read_source_slice(real.sourceImagePath, real.sourceOffset, real.sourceSize, context);
    const std::string actualSha256 = sha256_bytes(payload);
    if (actualSha256 != real.sourceSha256) {
        throw std::runtime_error(context + " source_sha256 does not match source slice");
    }
    return payload;
}

void add_real_metadata_field(std::map<std::string, std::string>& values, YAML::Node node,
                             const std::string& key, const std::string& context) {
    if (node[key]) {
        values[key] = require_scalar(node, key, context);
    }
}

std::string json_escape(const std::string& value) {
    std::ostringstream escaped;
    for (const char c : value) {
        switch (c) {
            case '\\':
                escaped << "\\\\";
                break;
            case '"':
                escaped << "\\\"";
                break;
            case '\n':
                escaped << "\\n";
                break;
            default:
                escaped << c;
                break;
        }
    }
    return escaped.str();
}

std::string stable_json(const std::map<std::string, std::string>& values) {
    std::ostringstream json;
    json << "{\n";
    size_t index = 0;
    for (const auto& [key, value] : values) {
        json << "  \"" << json_escape(key) << "\": \"" << json_escape(value) << "\"";
        if (++index != values.size()) {
            json << ",";
        }
        json << "\n";
    }
    json << "}\n";
    return json.str();
}

} // namespace

ExportResult DolRelBinarySegmentExporter::Export(std::ostream& write, std::shared_ptr<IParsedData> raw,
                                                 std::string& entryName, YAML::Node& /*node*/,
                                                 std::string* replacement) {
    const auto data = std::static_pointer_cast<DolRelBinarySegmentData>(raw);
    entryName = data->archivePath;
    if (replacement != nullptr) {
        *replacement = data->archivePath;
    }

    auto writer = LUS::BinaryWriter();
    WriteHeader(writer, data->resourceType, data->resourceVersion);
    writer.Write(static_cast<uint32_t>(data->payloadData.size()));
    for (const uint8_t value : data->payloadData) {
        writer.Write(value);
    }
    writer.Finish(write);
    return std::nullopt;
}

ExportResult DolRelPolicyMetadataExporter::Export(std::ostream& write, std::shared_ptr<IParsedData> raw,
                                                  std::string& entryName, YAML::Node& /*node*/,
                                                  std::string* replacement) {
    const auto data = std::static_pointer_cast<DolRelPolicyMetadataData>(raw);
    entryName = data->archivePath;
    if (replacement != nullptr) {
        *replacement = data->archivePath;
    }
    write << data->json;
    return std::nullopt;
}

std::optional<std::shared_ptr<IParsedData>> DolRelBinarySegmentFactory::parse(std::vector<uint8_t>& /*buffer*/,
                                                                              YAML::Node& node) {
    const std::string context = kBinaryFactoryName;
    const CommonPolicyFields fields = read_common_fields(node, context, kBinaryArchiveVersion);
    std::string segmentKind;
    std::vector<uint8_t> payload;

    if (fields.realSourceMode) {
        const RealSourceFields real = read_real_source_fields(node, fields, context);
        segmentKind = real.dolClassification;
        payload = read_verified_real_source_payload(real, context);
    } else {
        segmentKind = require_scalar(node, "synthetic_segment_kind", context);
        const uint64_t syntheticOffset = require_u64(node, "synthetic_offset", context);
        const uint64_t syntheticSize = require_u64(node, "synthetic_size", context);
        const std::string syntheticSha256 = require_scalar(node, "synthetic_sha256", context);
        const uint64_t syntheticByteCount = require_u64(node, "synthetic_byte_count", context);

        if (syntheticSize == 0 || syntheticSize > kMaxSyntheticSize) {
            throw std::runtime_error(context + " synthetic_size must be between 1 and 64");
        }
        if (syntheticOffset > std::numeric_limits<uint64_t>::max() - syntheticSize) {
            throw std::runtime_error(context + " synthetic_offset plus synthetic_size overflows");
        }
        if (syntheticByteCount != syntheticSize) {
            throw std::runtime_error(context + " synthetic_byte_count must match synthetic_size");
        }
        require_sha256(syntheticSha256, "synthetic_sha256", context);
        payload = make_synthetic_data(fields.configEntryId, fields.sourceFamily, segmentKind, syntheticOffset,
                                      syntheticSize);
    }

    const Torch::ResourceType resourceType = validate_binary_type(fields, segmentKind, context);
    reserve_archive_path(fields.archivePath, context);

    auto data = std::make_shared<DolRelBinarySegmentData>();
    data->payloadData = std::move(payload);
    data->resourceType = resourceType;
    data->resourceVersion = static_cast<int32_t>(fields.resourceVersion);
    data->archivePath = fields.archivePath;
    return data;
}

std::optional<std::shared_ptr<IParsedData>> DolRelPolicyMetadataFactory::parse(std::vector<uint8_t>& /*buffer*/,
                                                                               YAML::Node& node) {
    const std::string context = kMetadataFactoryName;
    const CommonPolicyFields fields = read_common_fields(node, context, kMetadataArchiveVersion);
    const std::string policyKind = require_scalar(node, "policy_kind", context);

    static const std::set<std::string> allowedPolicyKinds = {
        "generated_output_boundary",
        "first_dol_only_factory_report",
        "legal_payload_boundary",
        "runtime_routing_blocker",
    };
    if (fields.realSourceMode && fields.sourceFamily != "dol") {
        throw std::runtime_error(context + " source_family must be 'dol': " + fields.sourceFamily);
    }
    if (!fields.realSourceMode && fields.sourceFamily != "policy") {
        throw std::runtime_error(context + " has unsupported synthetic_source_family: " + fields.sourceFamily);
    }
    if (allowedPolicyKinds.find(policyKind) == allowedPolicyKinds.end()) {
        throw std::runtime_error(context + " has unsupported policy_kind: " + policyKind);
    }
    require_value(fields.resourceTypeName, "AcDolRelPolicyMetadata", "resource_type_name", context);
    require_value(fields.resourceTypeId, "AMET", "resource_type_id", context);
    if (!starts_with(fields.archivePath, "__OTR__ac/validation/dol_rel/") ||
        !ends_with(fields.archivePath, ".json")) {
        throw std::runtime_error(context + " destination_path must use the validation metadata namespace: " +
                                 fields.archivePath);
    }
    reserve_archive_path(fields.archivePath, context);

    auto data = std::make_shared<DolRelPolicyMetadataData>();
    data->archivePath = fields.archivePath;
    std::map<std::string, std::string> values = {
        { "archive_version", fields.archiveVersion },
        { "backend_window_context_status", fields.backendWindowContextStatus },
        { "config_entry_id", fields.configEntryId },
        { "destination_path", fields.archivePath },
        { "game_payload_status", fields.gamePayloadStatus },
        { "generated_output_policy", fields.generatedOutputPolicy },
        { "generated_output_root", fields.generatedOutputRoot },
        { "legal_payload_policy", fields.legalPayloadPolicy },
        { "phase6n_readiness_status", fields.phase6nReadinessStatus },
        { "policy_kind", policyKind },
        { "real_source_read_status", fields.realSourceReadStatus },
        { "renderer_upload_status", fields.rendererUploadStatus },
        { "resource_type_id", fields.resourceTypeId },
        { "resource_type_name", fields.resourceTypeName },
        { "resource_version", std::to_string(fields.resourceVersion) },
        { "runtime_routing_status", fields.runtimeRoutingStatus },
        { "texture_factory_readiness_status", fields.textureFactoryReadinessStatus },
        { "township_runtime_routing_status", fields.townshipRuntimeRoutingStatus },
    };
    if (fields.realSourceMode) {
        values["real_source_mode"] = "true";
        values["source_family"] = fields.sourceFamily;
        add_real_metadata_field(values, node, "normalized_source_path_label", context);
        add_real_metadata_field(values, node, "source_image_sha256", context);
        add_real_metadata_field(values, node, "source_image_byte_size", context);
        add_real_metadata_field(values, node, "game_id", context);
        add_real_metadata_field(values, node, "canonical_version", context);
        add_real_metadata_field(values, node, "source_evidence_id", context);
        add_real_metadata_field(values, node, "source_family_count", context);
        add_real_metadata_field(values, node, "source_slice_count", context);
        add_real_metadata_field(values, node, "total_source_byte_count", context);
        add_real_metadata_field(values, node, "source_byte_cap_per_slice", context);
        add_real_metadata_field(values, node, "source_total_byte_cap", context);
        add_real_metadata_field(values, node, "runtime_dvd_resource_replacement_status", context);
        add_real_metadata_field(values, node, "report_log_payload_status", context);
        add_real_metadata_field(values, node, "lus_typed_registration_status", context);
    } else {
        values["synthetic_source_family"] = fields.sourceFamily;
    }
    data->json = stable_json(values);
    return data;
}

} // namespace AC
