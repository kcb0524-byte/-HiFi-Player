/*
 * DST 디코더 테스트 v3 — 크로스섹터 패킷 지원
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_core.h"

#define SECTOR_SIZE 2048
#define MAX_FRAME   131072

/* 패킷 메타 */
typedef struct { int fs, dt, pl; } PktMeta;

/* 크로스섹터 상태 */
static uint8_t  carry_data[MAX_FRAME];
static int      carry_len   = 0;
static PktMeta  carry_pkt;
static int      have_carry  = 0;  /* 아직 데이터가 모자란 패킷 있음 */
static int      carry_need  = 0;  /* 아직 필요한 바이트 수 */

/* 프레임 어셈블러 */
static uint8_t  frame_buf[MAX_FRAME];
static int      frame_len   = 0;
static int      in_frame    = 0;

/* 결과 */
static DSTContext *ctx = NULL;
static uint8_t    out_buf[4704 * 2];
static int        frame_count = 0;
static int        MAX_DECODE  = 5;

static double run_avg(const uint8_t *d, int n) {
    double s = 0; int c = 0, cur = -1, l = 0;
    for (int i = 0; i < n; i++)
        for (int b = 7; b >= 0; b--) {
            int bit = (d[i] >> b) & 1;
            if (cur < 0) { cur = bit; l = 1; }
            else if (bit == cur) l++;
            else { s += l; c++; cur = bit; l = 1; }
        }
    if (l && c) { s += l; c++; }
    return c ? s / c : 0;
}

static void decode_frame(void) {
    if (frame_len <= 0) return;
    printf("프레임 %d: %d바이트 입력\n", frame_count, frame_len);
    int r = dst_decode_frame(ctx, frame_buf, frame_len, out_buf);
    if (r == 0) {
        uint8_t ch0[512], ch1[512];
        for (int i = 0; i < 512; i++) {
            ch0[i] = out_buf[i*2];
            ch1[i] = out_buf[i*2+1];
        }
        double r0 = run_avg(ch0, 512);
        double r1 = run_avg(ch1, 512);
        printf("  ch0_run=%.2f  ch1_run=%.2f\n", r0, r1);
        printf("  ch0 첫8B: %02X %02X %02X %02X %02X %02X %02X %02X\n",
               ch0[0],ch0[1],ch0[2],ch0[3],ch0[4],ch0[5],ch0[6],ch0[7]);
    } else {
        printf("  디코딩 실패 r=%d\n", r);
    }
    frame_count++;
}

static void push_pkt_data(int fs, int dt, const uint8_t *data, int len) {
    if (dt != 1 && dt != 2) return;
    if (fs) {
        if (in_frame && frame_len > 0) decode_frame();
        frame_len = 0;
        in_frame  = 1;
    }
    if (in_frame && frame_len + len < MAX_FRAME) {
        memcpy(frame_buf + frame_len, data, len);
        frame_len += len;
    }
}

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    FILE *f = fopen(iso, "rb");
    if (!f) { fprintf(stderr, "ISO 열기 실패\n"); return 1; }

    ctx = dst_create(2);

    uint8_t sec[SECTOR_SIZE];
    /* carry: 이전 섹터에서 잘린 패킷의 남은 데이터 */
    uint8_t carry_buf[MAX_FRAME];
    int     carry_have = 0;  /* carry_buf에 이미 모은 바이트 */
    int     carry_need2 = 0; /* 아직 필요한 바이트 */
    int     carry_fs   = 0;
    int     carry_dt   = 0;

    printf("DST 크로스섹터 디코딩 테스트\n\n");

    for (int lsn = 647; lsn < 1000 && frame_count < MAX_DECODE; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sec, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

        uint8_t hdr = sec[0];
        if ((hdr >> 7) & 1) {
            /* 타임코드 섹터 — carry는 유지하되 패킷 데이터는 없음 */
            continue;
        }

        int fi = (hdr >> 3) & 7;
        int pi = hdr & 7;

        /* 패킷 메타 파싱 */
        int ptr = 1;
        PktMeta pkts[8];
        int npkts = 0;
        for (int i = 0; i < pi && ptr+2 <= SECTOR_SIZE; i++) {
            uint8_t b0 = sec[ptr], b1 = sec[ptr+1]; ptr += 2;
            pkts[npkts].fs = (b0 >> 7) & 1;
            pkts[npkts].dt = (b0 >> 3) & 7;
            pkts[npkts].pl = (b0 & 7) << 8 | b1;
            npkts++;
        }
        ptr += fi * 4;  /* frame info 건너뜀 */

        /* 페이로드 포인터 */
        const uint8_t *payload = sec + ptr;
        int pay_len = SECTOR_SIZE - ptr;
        int sptr = 0;

        /* carry 패킷 마무리 */
        if (carry_need2 > 0) {
            int avail = pay_len - sptr;
            int take  = (avail < carry_need2) ? avail : carry_need2;
            memcpy(carry_buf + carry_have, payload + sptr, take);
            carry_have  += take;
            carry_need2 -= take;
            sptr        += take;
            if (carry_need2 == 0) {
                push_pkt_data(carry_fs, carry_dt, carry_buf, carry_have);
                carry_have = 0;
            }
            if (frame_count >= MAX_DECODE) break;
        }

        /* 새 패킷들 처리 */
        for (int i = 0; i < npkts && frame_count < MAX_DECODE; i++) {
            int fs = pkts[i].fs;
            int dt = pkts[i].dt;
            int pl = pkts[i].pl;
            int avail = pay_len - sptr;

            if (avail >= pl) {
                /* 패킷 전체가 이 섹터 안에 있음 */
                push_pkt_data(fs, dt, payload + sptr, pl);
                sptr += pl;
            } else {
                /* 크로스섹터 — 남은 부분만 carry에 저장 */
                carry_fs   = fs;
                carry_dt   = dt;
                carry_have = avail;
                carry_need2 = pl - avail;
                if (carry_have > 0)
                    memcpy(carry_buf, payload + sptr, carry_have);
                sptr = pay_len;
                /* 이 섹터에서 더 이상 패킷 없음 */
                break;
            }
        }
    }

    /* 마지막 프레임 */
    if (frame_count < MAX_DECODE && in_frame && frame_len > 0)
        decode_frame();

    dst_destroy(ctx);
    fclose(f);
    printf("\n완료 (총 %d 프레임)\n", frame_count);
    return 0;
}
