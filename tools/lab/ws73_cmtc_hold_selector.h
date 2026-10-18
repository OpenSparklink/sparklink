/* SPDX-License-Identifier: GPL-2.0-only */
/* Test fixture selector only, not a protocol decoder or production input path.
 *
 * Identify existing SDK110/basic CMTC or SSAP ExchangeInfo responses in a bounded
 * real USB aggregate. A match permits the existing test QEMU hold to retain
 * the entire original transfer; it does not construct/consume/change a reply,
 * establish a generation/lifetime, or grant readiness. The coordinator and
 * independent capture must establish the original controller/connection.
 *
 * Caller provides at least size readable bytes. No other pointer contract.
 * Unknown framing/capabilities are nonmatches, never relaxed test success.
 */
#ifndef WS73_CMTC_HOLD_SELECTOR_H
#define WS73_CMTC_HOLD_SELECTOR_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static unsigned ws73_test_le16(const unsigned char *p)
{
    return p[0] | ((unsigned)p[1] << 8);
}

static uint32_t ws73_test_le32(const unsigned char *p)
{
    return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

static bool ws73_test_has_reply(const unsigned char *data, size_t size,
                               const unsigned char *response, size_t response_size)
{
    size_t offset = 92;
    bool ended = false, found = false;
    unsigned n;

    if (size < 92 || size > 20 * 1024 || ws73_test_le32(data) != 2 ||
        ws73_test_le32(data + 4) != size) {
        return false;
    }
    for (n = 0; n < 24; n++) {
        unsigned length = ws73_test_le16(data + 12 + n * 2);
        unsigned payload;
        const unsigned char *slot, *acb;

        if (!length) {
            ended = true;
            continue;
        }
        if (ended || length < 4 || length > size - offset) {
            return false;
        }
        slot = data + offset;
        payload = ws73_test_le16(slot + 2);
        if (payload > length - 4) {
            return false;
        }
        acb = slot + 4;
        if (slot[0] == 0xa0 && slot[1] == 8 &&
            payload == 5 + response_size && acb[0] == 0xa3 &&
            !(ws73_test_le16(acb + 1) & 0xf000) &&
            ws73_test_le16(acb + 3) == response_size &&
            !memcmp(acb + 5, response, response_size)) {
            found = true;
        }
        offset += length;
    }
    return found && offset == size;
}

static bool ws73_test_is_cmtc_capability_reply(const unsigned char *data, size_t size)
{
    /* TCID2, CapabilityRsp id0, success, basic MTU2042/MPS2047. */
    static const unsigned char response[] = {
        2, 0, 16, 0, 2, 0, 12, 0, 0xe2, 0, 0, 0, 0, 0,
        0xfa, 7, 0xff, 7, 1, 1
    };
    return ws73_test_has_reply(data, size, response, sizeof(response));
}

static bool ws73_test_is_ssap_exchange_reply(const unsigned char *data, size_t size)
{
    /* SMTC TCID10, ordinary ExchangeInfo Response, MTU2042/version1.2.
     * Request opcode2 and response opcode3 are deliberately distinct. */
    static const unsigned char response[] = {
        10, 0, 6, 0, 3, 3, 0xfa, 7, 1, 2
    };
    return ws73_test_has_reply(data, size, response, sizeof(response));
}
#endif
