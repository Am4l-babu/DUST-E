// =============================================================================
//  crc16.h - CRC-16/CCITT-FALSE, the same one brain/dustebrain/body/protocol.py
//  uses. Check value for "123456789" is 0x29B1; both sides have a test for it.
//
//  The USB line runs alongside motor wiring. Corruption happens, and a line
//  that fails this check is dropped and counted - never guessed at.
// =============================================================================
#pragma once
#include <stdint.h>
#include <stddef.h>

static inline uint16_t crc16_ccitt(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}
