#include "BtiTextureFactory.h"

#include <algorithm>
#include <limits>
#include <stdexcept>

namespace AC {
namespace {

constexpr size_t kHeaderSize = 32;
constexpr uint8_t kC8 = 9;
constexpr uint8_t kRgb5A3 = 2;
constexpr uint32_t kOtex = 0x4F544558U;

uint16_t be16(const uint8_t* p) {
    return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8U) | p[1]);
}

uint32_t be32(const uint8_t* p) {
    return (static_cast<uint32_t>(p[0]) << 24U) |
           (static_cast<uint32_t>(p[1]) << 16U) |
           (static_cast<uint32_t>(p[2]) << 8U) | p[3];
}

void put16(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v >> 8U));
    out.push_back(static_cast<uint8_t>(v));
}

void put32(std::vector<uint8_t>& out, uint32_t v) {
    out.push_back(static_cast<uint8_t>(v >> 24U));
    out.push_back(static_cast<uint8_t>(v >> 16U));
    out.push_back(static_cast<uint8_t>(v >> 8U));
    out.push_back(static_cast<uint8_t>(v));
}

void put64(std::vector<uint8_t>& out, uint64_t v) {
    put32(out, static_cast<uint32_t>(v >> 32U));
    put32(out, static_cast<uint32_t>(v));
}

uint8_t expand3(uint16_t v) { return static_cast<uint8_t>((v * 255U + 3U) / 7U); }
uint8_t expand4(uint16_t v) { return static_cast<uint8_t>((v << 4U) | v); }
uint8_t expand5(uint16_t v) { return static_cast<uint8_t>((v << 3U) | (v >> 2U)); }

std::array<uint8_t, 4> decodeRgb5A3(uint16_t value) {
    if ((value & 0x8000U) == 0) {
        return { expand4((value >> 8U) & 0xFU), expand4((value >> 4U) & 0xFU),
                 expand4(value & 0xFU), expand3((value >> 12U) & 0x7U) };
    }
    return { expand5((value >> 10U) & 0x1FU), expand5((value >> 5U) & 0x1FU),
             expand5(value & 0x1FU), 255 };
}

std::string requiredPath(YAML::Node& node) {
    std::string path = GetSafeNode<std::string>(node, "destination_path");
    std::replace(path.begin(), path.end(), '\\', '/');
    constexpr const char* prefix = "__OTR__";
    if (path.rfind(prefix, 0) == 0) path.erase(0, 7);
    if (path != "ac/texture/forest_2nd/data/boy1.OTEX") {
        throw std::runtime_error("AC:BTI_TEXTURE destination_path must be the production boy1 OTEX path");
    }
    return path;
}

} // namespace

std::optional<std::shared_ptr<IParsedData>> BtiTextureFactory::parse(
    std::vector<uint8_t>& buffer, YAML::Node& node) {
    const size_t offset = GetSafeNode<uint32_t>(node, "offset", 0);
    const size_t size = GetSafeNode<uint32_t>(node, "size", static_cast<uint32_t>(buffer.size() - std::min(offset, buffer.size())));
    if (offset > buffer.size() || size > buffer.size() - offset || size < kHeaderSize) {
        throw std::runtime_error("AC:BTI_TEXTURE input range is truncated or outside the source member");
    }
    const uint8_t* bti = buffer.data() + offset;
    if (bti[0] != kC8 || bti[8] == 0 || bti[9] != kRgb5A3) {
        throw std::runtime_error("AC:BTI_TEXTURE requires C8 indices with an RGB5A3 palette");
    }
    const uint16_t width = be16(bti + 2);
    const uint16_t height = be16(bti + 4);
    const uint16_t paletteCount = be16(bti + 0x0A);
    const uint32_t paletteOffset = be32(bti + 0x0C);
    const uint32_t imageOffset = be32(bti + 0x1C);
    if (width == 0 || height == 0 || paletteCount == 0) {
        throw std::runtime_error("AC:BTI_TEXTURE dimensions and palette must be nonzero");
    }
    const size_t tilesX = (static_cast<size_t>(width) + 7U) / 8U;
    const size_t tilesY = (static_cast<size_t>(height) + 3U) / 4U;
    const size_t imageSize = tilesX * tilesY * 32U;
    const size_t paletteSize = static_cast<size_t>(paletteCount) * 2U;
    if (imageOffset > size || imageSize > size - imageOffset ||
        paletteOffset > size || paletteSize > size - paletteOffset) {
        throw std::runtime_error("AC:BTI_TEXTURE image or palette range exceeds the BTI member");
    }

    auto parsed = std::make_shared<BtiTextureData>();
    parsed->width = width;
    parsed->height = height;
    parsed->archivePath = requiredPath(node);
    parsed->rgba.assign(static_cast<size_t>(width) * height * 4U, 0);
    for (size_t ty = 0; ty < tilesY; ++ty) {
        for (size_t tx = 0; tx < tilesX; ++tx) {
            const size_t tileBase = imageOffset + (ty * tilesX + tx) * 32U;
            for (size_t y = 0; y < 4; ++y) {
                for (size_t x = 0; x < 8; ++x) {
                    const size_t dx = tx * 8U + x;
                    const size_t dy = ty * 4U + y;
                    if (dx >= width || dy >= height) continue;
                    const uint8_t index = bti[tileBase + y * 8U + x];
                    if (index >= paletteCount) {
                        throw std::runtime_error("AC:BTI_TEXTURE C8 index exceeds the palette");
                    }
                    const auto rgba = decodeRgb5A3(be16(bti + paletteOffset + index * 2U));
                    std::copy(rgba.begin(), rgba.end(), parsed->rgba.begin() + (dy * width + dx) * 4U);
                }
            }
        }
    }
    return parsed;
}

ExportResult BtiTextureBinaryExporter::Export(std::ostream& write,
                                               std::shared_ptr<IParsedData> raw,
                                               std::string& entryName,
                                               YAML::Node& /*node*/,
                                               std::string* replacement) {
    const auto data = std::static_pointer_cast<BtiTextureData>(raw);
    entryName = data->archivePath;
    if (replacement != nullptr) *replacement = entryName;

    std::vector<uint8_t> out;
    out.reserve(80U + data->rgba.size());
    out.push_back(1); // big endian
    out.insert(out.end(), 3, 0);
    put32(out, kOtex);
    put32(out, 0);
    put64(out, 0xDEADBEEFDEADBEEFULL);
    out.resize(64, 0);
    out.insert(out.end(), { 'A', 'C', 'T', 'X' });
    put16(out, data->width);
    put16(out, data->height);
    put32(out, 1); // Fast::TextureType::RGBA32bpp
    put32(out, static_cast<uint32_t>(data->rgba.size()));
    out.insert(out.end(), data->rgba.begin(), data->rgba.end());
    write.write(reinterpret_cast<const char*>(out.data()), static_cast<std::streamsize>(out.size()));
    return std::nullopt;
}

} // namespace AC
