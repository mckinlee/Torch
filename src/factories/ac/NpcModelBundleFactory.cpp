#include "NpcModelBundleFactory.h"

#include "Companion.h"
#include "archive/BinaryWrapper.h"
#include "utils/Decompressor.h"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <sstream>

namespace AC {
namespace {

constexpr const char* kDefaultManifestPath = "township/resource_slices.json";
constexpr size_t kLusBinaryResourceHeaderSize = 64;
constexpr std::uint32_t kLusDisplayListType = 0x4F444C54U; // ODLT
constexpr std::uint32_t kLusMatrixType = 0x4F4D5458U;      // OMTX
constexpr std::uint32_t kLusTextureType = 0x4F544558U;     // OTEX
constexpr std::uint32_t kLusVertexType = 0x4F565458U;      // OVTX

struct LusResourceContract {
    const char* extension;
    std::uint32_t type;
    size_t minimumBodySize;
};

struct ModelManifestContract {
    std::set<std::string> exactModelNames;
    std::set<std::string> modelReferenceNames;
    std::map<std::string, size_t> matrixCountsByModelName;
    std::set<std::string> resourcePaths;
};

struct BundleManifestValidation {
    std::set<std::string> archivePaths;
    std::set<std::string> modelNames;
    std::set<std::string> sceneNames;
};

std::string read_symbol(YAML::Node& node, const std::string& entryName) {
    return GetSafeNode(node, "symbol", entryName);
}

std::string normalize_archive_path(std::string path) {
    std::replace(path.begin(), path.end(), '\\', '/');
    if (path.empty()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive path is empty");
    }

    fs::path parsed(path);
    if (parsed.is_absolute()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive path must be relative: " + path);
    }
    for (const fs::path& part : parsed) {
        const std::string text = part.generic_string();
        if (text == "..") {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive path escapes archive_root: " + path);
        }
    }

    return parsed.generic_string();
}

void write_byte_array(std::ostream& write, const std::vector<uint8_t>& data) {
    write << "{\n" << tab_t;
    for (size_t i = 0; i < data.size(); ++i) {
        if ((i % 15 == 0) && i != 0) {
            write << "\n" << tab_t;
        }
        write << "0x" << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(data[i]) << ", ";
    }
    write << "\n};\n";
}

std::vector<char> read_file_bytes(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.is_open()) {
        throw std::runtime_error("Failed to open AC NPC model bundle file: " + path.string());
    }
    return std::vector<char>(std::istreambuf_iterator<char>(input), {});
}

std::uint32_t read_u32(const std::vector<char>& bytes, size_t offset, bool bigEndian) {
    const auto at = [&](size_t index) {
        return static_cast<std::uint32_t>(static_cast<unsigned char>(bytes.at(index)));
    };
    if (bigEndian) {
        return (at(offset) << 24U) | (at(offset + 1U) << 16U) | (at(offset + 2U) << 8U) | at(offset + 3U);
    }
    return at(offset) | (at(offset + 1U) << 8U) | (at(offset + 2U) << 16U) | (at(offset + 3U) << 24U);
}

std::string require_string(YAML::Node node, const std::string& key, const std::string& context) {
    if (!node[key] || !node[key].IsScalar()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " is missing required scalar '" + key + "'");
    }
    return node[key].as<std::string>();
}

std::string require_non_empty_string(YAML::Node node, const std::string& key, const std::string& context) {
    std::string value = require_string(node, key, context);
    if (value.empty()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " has empty scalar '" + key + "'");
    }
    return value;
}

YAML::Node require_sequence(YAML::Node node, const std::string& key) {
    if (!node[key] || !node[key].IsSequence()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest is missing required sequence '" + key + "'");
    }
    return node[key];
}

YAML::Node require_entry_sequence(YAML::Node node, const std::string& key, const std::string& context) {
    if (!node[key] || !node[key].IsSequence()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " is missing required sequence '" + key + "'");
    }
    return node[key];
}

std::optional<std::uint32_t> optional_u32(YAML::Node node, const std::string& context) {
    if (!node || node.IsNull()) {
        return std::nullopt;
    }
    if (!node.IsScalar()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " must be a scalar integer");
    }

    const std::uint64_t value = node.as<std::uint64_t>();
    if (value > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " is outside the uint32 range");
    }
    return static_cast<std::uint32_t>(value);
}

std::uint32_t require_u32(YAML::Node node, const std::string& context) {
    std::optional<std::uint32_t> value = optional_u32(node, context);
    if (!value) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " is missing required scalar integer");
    }
    return *value;
}

std::vector<fs::path> collect_bundle_files(const fs::path& root, YAML::Node& node) {
    std::vector<fs::path> files;
    if (node["archive_files"]) {
        const auto archiveFiles = node["archive_files"];
        if (!archiveFiles.IsSequence()) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive_files must be a sequence");
        }
        for (const auto& item : archiveFiles) {
            files.push_back(root / normalize_archive_path(item.as<std::string>()));
        }
    } else {
        for (const auto& entry : fs::recursive_directory_iterator(root)) {
            if (!entry.is_directory()) {
                files.push_back(entry.path());
            }
        }
    }
    std::sort(files.begin(), files.end());
    return files;
}

std::set<std::string> collect_relative_file_names(const fs::path& root, const std::vector<fs::path>& files) {
    std::set<std::string> names;
    for (const fs::path& file : files) {
        const fs::path relative = fs::relative(file, root);
        const std::string output = normalize_archive_path(relative.generic_string());
        if (output.rfind("..", 0) == 0) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive file escapes archive_root: " + file.string());
        }
        names.insert(output);
    }
    return names;
}

void require_archive_member(const fs::path& root, const std::set<std::string>& archiveFiles, const std::string& path,
                            const std::string& context) {
    const std::string normalized = normalize_archive_path(path);
    if (!archiveFiles.empty() && archiveFiles.find(normalized) == archiveFiles.end()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest references " + context +
                                 " outside archive_files: " + normalized);
    }

    const fs::path fullPath = root / normalized;
    if (!fs::exists(fullPath) || !fs::is_regular_file(fullPath)) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest references missing " + context + ": " + normalized);
    }
}

LusResourceContract require_lus_resource_contract(const std::string& type, const std::string& context) {
    if (type == "DisplayList") {
        return { ".ODLT", kLusDisplayListType, 8 };
    }
    if (type == "Vertex") {
        return { ".OVTX", kLusVertexType, 4 };
    }
    if (type == "Matrix") {
        return { ".OMTX", kLusMatrixType, 64 };
    }
    if (type == "Texture") {
        return { ".OTEX", kLusTextureType, 28 };
    }
    throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " has unsupported LUS resource type: " + type);
}

void validate_lus_resource_file(const fs::path& root,
                                const std::set<std::string>& archiveFiles,
                                const std::string& path,
                                const std::string& type,
                                const std::string& context) {
    const std::string normalized = normalize_archive_path(path);
    const LusResourceContract contract = require_lus_resource_contract(type, context);
    if (fs::path(normalized).extension().generic_string() != contract.extension) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " type '" + type +
                                 "' must use " + contract.extension + ": " + normalized);
    }

    require_archive_member(root, archiveFiles, normalized, context);
    const std::vector<char> bytes = read_file_bytes(root / normalized);
    const size_t minimumSize = kLusBinaryResourceHeaderSize + contract.minimumBodySize;
    if (bytes.size() < minimumSize) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " is too small for type '" + type +
                                 "': " + normalized);
    }

    const unsigned char byteOrder = static_cast<unsigned char>(bytes.at(0));
    if (byteOrder != 0U && byteOrder != 1U) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " has invalid LUS byte order: " + normalized);
    }
    const bool bigEndian = byteOrder == 1U;
    const std::uint32_t actualType = read_u32(bytes, 4, bigEndian);
    if (actualType != contract.type) {
        std::ostringstream expected;
        expected << "0x" << std::hex << std::uppercase << contract.type;
        std::ostringstream actual;
        actual << "0x" << std::hex << std::uppercase << actualType;
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " header type " + actual.str() +
                                 " does not match manifest type '" + type + "' (" + expected.str() +
                                 "): " + normalized);
    }
}

std::set<std::string> collect_named_entries(YAML::Node sequence) {
    std::set<std::string> names;
    for (const auto& item : sequence) {
        if (item["name"] && item["name"].IsScalar()) {
            names.insert(item["name"].as<std::string>());
        }
    }
    return names;
}

void validate_required_names(YAML::Node& node, const std::string& key, const std::set<std::string>& available,
                             const std::string& label) {
    if (!node[key]) {
        if (available.empty()) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest has no " + label);
        }
        return;
    }
    if (!node[key].IsSequence()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + key + " must be a sequence");
    }

    for (const auto& item : node[key]) {
        const std::string expected = item.as<std::string>();
        if (available.find(expected) == available.end()) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE required " + label + " is missing from manifest: " +
                                     expected);
        }
    }
}

std::string model_reference_name(std::string modelName) {
    const std::string marker = ".line_";
    const size_t markerPosition = modelName.rfind(marker);
    if (markerPosition == std::string::npos) {
        return modelName;
    }

    const size_t suffixStart = markerPosition + marker.size();
    if (suffixStart == modelName.size()) {
        return modelName;
    }
    for (size_t i = suffixStart; i < modelName.size(); ++i) {
        if (modelName[i] < '0' || modelName[i] > '9') {
            return modelName;
        }
    }
    return modelName.substr(0, markerPosition);
}

void insert_model_reference_names(ModelManifestContract& contract, const std::string& modelName) {
    contract.modelReferenceNames.insert(modelName);
    contract.modelReferenceNames.insert(model_reference_name(modelName));
}

size_t collect_model_resource_paths(YAML::Node model, std::set<std::string>& paths) {
    paths.insert(normalize_archive_path(require_string(model, "display_list_path", "lus_model_resources entry")));
    paths.insert(normalize_archive_path(require_string(model, "vertex_path", "lus_model_resources entry")));
    paths.insert(normalize_archive_path(require_string(model, "texture_path", "lus_model_resources entry")));
    const std::string palettePath = require_string(model, "palette_path", "lus_model_resources entry");
    if (!palettePath.empty()) {
        paths.insert(normalize_archive_path(palettePath));
    }

    YAML::Node matrixPaths = require_entry_sequence(model, "matrix_paths", "lus_model_resources entry");
    if (matrixPaths.size() == 0) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE lus_model_resources entry has no matrix_paths");
    }
    for (const auto& item : matrixPaths) {
        paths.insert(normalize_archive_path(item.as<std::string>()));
    }

    if (model["texture_bindings"]) {
        if (!model["texture_bindings"].IsSequence()) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE texture_bindings must be a sequence");
        }
        for (const auto& binding : model["texture_bindings"]) {
            paths.insert(normalize_archive_path(require_string(binding, "texture_path", "texture binding")));
            const std::string palettePath = require_string(binding, "palette_path", "texture binding");
            if (!palettePath.empty()) {
                paths.insert(normalize_archive_path(palettePath));
            }
        }
    }

    return matrixPaths.size();
}

std::set<std::string> collect_lus_resource_paths(const fs::path& root,
                                                 const std::set<std::string>& archiveFiles,
                                                 YAML::Node lusResources) {
    std::set<std::string> paths;
    std::set<std::string> names;
    for (const auto& resource : lusResources) {
        const std::string context = "lus_resources entry";
        const std::string name = require_non_empty_string(resource, "name", context);
        if (!names.insert(name).second) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE duplicate typed LUS resource name: " + name);
        }
        const std::string path = normalize_archive_path(require_string(resource, "archive_path", context));
        if (!paths.insert(path).second) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE duplicate typed LUS resource archive_path: " + path);
        }
        validate_lus_resource_file(root, archiveFiles, path, require_string(resource, "type", context), context);
    }
    return paths;
}

ModelManifestContract validate_lus_model_resources(YAML::Node lusModelResources,
                                                   const std::set<std::string>& lusResourcePaths) {
    ModelManifestContract contract;
    for (const auto& model : lusModelResources) {
        const std::string modelName = require_non_empty_string(model, "name", "lus_model_resources entry");
        if (!contract.exactModelNames.insert(modelName).second) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE duplicate typed model resource: " + modelName);
        }
        insert_model_reference_names(contract, modelName);

        std::set<std::string> modelPaths;
        const size_t matrixCount = collect_model_resource_paths(model, modelPaths);
        contract.matrixCountsByModelName[modelName] = matrixCount;
        contract.resourcePaths.insert(modelPaths.begin(), modelPaths.end());

        for (const std::string& path : modelPaths) {
            if (lusResourcePaths.find(path) == lusResourcePaths.end()) {
                throw std::runtime_error("AC:NPC_MODEL_BUNDLE typed model resource '" + modelName +
                                         "' references path not declared in lus_resources: " + path);
            }
        }
    }
    return contract;
}

void require_model_reference(const ModelManifestContract& contract, const std::string& modelName,
                             const std::string& context) {
    if (modelName.empty()) {
        return;
    }
    if (contract.modelReferenceNames.find(modelName) == contract.modelReferenceNames.end()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context +
                                 " references missing model resource: " + modelName);
    }
}

void require_matrix_slot_within_model(const ModelManifestContract& contract, const std::string& modelName,
                                      std::uint32_t matrixSlot, const std::string& context) {
    const auto it = contract.matrixCountsByModelName.find(modelName);
    if (it == contract.matrixCountsByModelName.end()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context +
                                 " references missing typed model resource: " + modelName);
    }
    if (matrixSlot >= it->second) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE " + context + " matrix slot " +
                                 std::to_string(matrixSlot) + " exceeds model '" + modelName +
                                 "' matrix count " + std::to_string(it->second));
    }
}

std::set<std::string> collect_matrix_table_names(YAML::Node manifest) {
    std::set<std::string> names;
    if (manifest["entries"]) {
        for (const auto& entry : require_sequence(manifest, "entries")) {
            if (entry["name"] && entry["name"].IsScalar()) {
                names.insert(entry["name"].as<std::string>());
            }
        }
    }
    if (manifest["model_roots"]) {
        for (const auto& modelRoot : require_sequence(manifest, "model_roots")) {
            if (modelRoot["matrix_table_slice_name"] && modelRoot["matrix_table_slice_name"].IsScalar()) {
                names.insert(modelRoot["matrix_table_slice_name"].as<std::string>());
            }
        }
    }
    return names;
}

std::set<std::string> validate_scene_instances(YAML::Node sceneInstances,
                                               const ModelManifestContract& modelContract,
                                               const std::set<std::string>& matrixTableNames,
                                               const std::string& requiredPoseKind,
                                               const std::string& requiredBaseMatrixMode) {
    std::set<std::string> sceneNames;
    for (const auto& scene : sceneInstances) {
        const std::string sceneName = require_non_empty_string(scene, "name", "lus_scene_instances entry");
        if (!sceneNames.insert(sceneName).second) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE duplicate LUS scene instance: " + sceneName);
        }

        const std::string modelName = require_non_empty_string(scene, "model_name", "LUS scene '" + sceneName + "'");
        if (modelContract.exactModelNames.find(modelName) == modelContract.exactModelNames.end()) {
            throw std::runtime_error("AC:NPC_MODEL_BUNDLE LUS scene '" + sceneName +
                                     "' references missing typed model resource: " + modelName);
        }

        if (!requiredPoseKind.empty()) {
            const std::string poseKind = require_non_empty_string(scene, "pose_kind", "LUS scene '" + sceneName + "'");
            if (poseKind != requiredPoseKind) {
                throw std::runtime_error("AC:NPC_MODEL_BUNDLE LUS scene '" + sceneName +
                                         "' pose_kind must be '" + requiredPoseKind + "': " + poseKind);
            }
        }

        if (!requiredBaseMatrixMode.empty()) {
            const std::string baseMatrixMode =
                require_non_empty_string(scene, "base_matrix_mode", "LUS scene '" + sceneName + "'");
            if (baseMatrixMode != requiredBaseMatrixMode) {
                throw std::runtime_error("AC:NPC_MODEL_BUNDLE LUS scene '" + sceneName +
                                         "' base_matrix_mode must be '" + requiredBaseMatrixMode +
                                         "': " + baseMatrixMode);
            }
        }

        if (scene["matrix_table_name"] && scene["matrix_table_name"].IsScalar()) {
            const std::string matrixTableName = scene["matrix_table_name"].as<std::string>();
            if (!matrixTableName.empty() && matrixTableNames.find(matrixTableName) == matrixTableNames.end()) {
                throw std::runtime_error("AC:NPC_MODEL_BUNDLE LUS scene '" + sceneName +
                                         "' references missing matrix table: " + matrixTableName);
            }
        }

        if (scene["source_matrix_slots"]) {
            YAML::Node sourceSlots = require_entry_sequence(scene, "source_matrix_slots", "LUS scene '" + sceneName + "'");
            for (const auto& slot : sourceSlots) {
                require_matrix_slot_within_model(modelContract,
                                                 modelName,
                                                 require_u32(slot, "LUS scene '" + sceneName + "' source_matrix_slots entry"),
                                                 "LUS scene '" + sceneName + "'");
            }
        }

        if (scene["matrix_slot_bindings"]) {
            YAML::Node bindings = require_entry_sequence(scene, "matrix_slot_bindings", "LUS scene '" + sceneName + "'");
            for (const auto& binding : bindings) {
                require_matrix_slot_within_model(modelContract,
                                                 modelName,
                                                 require_u32(binding["matrix_slot"],
                                                             "LUS scene '" + sceneName + "' matrix_slot_bindings entry"),
                                                 "LUS scene '" + sceneName + "'");
                if (binding["joint_model_name"] && binding["joint_model_name"].IsScalar()) {
                    require_model_reference(modelContract,
                                            binding["joint_model_name"].as<std::string>(),
                                            "LUS scene '" + sceneName + "' matrix slot binding");
                }
            }
        }

        const std::optional<std::uint32_t> selectedMatrixSlot =
            optional_u32(scene["selected_matrix_slot"], "LUS scene '" + sceneName + "' selected_matrix_slot");
        if (selectedMatrixSlot) {
            require_matrix_slot_within_model(modelContract,
                                             modelName,
                                             *selectedMatrixSlot,
                                             "LUS scene '" + sceneName + "'");
        }

        if (scene["selected_joint_model_name"] && scene["selected_joint_model_name"].IsScalar()) {
            require_model_reference(modelContract,
                                    scene["selected_joint_model_name"].as<std::string>(),
                                    "LUS scene '" + sceneName + "' selected joint");
        }
    }
    return sceneNames;
}

BundleManifestValidation validate_bundle_manifest(const fs::path& root,
                                                  YAML::Node& node,
                                                  const std::set<std::string>& archiveFiles) {
    const std::string primaryModelRoot = require_string(node, "model_root", "asset entry");
    const std::string primarySceneInstance = require_string(node, "scene", "asset entry");
    const std::string requiredPoseKind = GetSafeNode<std::string>(node, "required_pose_kind", "");
    const std::string requiredBaseMatrixMode =
        GetSafeNode<std::string>(node, "required_base_matrix_mode", "");
    const std::string manifestPath =
        normalize_archive_path(GetSafeNode<std::string>(node, "manifest_path", kDefaultManifestPath));
    require_archive_member(root, archiveFiles, manifestPath, "manifest");

    YAML::Node manifest = YAML::LoadFile((root / manifestPath).string());
    if (require_string(manifest, "format", "manifest") != "township.resource_slice_archive") {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest has an unsupported format");
    }

    YAML::Node lusResources = require_sequence(manifest, "lus_resources");
    YAML::Node lusModelResources = require_sequence(manifest, "lus_model_resources");
    YAML::Node sceneInstances = require_sequence(manifest, "lus_scene_instances");
    if (lusResources.size() == 0 || lusModelResources.size() == 0 || sceneInstances.size() == 0) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE manifest must contain typed LUS resources, model bundles, and scene instances");
    }

    const std::set<std::string> lusResourcePaths = collect_lus_resource_paths(root, archiveFiles, lusResources);
    const ModelManifestContract modelContract = validate_lus_model_resources(lusModelResources, lusResourcePaths);
    const std::set<std::string> sceneNames =
        validate_scene_instances(sceneInstances,
                                 modelContract,
                                 collect_matrix_table_names(manifest),
                                 requiredPoseKind,
                                 requiredBaseMatrixMode);

    std::set<std::string> requiredPaths;
    if (manifest["entries"]) {
        YAML::Node entries = require_sequence(manifest, "entries");
        for (const auto& entry : entries) {
            requiredPaths.insert(normalize_archive_path(require_string(entry, "archive_path", "entries entry")));
        }
    }
    requiredPaths.insert(lusResourcePaths.begin(), lusResourcePaths.end());
    requiredPaths.insert(modelContract.resourcePaths.begin(), modelContract.resourcePaths.end());

    for (const std::string& path : requiredPaths) {
        require_archive_member(root, archiveFiles, path, "runtime resource");
    }

    std::set<std::string> modelNames = modelContract.exactModelNames;
    if (manifest["model_roots"]) {
        std::set<std::string> rootNames = collect_named_entries(require_sequence(manifest, "model_roots"));
        modelNames.insert(rootNames.begin(), rootNames.end());
    }
    if (modelNames.find(primaryModelRoot) == modelNames.end()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE primary model_root is missing from manifest: " +
                                 primaryModelRoot);
    }

    if (sceneNames.find(primarySceneInstance) == sceneNames.end()) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE primary scene is missing from manifest: " +
                                 primarySceneInstance);
    }

    validate_required_names(node, "required_model_roots", modelNames, "model roots");
    validate_required_names(node, "required_scene_instances", sceneNames, "scene instances");

    BundleManifestValidation validation;
    validation.archivePaths.insert(manifestPath);
    validation.archivePaths.insert(requiredPaths.begin(), requiredPaths.end());
    validation.modelNames = std::move(modelNames);
    validation.sceneNames = std::move(sceneNames);
    return validation;
}

std::vector<fs::path> collect_manifest_bundle_files(const fs::path& root,
                                                    YAML::Node& node,
                                                    const std::set<std::string>& archiveFiles,
                                                    const BundleManifestValidation& validation) {
    std::set<std::string> paths = validation.archivePaths;
    if (node["additional_archive_files"]) {
        YAML::Node additionalFiles = require_entry_sequence(node, "additional_archive_files", "asset entry");
        for (const auto& item : additionalFiles) {
            const std::string path = normalize_archive_path(item.as<std::string>());
            require_archive_member(root, archiveFiles, path, "additional archive file");
            paths.insert(path);
        }
    }

    std::vector<fs::path> files;
    files.reserve(paths.size());
    for (const std::string& path : paths) {
        files.push_back(root / path);
    }
    return files;
}

bool register_bundle_files(YAML::Node& node) {
    if (!node["archive_root"]) {
        return false;
    }

    const fs::path archiveRoot = GetSafeNode<std::string>(node, "archive_root");
    if (!fs::exists(archiveRoot) || !fs::is_directory(archiveRoot)) {
        throw std::runtime_error("AC:NPC_MODEL_BUNDLE archive_root is not a directory: " + archiveRoot.string());
    }

    const std::vector<fs::path> discoveredFiles = collect_bundle_files(archiveRoot, node);
    const std::set<std::string> archiveFileNames = collect_relative_file_names(archiveRoot, discoveredFiles);
    const BundleManifestValidation validation = validate_bundle_manifest(archiveRoot, node, archiveFileNames);
    const bool manifestOnly = GetSafeNode<bool>(node, "archive_manifest_only", false);
    const std::vector<fs::path> files =
        manifestOnly ? collect_manifest_bundle_files(archiveRoot, node, archiveFileNames, validation) : discoveredFiles;

    bool wroteToWrapper = false;
    for (const fs::path& file : files) {
        const fs::path relative = fs::relative(file, archiveRoot);
        std::string output = normalize_archive_path(relative.generic_string());
        std::vector<char> data = read_file_bytes(file);
        if (Companion::Instance->IsOTRMode() && Companion::Instance->GetCurrentWrapper() != nullptr) {
            Companion::Instance->GetCurrentWrapper()->AddFile(output, data);
            wroteToWrapper = true;
        } else {
            Companion::Instance->RegisterCompanionFile(output, std::move(data));
        }
    }
    return wroteToWrapper;
}

} // namespace

ExportResult NpcModelBundleHeaderExporter::Export(std::ostream& write, std::shared_ptr<IParsedData> /*data*/,
                                                  std::string& entryName, YAML::Node& node,
                                                  std::string* replacement) {
    const auto symbol = read_symbol(node, entryName);

    if (Companion::Instance->IsOTRMode()) {
        write << "static const ALIGN_ASSET(2) char " << symbol << "[] = \"__OTR__" << (*replacement) << "\";\n\n";
        return std::nullopt;
    }

    write << "extern u8 " << symbol << "[];\n";
    return std::nullopt;
}

ExportResult NpcModelBundleCodeExporter::Export(std::ostream& write, std::shared_ptr<IParsedData> raw,
                                                std::string& entryName, YAML::Node& node,
                                                std::string* replacement) {
    const auto symbol = read_symbol(node, entryName);
    const auto offset = GetSafeNode<uint32_t>(node, "offset");
    const auto data = std::static_pointer_cast<RawBuffer>(raw)->mBuffer;

    if (Companion::Instance->IsOTRMode()) {
        write << "static const ALIGN_ASSET(2) char " << symbol << "[] = \"__OTR__" << (*replacement) << "\";\n\n";
        return std::nullopt;
    }

    write << "u8 " << symbol << "[] = ";
    write_byte_array(write, data);

    if (Companion::Instance->IsDebug()) {
        write << "// AC NPC model bundle scaffold size: 0x" << std::hex << std::uppercase << data.size() << "\n";
    }

    return offset + data.size();
}

ExportResult NpcModelBundleBinaryExporter::Export(std::ostream& write, std::shared_ptr<IParsedData> raw,
                                                  std::string& /*entryName*/, YAML::Node& /*node*/,
                                                  std::string* /*replacement*/) {
    auto writer = LUS::BinaryWriter();
    const auto data = std::static_pointer_cast<RawBuffer>(raw)->mBuffer;

    WriteHeader(writer, Torch::ResourceType::Blob, 0);
    writer.Write(static_cast<uint32_t>(data.size()));
    writer.Write(reinterpret_cast<const char*>(data.data()), data.size());
    writer.Finish(write);
    return std::nullopt;
}

std::optional<std::shared_ptr<IParsedData>> NpcModelBundleFactory::parse(std::vector<uint8_t>& buffer,
                                                                         YAML::Node& node) {
    (void)require_string(node, "model_root", "asset entry");
    (void)require_string(node, "scene", "asset entry");
    if (register_bundle_files(node)) {
        node["skip_asset_export"] = true;
    }

    auto [_, segment] = Decompressor::AutoDecode(node, buffer);
    return std::make_shared<RawBuffer>(segment.data, segment.size);
}

} // namespace AC
