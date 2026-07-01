/*
 * DST (Direct Stream Transfer) 디코더 코어
 * IEC 62074-1 기반 구현
 * sacd-ripper 프로젝트 알고리즘 참조
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_core.h"

/* ── 확률 테이블 (IEC 62074-1 Annex C) ─────────────────────── */
static const uint8_t P_table[128] = {
    128, 123, 118, 114, 109, 105, 101,  97,  93,  90,  86,  83,  80,  77,  74,  71,
     68,  65,  63,  60,  58,  56,  54,  52,  50,  48,  46,  44,  42,  41,  39,  38,
     36,  35,  33,  32,  31,  30,  29,  27,  26,  25,  24,  23,  22,  22,  21,  20,
     19,  18,  18,  17,  16,  16,  15,  14,  14,  13,  13,  12,  12,  11,  11,  10,
     10,   9,   9,   9,   8,   8,   8,   7,   7,   7,   6,   6,   6,   6,   5,   5,
      5,   5,   4,   4,   4,   4,   4,   4,   3,   3,   3,   3,   3,   3,   3,   2,
      2,   2,   2,   2,   2,   2,   2,   2,   1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,
};

/* ── 비트 리더 ───────────────────────────────────────────────── */
typedef struct {
    const uint8_t *data;
    int            pos;
    int            total_bits;
} BitReader;

static void br_init(BitReader *br, const uint8_t *data, int len) {
    br->data       = data;
    br->pos        = 0;
    br->total_bits = len * 8;
}

static int br_read_bit(BitReader *br) {
    if (br->pos >= br->total_bits) return 0;
    int byte_idx = br->pos >> 3;
    int bit_idx  = 7 - (br->pos & 7);
    br->pos++;
    return (br->data[byte_idx] >> bit_idx) & 1;
}

static int br_read_bits(BitReader *br, int n) {
    int v = 0;
    for (int i = 0; i < n; i++)
        v = (v << 1) | br_read_bit(br);
    return v;
}

/* ── 산술 디코더 ─────────────────────────────────────────────── */
typedef struct {
    BitReader *br;
    uint32_t   A;   /* 구간 크기 */
    uint32_t   C;   /* 코드 레지스터 */
} ArithDec;

static void ac_init(ArithDec *ac, BitReader *br) {
    ac->br = br;
    ac->C  = br_read_bits(br, 8);
    ac->A  = 256;
}

static int ac_decode(ArithDec *ac, int p) {
    /* p = P(1)*256 */
    int bit;
    ac->A--;
    uint32_t t = ((ac->A * (uint32_t)p) + 128) >> 8;
    if (ac->C > t) {
        ac->C -= t + 1;
        ac->A -= t;
        bit = 1;
    } else {
        ac->A = t + 1;
        bit = 0;
    }
    /* 재정규화 */
    while (ac->A < 128) {
        ac->A <<= 1;
        ac->C  = ((ac->C << 1) & 0xFF) | br_read_bit(ac->br);
    }
    return bit;
}

/* ── DST 프레임 디코더 ───────────────────────────────────────── */
#define FILTER_ORDER 16
#define FRAME_SIZE   4704

typedef struct {
    int8_t  coefs[FILTER_ORDER];
    int     history[FILTER_ORDER];
} ChannelState;

struct DSTContext {
    int          channels;
    ChannelState ch[DST_MAX_CHANNELS];
};

DSTContext *dst_create(int channels) {
    DSTContext *ctx = calloc(1, sizeof(DSTContext));
    if (!ctx) return NULL;
    ctx->channels = channels;
    return ctx;
}

void dst_destroy(DSTContext *ctx) {
    free(ctx);
}

void dst_reset(DSTContext *ctx) {
    memset(ctx->ch, 0, sizeof(ctx->ch));
}

/*
 * dst_decode_frame:
 *   frame_data: DST 압축 프레임 데이터
 *   frame_len:  바이트 수
 *   out:        출력 버퍼 (FRAME_SIZE * channels 바이트)
 *   반환값:      0=성공, -1=에러
 */
int dst_decode_frame(DSTContext *ctx,
                     const uint8_t *frame_data, int frame_len,
                     uint8_t *out)
{
    if (!ctx || !frame_data || !out || frame_len <= 0)
        return -1;

    BitReader br;
    br_init(&br, frame_data, frame_len);

    ArithDec ac;
    ac_init(&ac, &br);

    int channels = ctx->channels;

    /* 출력 버퍼 초기화 */
    memset(out, 0, FRAME_SIZE * channels);

    /* 바이트 × 채널 루프: ch0_byte0, ch1_byte0, ch0_byte1, ... */
    for (int bi = 0; bi < FRAME_SIZE; bi++) {
        for (int ch = 0; ch < channels; ch++) {
            ChannelState *cs = &ctx->ch[ch];
            uint8_t byte_val = 0;

            for (int bit_i = 0; bit_i < 8; bit_i++) {
                /* FIR 예측 */
                int pred = 0;
                for (int k = 0; k < FILTER_ORDER; k++)
                    pred += cs->coefs[k] * cs->history[k];

                /* 예측값 → 확률 */
                int idx = abs(pred) >> 3;
                if (idx > 127) idx = 127;
                int p = P_table[idx];
                if (pred < 0) p = 256 - p;

                /* 산술 디코딩 */
                int bit = ac_decode(&ac, p);
                byte_val = (byte_val << 1) | bit;

                /* LMS 적응 필터 업데이트 */
                int err = (pred >= 0) ? (bit ? 0 : -1) : (bit ? 1 : 0);
                /* 더 정확히: err = bit - (pred>=0 ? 1 : 0) */
                err = bit - (pred >= 0 ? 1 : 0);
                if (err != 0) {
                    for (int k = 0; k < FILTER_ORDER; k++) {
                        if (cs->history[k] != 0) {
                            int new_c = cs->coefs[k] + err * (cs->history[k] > 0 ? 1 : -1);
                            if (new_c >  127) new_c =  127;
                            if (new_c < -128) new_c = -128;
                            cs->coefs[k] = (int8_t)new_c;
                        }
                    }
                }

                /* 히스토리 업데이트 (shift right, 새 비트 MSB에) */
                memmove(&cs->history[1], &cs->history[0],
                        (FILTER_ORDER-1) * sizeof(int));
                cs->history[0] = bit ? 1 : -1;  /* +1/-1 표현 */
            }

            out[bi * channels + ch] = byte_val;
        }
    }

    return 0;
}

int dst_frame_size(void) {
    return FRAME_SIZE;
}
