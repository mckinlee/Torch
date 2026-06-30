#pragma once

#include "factories/BaseFactory.h"
#include "types/RawBuffer.h"

namespace AC {

struct DolRelBinarySegmentData : IParsedData {
    std::vector<uint8_t> payloadData;
    Torch::ResourceType resourceType;
    int32_t resourceVersion;
    std::string archivePath;
};

struct DolRelPolicyMetadataData : IParsedData {
    std::string json;
    std::string archivePath;
};

class DolRelBinarySegmentExporter : public BaseExporter {
    ExportResult Export(std::ostream& write, std::shared_ptr<IParsedData> data, std::string& entryName,
                        YAML::Node& node, std::string* replacement) override;
};

class DolRelPolicyMetadataExporter : public BaseExporter {
    ExportResult Export(std::ostream& write, std::shared_ptr<IParsedData> data, std::string& entryName,
                        YAML::Node& node, std::string* replacement) override;
};

class DolRelBinarySegmentFactory : public BaseFactory {
public:
    std::optional<std::shared_ptr<IParsedData>> parse(std::vector<uint8_t>& buffer, YAML::Node& data) override;
    std::unordered_map<ExportType, std::shared_ptr<BaseExporter>> GetExporters() override {
        return {
            REGISTER(Binary, DolRelBinarySegmentExporter)
        };
    }
};

class DolRelPolicyMetadataFactory : public BaseFactory {
public:
    std::optional<std::shared_ptr<IParsedData>> parse(std::vector<uint8_t>& buffer, YAML::Node& data) override;
    std::unordered_map<ExportType, std::shared_ptr<BaseExporter>> GetExporters() override {
        return {
            REGISTER(Binary, DolRelPolicyMetadataExporter)
        };
    }
};

} // namespace AC
