#include "PlayerClothTextureFactory.h"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace AC {
namespace {

constexpr uint16_t kWidth = 32;
constexpr uint16_t kHeight = 32;
constexpr size_t kImageSize = 0x200;
constexpr size_t kPaletteSize = 0x20;
constexpr uint32_t kImagePackedOffset = 0;
constexpr uint32_t kPalettePackedOffset = kImageSize;
constexpr size_t kPackedSize = kImageSize + kPaletteSize;
constexpr uint32_t kPaletteEntries = 16;
constexpr uint32_t kOtex = 0x4F544558U;
constexpr const char* kFormat = "C4";
constexpr const char* kPaletteFormat = "RGB5A3";

struct PlayerClothSpecification {
    uint32_t index;
    uint64_t imageSourceOffset;
    uint64_t paletteSourceOffset;
    const char* archivePath;
};

constexpr std::array<PlayerClothSpecification, 2> kPlayerClothSpecifications{ {
    { 0, 1454014656, 1453900320,
      "ac/texture/forest_1st/player/cloth-000.OTEX" },
    { 1, 1454015168, 1453900352,
      "ac/texture/forest_1st/player/cloth-001.OTEX" },
} };

const PlayerClothSpecification& requirePlayerClothSpecification(uint32_t index) {
    for (const auto& specification : kPlayerClothSpecifications) {
        if (specification.index == index) {
            return specification;
        }
    }
    throw std::runtime_error(
        "AC:PLAYER_CLOTH_TEXTURE supports only built-in cloth indices 0 and 1");
}

const PlayerClothSpecification& requireExactConfiguration(YAML::Node& node) {
    if (node["source_base_offset"]) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE does not accept source_base_offset");
    }
    if (GetSafeNode<uint32_t>(node, "offset") != 0) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE generic offset must be packed offset 0");
    }
    const auto& specification =
        requirePlayerClothSpecification(GetSafeNode<uint32_t>(node, "cloth_index"));
    if (GetSafeNode<uint32_t>(node, "width") != kWidth ||
        GetSafeNode<uint32_t>(node, "height") != kHeight) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE requires 32x32 dimensions");
    }
    if (GetSafeNode<std::string>(node, "format") != kFormat ||
        GetSafeNode<std::string>(node, "palette_format") != kPaletteFormat) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE requires C4 with an RGB5A3 palette");
    }
    if (GetSafeNode<uint32_t>(node, "palette_entries") != kPaletteEntries) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE requires exactly 16 palette entries");
    }
    if (GetSafeNode<uint32_t>(node, "image_size") != kImageSize ||
        GetSafeNode<uint32_t>(node, "palette_size") != kPaletteSize) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE selected image and palette ranges must be exact");
    }
    if (GetSafeNode<uint32_t>(node, "image_offset") != kImagePackedOffset ||
        GetSafeNode<uint32_t>(node, "palette_offset") != kPalettePackedOffset) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE packed range offsets must be exact");
    }
    auto ranges = node["bounded_ranges"];
    if (!ranges || !ranges.IsSequence() || ranges.size() != 2) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE requires exactly two bounded source ranges");
    }
    auto image = ranges[0];
    auto palette = ranges[1];
    if (!image.IsMap() || image.size() != 3 ||
        GetSafeNode<uint64_t>(image, "source_offset") != specification.imageSourceOffset ||
        GetSafeNode<uint64_t>(image, "size") != kImageSize ||
        GetSafeNode<uint64_t>(image, "packed_offset") != kImagePackedOffset) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE first bounded range must be the exact image");
    }
    if (!palette.IsMap() || palette.size() != 3 ||
        GetSafeNode<uint64_t>(palette, "source_offset") != specification.paletteSourceOffset ||
        GetSafeNode<uint64_t>(palette, "size") != kPaletteSize ||
        GetSafeNode<uint64_t>(palette, "packed_offset") != kPalettePackedOffset) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE second bounded range must be the exact palette");
    }

    std::string path = GetSafeNode<std::string>(node, "destination_path");
    std::replace(path.begin(), path.end(), '\\', '/');
    constexpr const char* prefix = "__OTR__";
    if (path.rfind(prefix, 0) == 0) {
        path.erase(0, 7);
    }
    if (path != specification.archivePath) {
        throw std::runtime_error(
            "AC:PLAYER_CLOTH_TEXTURE destination_path must match the exact cloth index");
    }
    return specification;
}

uint16_t be16(const uint8_t* bytes) {
    return static_cast<uint16_t>((static_cast<uint16_t>(bytes[0]) << 8U) | bytes[1]);
}

uint8_t expand3(uint16_t value) {
    return static_cast<uint8_t>((value * 255U + 3U) / 7U);
}

uint8_t expand4(uint16_t value) {
    return static_cast<uint8_t>((value << 4U) | value);
}

uint8_t expand5(uint16_t value) {
    return static_cast<uint8_t>((value << 3U) | (value >> 2U));
}

std::array<uint8_t, 4> decodeRgb5A3(uint16_t value) {
    if ((value & 0x8000U) == 0) {
        return { expand4((value >> 8U) & 0xFU), expand4((value >> 4U) & 0xFU),
                 expand4(value & 0xFU), expand3((value >> 12U) & 0x7U) };
    }
    return { expand5((value >> 10U) & 0x1FU), expand5((value >> 5U) & 0x1FU),
             expand5(value & 0x1FU), 255 };
}

void put16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value >> 8U));
    out.push_back(static_cast<uint8_t>(value));
}

void put32(std::vector<uint8_t>& out, uint32_t value) {
    out.push_back(static_cast<uint8_t>(value >> 24U));
    out.push_back(static_cast<uint8_t>(value >> 16U));
    out.push_back(static_cast<uint8_t>(value >> 8U));
    out.push_back(static_cast<uint8_t>(value));
}

void put64(std::vector<uint8_t>& out, uint64_t value) {
    put32(out, static_cast<uint32_t>(value >> 32U));
    put32(out, static_cast<uint32_t>(value));
}

} // namespace

std::optional<std::shared_ptr<IParsedData>> PlayerClothTextureFactory::parse(
    std::vector<uint8_t>& buffer, YAML::Node& node) {
    const auto& specification = requireExactConfiguration(node);

    if (buffer.size() != kPackedSize) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE packed input must be exactly 544 bytes");
    }

    const uint8_t* image = buffer.data() + kImagePackedOffset;
    const uint8_t* palette = buffer.data() + kPalettePackedOffset;
    auto parsed = std::make_shared<PlayerClothTextureData>();
    parsed->archivePath = specification.archivePath;
    parsed->rgba.assign(static_cast<size_t>(kWidth) * kHeight * 4U, 0);

    constexpr size_t tilesAcross = kWidth / 8U;
    constexpr size_t tilesDown = kHeight / 8U;
    for (size_t tileY = 0; tileY < tilesDown; ++tileY) {
        for (size_t tileX = 0; tileX < tilesAcross; ++tileX) {
            const size_t tileBase = (tileY * tilesAcross + tileX) * 32U;
            for (size_t y = 0; y < 8; ++y) {
                for (size_t x = 0; x < 8; ++x) {
                    const uint8_t packed = image[tileBase + y * 4U + x / 2U];
                    const uint8_t index = (x & 1U) == 0 ? packed >> 4U : packed & 0xFU;
                    if (index >= kPaletteEntries) {
                        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE C4 index exceeds the palette");
                    }
                    const auto rgba = decodeRgb5A3(be16(palette + index * 2U));
                    const size_t destination =
                        ((tileY * 8U + y) * kWidth + tileX * 8U + x) * 4U;
                    std::copy(rgba.begin(), rgba.end(), parsed->rgba.begin() + destination);
                }
            }
        }
    }
    if (parsed->rgba.size() != 4096U) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE decoded output size is not exact");
    }
    return parsed;
}

ExportResult PlayerClothTextureBinaryExporter::Export(std::ostream& write,
                                                       std::shared_ptr<IParsedData> raw,
                                                       std::string& entryName,
                                                       YAML::Node& /*node*/,
                                                       std::string* replacement) {
    const auto data = std::static_pointer_cast<PlayerClothTextureData>(raw);
    const bool supportedPath = std::any_of(
        kPlayerClothSpecifications.begin(), kPlayerClothSpecifications.end(),
        [&data](const auto& specification) {
            return data->archivePath == specification.archivePath;
        });
    if (!supportedPath || data->rgba.size() != 4096U) {
        throw std::runtime_error("AC:PLAYER_CLOTH_TEXTURE export shape is not exact");
    }
    entryName = data->archivePath;
    if (replacement != nullptr) {
        *replacement = entryName;
    }

    std::vector<uint8_t> out;
    out.reserve(80U + data->rgba.size());
    out.push_back(1);
    out.insert(out.end(), 3, 0);
    put32(out, kOtex);
    put32(out, 0);
    put64(out, 0xDEADBEEFDEADBEEFULL);
    out.resize(64, 0);
    out.insert(out.end(), { 'A', 'C', 'T', 'X' });
    put16(out, kWidth);
    put16(out, kHeight);
    put32(out, 1);
    put32(out, static_cast<uint32_t>(data->rgba.size()));
    out.insert(out.end(), data->rgba.begin(), data->rgba.end());
    write.write(reinterpret_cast<const char*>(out.data()), static_cast<std::streamsize>(out.size()));
    return std::nullopt;
}

} // namespace AC
