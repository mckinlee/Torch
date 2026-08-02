#include "AcTextureCodec.h"

#include <algorithm>
#include <array>
#include <limits>
#include <ostream>
#include <stdexcept>

namespace AC {
namespace {

constexpr uint32_t kTextureResourceType = 0x4F544558U;

uint16_t ReadBigEndian16(const uint8_t* bytes) {
    return static_cast<uint16_t>((static_cast<uint16_t>(bytes[0]) << 8U) | bytes[1]);
}

uint8_t Expand3(uint16_t value) {
    return static_cast<uint8_t>((value * 255U + 3U) / 7U);
}

uint8_t Expand4(uint16_t value) {
    return static_cast<uint8_t>((value << 4U) | value);
}

uint8_t Expand5(uint16_t value) {
    return static_cast<uint8_t>((value << 3U) | (value >> 2U));
}

std::array<uint8_t, 4> DecodeRgb5A3(uint16_t value) {
    if ((value & 0x8000U) == 0) {
        return {
            Expand4((value >> 8U) & 0xFU),
            Expand4((value >> 4U) & 0xFU),
            Expand4(value & 0xFU),
            Expand3((value >> 12U) & 0x7U),
        };
    }
    return {
        Expand5((value >> 10U) & 0x1FU),
        Expand5((value >> 5U) & 0x1FU),
        Expand5(value & 0x1FU),
        255,
    };
}

void Put16(std::vector<uint8_t>& out, uint16_t value) {
    out.push_back(static_cast<uint8_t>(value >> 8U));
    out.push_back(static_cast<uint8_t>(value));
}

void Put32(std::vector<uint8_t>& out, uint32_t value) {
    out.push_back(static_cast<uint8_t>(value >> 24U));
    out.push_back(static_cast<uint8_t>(value >> 16U));
    out.push_back(static_cast<uint8_t>(value >> 8U));
    out.push_back(static_cast<uint8_t>(value));
}

void Put64(std::vector<uint8_t>& out, uint64_t value) {
    Put32(out, static_cast<uint32_t>(value >> 32U));
    Put32(out, static_cast<uint32_t>(value));
}

} // namespace

std::vector<uint8_t> DecodeC4Rgb5A3(const uint8_t* image, size_t imageSize, const uint8_t* palette, size_t paletteSize,
                                    uint16_t width, uint16_t height) {
    const size_t pixelCount = static_cast<size_t>(width) * height;
    if (image == nullptr || palette == nullptr || width == 0 || height == 0 || width % 8U != 0 || height % 8U != 0 ||
        pixelCount > std::numeric_limits<size_t>::max() / 4U || imageSize != pixelCount / 2U || paletteSize != 32U) {
        throw std::runtime_error("C4/RGB5A3 texture layout is invalid");
    }

    std::vector<uint8_t> rgba(pixelCount * 4U, 0);
    const size_t tilesAcross = width / 8U;
    const size_t tilesDown = height / 8U;
    for (size_t tileY = 0; tileY < tilesDown; ++tileY) {
        for (size_t tileX = 0; tileX < tilesAcross; ++tileX) {
            const size_t tileBase = (tileY * tilesAcross + tileX) * 32U;
            for (size_t y = 0; y < 8U; ++y) {
                for (size_t x = 0; x < 8U; ++x) {
                    const uint8_t packed = image[tileBase + y * 4U + x / 2U];
                    const uint8_t index = (x & 1U) == 0 ? packed >> 4U : packed & 0xFU;
                    const auto color = DecodeRgb5A3(ReadBigEndian16(palette + static_cast<size_t>(index) * 2U));
                    const size_t destination = ((tileY * 8U + y) * width + tileX * 8U + x) * 4U;
                    std::copy(color.begin(), color.end(), rgba.begin() + destination);
                }
            }
        }
    }
    return rgba;
}

std::vector<uint8_t> DecodeC8Rgb5A3(const uint8_t* image, size_t imageSize, const uint8_t* palette, size_t paletteSize,
                                    uint16_t paletteEntries, uint16_t width, uint16_t height) {
    if (image == nullptr || palette == nullptr || width == 0 || height == 0 || paletteEntries == 0 ||
        paletteEntries > 256U || width % 8U != 0 || height % 4U != 0 ||
        paletteSize != static_cast<size_t>(paletteEntries) * 2U) {
        throw std::runtime_error("C8/RGB5A3 texture layout is invalid");
    }

    const size_t tilesAcross = width / 8U;
    const size_t tilesDown = height / 4U;
    if (tilesAcross > std::numeric_limits<size_t>::max() / tilesDown) {
        throw std::runtime_error("C8/RGB5A3 texture layout is invalid");
    }
    const size_t tileCount = tilesAcross * tilesDown;
    if (tileCount > std::numeric_limits<size_t>::max() / 32U || imageSize != tileCount * 32U) {
        throw std::runtime_error("C8/RGB5A3 texture layout is invalid");
    }

    const size_t pixelCount = static_cast<size_t>(width) * height;
    if (pixelCount > std::numeric_limits<size_t>::max() / 4U) {
        throw std::runtime_error("C8/RGB5A3 texture layout is invalid");
    }
    std::vector<uint8_t> rgba(pixelCount * 4U, 0);
    for (size_t tileY = 0; tileY < tilesDown; ++tileY) {
        for (size_t tileX = 0; tileX < tilesAcross; ++tileX) {
            const size_t tileBase = (tileY * tilesAcross + tileX) * 32U;
            for (size_t y = 0; y < 4U; ++y) {
                for (size_t x = 0; x < 8U; ++x) {
                    const size_t destinationX = tileX * 8U + x;
                    const size_t destinationY = tileY * 4U + y;
                    const uint8_t index = image[tileBase + y * 8U + x];
                    if (index >= paletteEntries) {
                        throw std::runtime_error("C8/RGB5A3 texture index exceeds the palette");
                    }
                    const auto color = DecodeRgb5A3(ReadBigEndian16(palette + static_cast<size_t>(index) * 2U));
                    const size_t destination = (destinationY * width + destinationX) * 4U;
                    std::copy(color.begin(), color.end(), rgba.begin() + destination);
                }
            }
        }
    }
    return rgba;
}

void WriteRgba32TextureResource(std::ostream& write, const std::vector<uint8_t>& rgba, uint16_t width,
                                uint16_t height) {
    const size_t pixelCount = static_cast<size_t>(width) * height;
    if (width == 0 || height == 0 || pixelCount > std::numeric_limits<size_t>::max() / 4U ||
        rgba.size() != pixelCount * 4U || rgba.size() > std::numeric_limits<uint32_t>::max() ||
        rgba.size() > std::numeric_limits<size_t>::max() - 80U) {
        throw std::runtime_error("RGBA32 texture resource shape is invalid");
    }

    std::vector<uint8_t> out;
    out.reserve(80U + rgba.size());
    out.push_back(1);
    out.insert(out.end(), 3, 0);
    Put32(out, kTextureResourceType);
    Put32(out, 0);
    Put64(out, 0xDEADBEEFDEADBEEFULL);
    out.resize(64, 0);
    out.insert(out.end(), { 'A', 'C', 'T', 'X' });
    Put16(out, width);
    Put16(out, height);
    Put32(out, 1);
    Put32(out, static_cast<uint32_t>(rgba.size()));
    out.insert(out.end(), rgba.begin(), rgba.end());
    write.write(reinterpret_cast<const char*>(out.data()), static_cast<std::streamsize>(out.size()));
    if (!write) {
        throw std::runtime_error("RGBA32 texture resource export failed");
    }
}

} // namespace AC
