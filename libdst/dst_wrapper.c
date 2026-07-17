/*
 * dst_wrapper.c
 * DST 디코더 C 래퍼 — Python ctypes 용 심플 동기식 API
 *
 * 빌드:
 *   macOS:   build_libdst_mac.sh
 *   Windows: build_libdst_win.bat
 *
 * API:
 *   void* dst_wrap_create(int channels, int fs_factor)
 *   int   dst_wrap_decode(void* h, uint8_t* dst_data, int dst_size,
 *                         uint8_t* dsd_out, int dsd_out_size)
 *   int   dst_wrap_frame_output_size(int channels, int fs_factor)
 *   void  dst_wrap_destroy(void* h)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_init.h"
#include "dst_fram.h"
#include "conststr.h"

/*
 * SACD DST 비트 순서 정정 테이블
 * SACD는 DST 압축 비트스트림을 LSB-first로 저장하지만,
 * Philips 참조 디코더의 getbits()는 MSB-first로 읽는다.
 * 따라서 디코딩 전에 각 바이트를 비트 역전해야 한다.
 *
 * bit_rev_table[i] = i의 비트를 역순으로 뒤집은 값
 * 예: 0x0b (00001011) → 0xD0 (11010000)
 *     bit0(DSTCoded=1) → bit7(DSTCoded=1)이 되어 디코더가 올바르게 인식
 */
static const uint8_t bit_rev_table[256] = {
    0x00,0x80,0x40,0xC0,0x20,0xA0,0x60,0xE0,
    0x10,0x90,0x50,0xD0,0x30,0xB0,0x70,0xF0,
    0x08,0x88,0x48,0xC8,0x28,0xA8,0x68,0xE8,
    0x18,0x98,0x58,0xD8,0x38,0xB8,0x78,0xF8,
    0x04,0x84,0x44,0xC4,0x24,0xA4,0x64,0xE4,
    0x14,0x94,0x54,0xD4,0x34,0xB4,0x74,0xF4,
    0x0C,0x8C,0x4C,0xCC,0x2C,0xAC,0x6C,0xEC,
    0x1C,0x9C,0x5C,0xDC,0x3C,0xBC,0x7C,0xFC,
    0x02,0x82,0x42,0xC2,0x22,0xA2,0x62,0xE2,
    0x12,0x92,0x52,0xD2,0x32,0xB2,0x72,0xF2,
    0x0A,0x8A,0x4A,0xCA,0x2A,0xAA,0x6A,0xEA,
    0x1A,0x9A,0x5A,0xDA,0x3A,0xBA,0x7A,0xFA,
    0x06,0x86,0x46,0xC6,0x26,0xA6,0x66,0xE6,
    0x16,0x96,0x56,0xD6,0x36,0xB6,0x76,0xF6,
    0x0E,0x8E,0x4E,0xCE,0x2E,0xAE,0x6E,0xEE,
    0x1E,0x9E,0x5E,0xDE,0x3E,0xBE,0x7E,0xFE,
    0x01,0x81,0x41,0xC1,0x21,0xA1,0x61,0xE1,
    0x11,0x91,0x51,0xD1,0x31,0xB1,0x71,0xF1,
    0x09,0x89,0x49,0xC9,0x29,0xA9,0x69,0xE9,
    0x19,0x99,0x59,0xD9,0x39,0xB9,0x79,0xF9,
    0x05,0x85,0x45,0xC5,0x25,0xA5,0x65,0xE5,
    0x15,0x95,0x55,0xD5,0x35,0xB5,0x75,0xF5,
    0x0D,0x8D,0x4D,0xCD,0x2D,0xAD,0x6D,0xED,
    0x1D,0x9D,0x5D,0xDD,0x3D,0xBD,0x7D,0xFD,
    0x03,0x83,0x43,0xC3,0x23,0xA3,0x63,0xE3,
    0x13,0x93,0x53,0xD3,0x33,0xB3,0x73,0xF3,
    0x0B,0x8B,0x4B,0xCB,0x2B,0xAB,0x6B,0xEB,
    0x1B,0x9B,0x5B,0xDB,0x3B,0xBB,0x7B,0xFB,
    0x07,0x87,0x47,0xC7,0x27,0xA7,0x67,0xE7,
    0x17,0x97,0x57,0xD7,0x37,0xB7,0x77,0xF7,
    0x0F,0x8F,0x4F,0xCF,0x2F,0xAF,0x6F,0xEF,
    0x1F,0x9F,0x5F,0xDF,0x3F,0xBF,0x7F,0xFF
};

/* ── 에러 통계 (디버그용) ────────────────────────────────────── */
static int g_err_cnt[20] = {0};  /* 에러 코드 0-19별 카운트 */
static int g_ok_cnt  = 0;

/* ── 내부 핸들 ───────────────────────────────────────────────── */
typedef struct {
    ebunch D;          /* libdstdec 내부 상태 (heap 포인터 포함) */
    int    channels;
    int    fs_factor;  /* 64=DSD64, 128=DSD128 */
    int    frame_cnt;  /* 누적 프레임 카운터 */
} DstHandle;

/* ── 공개 API ────────────────────────────────────────────────── */

/*
 * dst_wrap_create: 디코더 핸들 생성
 *   channels : 채널 수 (통상 2)
 *   fs_factor: 64 for DSD64 (SACD 표준)
 *   반환      : 핸들 포인터, 실패 시 NULL
 */
void* dst_wrap_create(int channels, int fs_factor)
{
    DstHandle *h = (DstHandle*)calloc(1, sizeof(DstHandle));
    if (!h) return NULL;

    h->channels  = channels;
    h->fs_factor = fs_factor;
    h->frame_cnt = 0;

    if (DST_InitDecoder(&h->D, channels, fs_factor) != 0) {
        free(h);
        return NULL;
    }
    return (void*)h;
}

/*
 * dst_wrap_decode: DST 압축 프레임 → 채널인터리브 DSD 바이트
 *   handle      : dst_wrap_create() 반환값
 *   dst_data    : 압축된 DST 프레임 바이트
 *   dst_size    : 압축 데이터 크기 (바이트)
 *   dsd_out     : 출력 버퍼 (최소 dst_wrap_frame_output_size() 바이트)
 *   dsd_out_size: 출력 버퍼 크기
 *   반환값      : 0=성공, DSTErr_* = 오류 코드
 *
 *   출력 형식: ch0_byte0, ch1_byte0, ch0_byte1, ch1_byte1, ... (바이트 인터리브)
 */
int dst_wrap_decode(void *handle,
                    const uint8_t *dst_data, int dst_size,
                    uint8_t *dsd_out,        int dsd_out_size)
{
    if (!handle || !dst_data || !dsd_out || dst_size <= 0) return -1;

    DstHandle *h = (DstHandle*)handle;
    int needed = (588 * h->fs_factor / 8) * h->channels;   /* 4704*ch for DSD64 */
    if (dsd_out_size < needed) return -2;

    memset(dsd_out, 0, needed);

    /* DSD64 2ch 비압축 = 9408바이트, 압축이 안 되는 최악의 경우도
     * 9408바이트 이내여야 함. 16384는 안전 마진(×1.7) 포함한 상한 */
    if (dst_size > 16384) return -3;  /* 비정상적으로 큰 프레임 거부 */

    /*
     * SACD DST 비트 순서 정정:
     * SACD는 DST 압축 비트스트림을 LSB-first로 저장하나
     * 디코더 getbits()는 MSB-first로 읽음 → 각 바이트를 비트 역전
     */
    uint8_t rev_buf[16384];
    for (int i = 0; i < dst_size; i++)
        rev_buf[i] = bit_rev_table[(uint8_t)dst_data[i]];

    int ret = DST_FramDSTDecode(
                  rev_buf,
                  dsd_out,
                  dst_size,
                  h->frame_cnt,
                  &h->D);

    /* DSTCoded=0 (비압축 raw DSD) 인데 프레임 크기가 너무 작은 경우:
     * 완전한 raw DSD 프레임은 채널당 4704바이트 × 채널 수 = 9408바이트 필요.
     * 그보다 작으면 이 프레임은 실제 raw DSD가 아니라 잘못된 경계에서
     * 시작된 DST AC 프레임 (DSTCoded=1) 이 잘못 판정된 것임.
     * 이 경우 ReadDSDframe이 부족한 버퍼에서 0x00으로 채워진
     * 9408바이트를 출력 → DSD 0x00 = 최대 음압 = 잡음.
     * → 0x55 (DSD 무음) 으로 교체하여 잡음 방지. */
    if (ret == 0 && h->D.FrameHdr.DSTCoded == 0) {
        int expected = h->D.FrameHdr.MaxFrameLen * h->D.FrameHdr.NrOfChannels;
        if (dst_size < expected) {
            memset(dsd_out, 0x55, needed);   /* 0x55 = DSD 무음 (교류비트) */
            ret = -10;   /* 내부 에러: 잘못된 DSTCoded=0 프레임 */
            if (h->frame_cnt < 20)
                fprintf(stderr, "[DST_FAKE0] F#%03d DSTCoded=0 sz=%d < expected=%d → silence\n",
                        h->frame_cnt, dst_size, expected);
        }
    }

    /* 에러 통계 집계 */
    if (ret == 0) {
        g_ok_cnt++;
    } else {
        int ec = (ret >= 0 && ret < 20) ? ret : 19;
        g_err_cnt[ec]++;
    }

    /* 실패 시 디코더 리셋 */
    if (ret != 0) {
        DST_CloseDecoder(&h->D);
        DST_InitDecoder(&h->D, h->channels, h->fs_factor);
    }

    /* 처음 20프레임: 에러 코드 출력 */
    if (h->frame_cnt < 20) {
        fprintf(stderr, "[DST_STAT] F#%03d sz=%4d ret=%-3d %s\n",
            h->frame_cnt, dst_size, ret, (ret == 0) ? "OK" : "FAIL");
    }

    /* 처음 성공한 5프레임: DSD 출력 첫 32바이트 덤프
     * 유효한 DSD 음악 데이터는 0x55/0xAA가 아닌 다양한 패턴이어야 함
     * 예: 0x69, 0x96, 0xA5, 0x6A 등 */
    if (ret == 0 && g_ok_cnt <= 5) {
        fprintf(stderr, "[DSD_OUT] F#%03d first32=", h->frame_cnt);
        for (int i = 0; i < 32 && i < needed; i++)
            fprintf(stderr, "%02x", dsd_out[i]);
        fprintf(stderr, "\n");
    }

    /* 100프레임마다 에러 분포 요약 */
    int total = h->frame_cnt + 1;
    if (total == 100 || total == 500 || total == 1000 || (total % 2000 == 0 && total > 0)) {
        fprintf(stderr, "[DST_SUMMARY] total=%d OK=%d ", total, g_ok_cnt);
        for (int i = 0; i < 20; i++) {
            if (g_err_cnt[i] > 0)
                fprintf(stderr, "err%d=%d ", i, g_err_cnt[i]);
        }
        fprintf(stderr, "\n");
    }

    h->frame_cnt++;
    return ret;
}

/*
 * dst_wrap_frame_output_size: 디코딩 후 DSD 출력 바이트 수
 *   DSD64 2ch → 4704 × 2 = 9408 바이트
 */
int dst_wrap_frame_output_size(int channels, int fs_factor)
{
    return (588 * fs_factor / 8) * channels;
}

/*
 * dst_wrap_destroy: 핸들 해제
 */
void dst_wrap_destroy(void *handle)
{
    if (!handle) return;
    DstHandle *h = (DstHandle*)handle;
    DST_CloseDecoder(&h->D);
    free(h);
}
