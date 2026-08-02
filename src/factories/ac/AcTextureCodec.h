#pragma once

#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <vector>

namespace AC {

std::vector<uint8_t> DecodeC4Rgb5A3(const uint8_t* image, size_t imageSize, const uint8_t* palette, size_t paletteSize,
                                    uint16_t width, uint16_t height);

void WriteRgba32TextureResource(std::ostream& write, const std::vector<uint8_t>& rgba, uint16_t width, uint16_t height);

} // namespace AC
