#include "ItemBillboardTextureFactory.h"
#include "AcTextureCodec.h"

#include <algorithm>
#include <stdexcept>
#include <string_view>

namespace AC {
namespace {

constexpr uint64_t kCompressedSourceOffset = 1447155436ULL;
constexpr uint32_t kCompressedLogicalSize = 6137393U;
constexpr uint32_t kCompressedStoredSize = 6137408U;
constexpr uint32_t kFamilyFirstOffset = 0xB6AA80U;
constexpr uint32_t kFamilyEndOffset = 0xB73100U;
constexpr uint32_t kMaximumDecompressedSize = 24U * 1024U * 1024U;
constexpr uint32_t kPaletteSize = 0x20U;
constexpr uint32_t kPaletteEntries = 16U;

struct Specification {
    uint32_t textureOffset;
    uint32_t paletteOffset;
    uint32_t textureSize;
    uint16_t width;
    uint16_t height;
    std::string archivePath;
};

std::string NormalizePath(std::string path) {
    std::replace(path.begin(), path.end(), '\\', '/');
    constexpr std::string_view prefix = "__OTR__";
    if (path.rfind(prefix, 0) == 0) path.erase(0, prefix.size());
    return path;
}

bool IsItemName(std::string_view name) {
    if (name.empty() || name.size() > 48U ||
        name.front() == '-' || name.back() == '-') {
        return false;
    }
    for (char character : name) {
        if (!((character >= 'a' && character <= 'z') ||
              (character >= '0' && character <= '9')) &&
            character != '-') {
            return false;
        }
    }
    return true;
}

Specification RequireExactConfiguration(YAML::Node& node) {
    if (node["source_base_offset"]) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE does not accept source_base_offset");
    }
    if (GetSafeNode<uint32_t>(node, "offset") != 0U) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE generic offset must be packed offset 0");
    }
    if (GetSafeNode<std::string>(node, "source_member") !=
        "/foresta.rel.szs") {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE source member must be foresta.rel.szs");
    }
    if (GetSafeNode<uint32_t>(node, "compressed_logical_size") !=
            kCompressedLogicalSize ||
        GetSafeNode<uint32_t>(node, "compressed_stored_size") !=
            kCompressedStoredSize) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE compressed source size is not exact");
    }

    const std::string itemName =
        GetSafeNode<std::string>(node, "item_name");
    if (!IsItemName(itemName)) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE item_name is invalid");
    }
    const uint32_t width =
        GetSafeNode<uint32_t>(node, "width");
    const uint32_t height =
        GetSafeNode<uint32_t>(node, "height");
    if ((width != 16U && width != 32U) || height != width) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE requires 16x16 or 32x32 dimensions");
    }
    if (GetSafeNode<std::string>(node, "format") != "C4" ||
        GetSafeNode<std::string>(node, "palette_format") !=
            "RGB5A3" ||
        GetSafeNode<uint32_t>(node, "palette_entries") !=
            kPaletteEntries) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE requires C4 with a 16-entry RGB5A3 palette");
    }

    const uint32_t textureSize = width * height / 2U;
    if (GetSafeNode<uint32_t>(node, "texture_size") !=
            textureSize ||
        GetSafeNode<uint32_t>(node, "palette_size") !=
            kPaletteSize) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE selected ranges are not exact");
    }
    const uint32_t textureOffset =
        GetSafeNode<uint32_t>(node, "texture_offset");
    const uint32_t paletteOffset =
        GetSafeNode<uint32_t>(node, "palette_offset");
    const auto rangeInsideFamily = [](uint32_t offset, uint32_t size) {
        return offset >= kFamilyFirstOffset &&
            offset <= kFamilyEndOffset &&
            size <= kFamilyEndOffset - offset;
    };
    if (!rangeInsideFamily(textureOffset, textureSize) ||
        !rangeInsideFamily(paletteOffset, kPaletteSize)) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE selected REL range is outside the item family");
    }

    auto ranges = node["bounded_ranges"];
    if (!ranges || !ranges.IsSequence() || ranges.size() != 1U) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE requires one bounded source range");
    }
    auto range = ranges[0];
    if (!range.IsMap() || range.size() != 3U ||
        GetSafeNode<uint64_t>(range, "source_offset") !=
            kCompressedSourceOffset ||
        GetSafeNode<uint32_t>(range, "size") !=
            kCompressedStoredSize ||
        GetSafeNode<uint32_t>(range, "packed_offset") != 0U) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE bounded source range is not exact");
    }

    const std::string archivePath = NormalizePath(
        GetSafeNode<std::string>(node, "destination_path"));
    const std::string expectedPath =
        "ac/texture/item/" + itemName + ".OTEX";
    if (archivePath != expectedPath) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE destination path does not match item_name");
    }
    return {
        textureOffset,
        paletteOffset,
        textureSize,
        static_cast<uint16_t>(width),
        static_cast<uint16_t>(height),
        archivePath,
    };
}

} // namespace

std::optional<std::shared_ptr<IParsedData>>
ItemBillboardTextureFactory::parse(
    std::vector<uint8_t>& buffer, YAML::Node& node) {
    const auto specification = RequireExactConfiguration(node);
    const uint32_t minimumOutputSize = std::max(
        specification.textureOffset + specification.textureSize,
        specification.paletteOffset + kPaletteSize);
    const auto decompressed = DecodeYaz0Member(
        buffer, kCompressedLogicalSize, kCompressedStoredSize,
        minimumOutputSize, kMaximumDecompressedSize,
        "AC:ITEM_BILLBOARD_TEXTURE");

    auto data = std::make_shared<ItemBillboardTextureData>();
    data->archivePath = specification.archivePath;
    data->width = specification.width;
    data->height = specification.height;
    data->rgba = DecodeC4Rgb5A3(
        decompressed.data() + specification.textureOffset,
        specification.textureSize,
        decompressed.data() + specification.paletteOffset,
        kPaletteSize, specification.width, specification.height);
    return data;
}

ExportResult ItemBillboardTextureBinaryExporter::Export(
    std::ostream& write, std::shared_ptr<IParsedData> raw,
    std::string& entryName, YAML::Node& node,
    std::string* replacement) {
    const auto specification = RequireExactConfiguration(node);
    const auto data =
        std::static_pointer_cast<ItemBillboardTextureData>(raw);
    const size_t expectedSize =
        static_cast<size_t>(specification.width) *
        specification.height * 4U;
    if (data->archivePath != specification.archivePath ||
        data->width != specification.width ||
        data->height != specification.height ||
        data->rgba.size() != expectedSize) {
        throw std::runtime_error(
            "AC:ITEM_BILLBOARD_TEXTURE export shape is not exact");
    }
    entryName = data->archivePath;
    if (replacement != nullptr) *replacement = entryName;
    WriteRgba32TextureResource(
        write, data->rgba, data->width, data->height);
    return std::nullopt;
}

} // namespace AC
