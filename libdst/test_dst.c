/*
 * DST 디코더 테스트 — Jeff Beck ISO에서 프레임 추출 후 디코딩
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_core.h"

#define SECTOR_SIZE 2048

static uint8_t sector_buf[SECTOR_SIZE];

/* 섹터에서 dt=2 패킷 추출 (크로스섹터 미지원, 단순 버전) */
static int extract_audio(const uint8_t *sec, uint8_t *out, int out_size,
                         int *frame_start_out)
{
    uint8_t hdr = sec[0];
    if ((hdr >> 7) & 1) return 0;  /* DST 타임코드 */

    int fi = (hdr >> 3) & 7;
    int pi = hdr & 7;

    int ptr = 1;
    int fs_arr[8], dt_arr[8], pl_arr[8];
    int npkts = 0;

    for (int i = 0; i < pi && ptr+2 <= SECTOR_SIZE; i++) {
        uint8_t b0 = sec[ptr], b1 = sec[ptr+1]; ptr += 2;
        fs_arr[npkts] = (b0 >> 7) & 1;
        dt_arr[npkts] = (b0 >> 3) & 7;
        pl_arr[npkts] = (b0 & 7) << 8 | b1;
        npkts++;
    }
    ptr += fi * 4;

    int total = 0;
    int got_fs = 0;
    for (int i = 0; i < npkts; i++) {
        int pl = pl_arr[i];
        if (ptr + pl > SECTOR_SIZE) break;
        if (dt_arr[i] == 1 || dt_arr[i] == 2) {
            if (fs_arr[i]) got_fs = 1;
            if (total + pl <= out_size) {
                memcpy(out + total, sec + ptr, pl);
                total += pl;
            }
        }
        ptr += pl;
    }
    if (frame_start_out) *frame_start_out = got_fs;
    return total;
}

static double run_avg(const uint8_t *data, int n) {
    double sum = 0; int cnt = 0;
    int cur = -1, l = 0;
    for (int i = 0; i < n; i++) {
        for (int b = 7; b >= 0; b--) {
            int bit = (data[i] >> b) & 1;
            if (cur < 0) { cur = bit; l = 1; }
            else if (bit == cur) l++;
            else { sum += l; cnt++; cur = bit; l = 1; }
        }
    }
    if (l > 0 && cnt > 0) { sum += l; cnt++; }
    return cnt > 0 ? sum / cnt : 0;
}

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    FILE *f = fopen(iso, "rb");
    if (!f) { fprintf(stderr, "ISO 열기 실패\n"); return 1; }

    DSTContext *ctx = dst_create(2);
    if (!ctx) { fclose(f); return 1; }

    /* 프레임 버퍼 (넉넉하게) */
    uint8_t *frame_buf = malloc(65536);
    int frame_len = 0;
    int in_frame  = 0;
    int frame_count = 0;

    uint8_t *out = malloc(4704 * 2);

    printf("DST 디코딩 테스트 시작...\n");

    for (int lsn = 648; lsn < 800 && frame_count < 10; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sector_buf, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

        uint8_t tmp[SECTOR_SIZE];
        int fs = 0;
        int n  = extract_audio(sector_buf, tmp, sizeof(tmp), &fs);
        if (n <= 0) continue;

        if (fs) {
            /* 새 프레임 시작 — 이전 프레임 디코딩 */
            if (in_frame && frame_len > 0) {
                int r = dst_decode_frame(ctx, frame_buf, frame_len, out);
                printf("프레임 %2d: %4dB 입력 r=%d\n", frame_count, frame_len, r);
                if (r == 0) {
                    /* 인터리브 기준으로 ch0=짝수바이트, ch1=홀수바이트 */
                    uint8_t ch0[256], ch1[256];
                    for (int i = 0; i < 256; i++) {
                        ch0[i] = out[i*2];
                        ch1[i] = out[i*2+1];
                    }
                    double rl0 = run_avg(ch0, 256);
                    double rl1 = run_avg(ch1, 256);
                    printf("         → ch0_run=%.2f ch1_run=%.2f "
                           "첫8B(ch0): %02X %02X %02X %02X %02X %02X %02X %02X\n",
                           rl0, rl1,
                           out[0],out[2],out[4],out[6],
                           out[8],out[10],out[12],out[14]);
                }
            }
            frame_len = 0;
            in_frame  = 1;
            frame_count++;
        }

        if (in_frame && frame_len + n < 65536) {
            memcpy(frame_buf + frame_len, tmp, n);
            frame_len += n;
        }
    }

    free(frame_buf);
    free(out);
    dst_destroy(ctx);
    fclose(f);
    printf("완료\n");
    return 0;
}
