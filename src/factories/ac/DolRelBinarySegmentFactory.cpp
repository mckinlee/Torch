#include "DolRelBinarySegmentFactory.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <map>
#include <set>
#include <sstream>

namespace AC {
namespace {

constexpr const char* kBinaryFactoryName = "AC:DOL_REL_BINARY_SEGMENT";
constexpr const char* kMetadataFactoryName = "AC:DOL_REL_POLICY_METADATA";
constexpr const char* kGeneratedRoot = "fixture-output/dol-rel-binary-segment";
constexpr const char* kGeneratedPolicy = "ignored-local-only";
constexpr const char* kLegalPolicy = "synthetic-only-no-game-payload";
constexpr const char* kBinaryArchiveVersion = "ac-dol-rel-binary-segment-v0";
constexpr const char* kMetadataArchiveVersion = "ac-dol-rel-policy-metadata-v0";
constexpr const char* kRuntimeBlocked = "blocked";
constexpr const char* kTextureBlocked = "blocked";
constexpr const char* kPhase6NBlocked = "blocked";
constexpr const char* kRendererNotExecuted = "not executed";
constexpr const char* kBackendNotCreated = "not created";
constexpr const char* kRealSourceAbsent = "absent";
constexpr const char* kGamePayloadAbsent = "absent";
constexpr const char* kTownshipRuntimeNotImplied = "not implied";
constexpr size_t kMaxSyntheticSize = 64;

std::set<std::string> gArchivePaths;

struct CommonPolicyFields {
    std::string configEntryId;
    std::string syntheticSourceFamily;
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

bool ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() &&
           value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool starts_with(const std::string& value, const std::string& prefix) {
    return value.rfind(prefix, 0) == 0;
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

void require_sha256(const std::string& value, const std::string& context) {
    if (value.size() != 64) {
        throw std::runtime_error(context + " synthetic_sha256 must be 64 lowercase hex characters");
    }
    for (const char c : value) {
        if (!std::isdigit(static_cast<unsigned char>(c)) && (c < 'a' || c > 'f')) {
            throw std::runtime_error(context + " synthetic_sha256 must be 64 lowercase hex characters");
        }
    }
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

CommonPolicyFields read_common_fields(YAML::Node node, const std::string& context, const std::string& archiveVersion) {
    CommonPolicyFields fields;
    fields.configEntryId = require_scalar(node, "config_entry_id", context);
    fields.syntheticSourceFamily = require_scalar(node, "synthetic_source_family", context);
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

    require_value(fields.generatedOutputRoot, kGeneratedRoot, "generated_output_root", context);
    require_value(fields.generatedOutputPolicy, kGeneratedPolicy, "generated_output_policy", context);
    require_value(fields.legalPayloadPolicy, kLegalPolicy, "legal_payload_policy", context);
    require_value(fields.archiveVersion, archiveVersion, "archive_version", context);
    require_value(fields.runtimeRoutingStatus, kRuntimeBlocked, "runtime_routing_status", context);
    require_value(fields.textureFactoryReadinessStatus, kTextureBlocked, "texture_factory_readiness_status", context);
    require_value(fields.phase6nReadinessStatus, kPhase6NBlocked, "phase6n_readiness_status", context);
    require_value(fields.rendererUploadStatus, kRendererNotExecuted, "renderer_upload_status", context);
    require_value(fields.backendWindowContextStatus, kBackendNotCreated, "backend_window_context_status", context);
    require_value(fields.realSourceReadStatus, kRealSourceAbsent, "real_source_read_status", context);
    require_value(fields.gamePayloadStatus, kGamePayloadAbsent, "game_payload_status", context);
    require_value(fields.townshipRuntimeRoutingStatus, kTownshipRuntimeNotImplied,
                  "township_runtime_routing_status", context);

    if (fields.resourceVersion != 0) {
        throw std::runtime_error(context + " resource_version must be 0");
    }
    validate_no_external_source(node, context);
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
    if (fields.syntheticSourceFamily != "dol" && fields.syntheticSourceFamily != "rel") {
        throw std::runtime_error(context + " has unsupported synthetic_source_family: " + fields.syntheticSourceFamily);
    }
    if (!is_allowed_segment_kind(fields.syntheticSourceFamily, segmentKind)) {
        throw std::runtime_error(context + " has unsupported synthetic_segment_kind: " + segmentKind);
    }

    if (fields.syntheticSourceFamily == "dol") {
        require_value(fields.resourceTypeName, "AcDolBinarySegment", "resource_type_name", context);
        require_value(fields.resourceTypeId, "ADOL", "resource_type_id", context);
        if (!starts_with(fields.archivePath, "__OTR__ac/dol_rel/binary_segment/dol/") ||
            !ends_with(fields.archivePath, ".ADOL")) {
            throw std::runtime_error(context + " destination_path must use the DOL ADOL namespace: " +
                                     fields.archivePath);
        }
        return Torch::ResourceType::AcDolBinarySegment;
    }

    require_value(fields.resourceTypeName, "AcRelBinarySegment", "resource_type_name", context);
    require_value(fields.resourceTypeId, "AREL", "resource_type_id", context);
    if (!starts_with(fields.archivePath, "__OTR__ac/dol_rel/binary_segment/rel/") ||
        !ends_with(fields.archivePath, ".AREL")) {
        throw std::runtime_error(context + " destination_path must use the REL AREL namespace: " + fields.archivePath);
    }
    return Torch::ResourceType::AcRelBinarySegment;
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
    writer.Write(static_cast<uint32_t>(data->syntheticData.size()));
    for (const uint8_t value : data->syntheticData) {
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
    const std::string segmentKind = require_scalar(node, "synthetic_segment_kind", context);
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
    require_sha256(syntheticSha256, context);

    const Torch::ResourceType resourceType = validate_binary_type(fields, segmentKind, context);
    reserve_archive_path(fields.archivePath, context);

    auto data = std::make_shared<DolRelBinarySegmentData>();
    data->syntheticData = make_synthetic_data(fields.configEntryId, fields.syntheticSourceFamily, segmentKind,
                                              syntheticOffset, syntheticSize);
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
        "legal_payload_boundary",
        "runtime_routing_blocker",
    };
    if (fields.syntheticSourceFamily != "policy") {
        throw std::runtime_error(context + " has unsupported synthetic_source_family: " +
                                 fields.syntheticSourceFamily);
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
    data->json = stable_json({
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
        { "synthetic_source_family", fields.syntheticSourceFamily },
        { "texture_factory_readiness_status", fields.textureFactoryReadinessStatus },
        { "township_runtime_routing_status", fields.townshipRuntimeRoutingStatus },
    });
    return data;
}

} // namespace AC
