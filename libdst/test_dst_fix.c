/*
 * DST 디코더 테스트 v2 — frame_count > 0 버그 수정
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_core.h"

#define SECTOR_SIZE 2048

static uint8_t sector_buf[SECTOR_SIZE];

static int extract_audio(const uint8_t *sec, uint8_t *out, int out_size,
                         int *frame_start_out)
{
    uint8_t hdr = sec[0];
    if ((hdr >> 7) & 1) return 0;

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

    uint8_t *frame_buf = malloc(65536);
    int frame_len = 0;
    int in_frame  = 0;
    int frame_count = 0;  /* 완성된 프레임 수 */

    uint8_t *out = malloc(4704 * 2);

    printf("DST 디코딩 테스트 v2 시작...\n");
    printf("(프레임 시작 감지 → 이전 프레임 디코딩)\n\n");

    for (int lsn = 648; lsn < 900 && frame_count < 5; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sector_buf, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

        uint8_t tmp[SECTOR_SIZE];
        int fs = 0;
        int n  = extract_audio(sector_buf, tmp, sizeof(tmp), &fs);
        if (n <= 0) continue;

        if (fs) {
            /* 새 프레임 시작 — 이전 프레임 디코딩 (frame_count 조건 제거!) */
            if (in_frame && frame_len > 0) {
                printf("프레임 %d: %d바이트 입력\n", frame_count, frame_len);
                int r = dst_decode_frame(ctx, frame_buf, frame_len, out);
                if (r == 0) {
                    /* ch0=짝수인덱스, ch1=홀수인덱스 */
                    uint8_t ch0[512], ch1[512];
                    int ns = (4704 < 512) ? 4704 : 512;
                    for (int i = 0; i < ns; i++) {
                        ch0[i] = out[i*2];
                        ch1[i] = out[i*2+1];
                    }
                    double rl0 = run_avg(ch0, ns);
                    double rl1 = run_avg(ch1, ns);
                    printf("  → ch0_run=%.2f  ch1_run=%.2f\n", rl0, rl1);
                    printf("  → ch0 첫 8B: %02X %02X %02X %02X %02X %02X %02X %02X\n",
                           ch0[0],ch0[1],ch0[2],ch0[3],ch0[4],ch0[5],ch0[6],ch0[7]);
                    printf("  → ch1 첫 8B: %02X %02X %02X %02X %02X %02X %02X %02X\n",
                           ch1[0],ch1[1],ch1[2],ch1[3],ch1[4],ch1[5],ch1[6],ch1[7]);
                } else {
                    printf("  → 디코딩 실패 r=%d\n", r);
                }
                frame_count++;
            }
            frame_len = 0;
            in_frame  = 1;
        }

        if (in_frame && frame_len + n < 65536) {
            memcpy(frame_buf + frame_len, tmp, n);
            frame_len += n;
        }
    }

    /* 마지막 프레임 */
    if (in_frame && frame_len > 0 && frame_count < 5) {
        printf("프레임 %d (마지막): %d바이트\n", frame_count, frame_len);
        int r = dst_decode_frame(ctx, frame_buf, frame_len, out);
        if (r == 0) {
            uint8_t ch0[512];
            int ns = 512;
            for (int i = 0; i < ns; i++) ch0[i] = out[i*2];
            printf("  → ch0_run=%.2f\n", run_avg(ch0, ns));
        }
    }

    free(frame_buf);
    free(out);
    dst_destroy(ctx);
    fclose(f);
    printf("\n완료\n");
    return 0;
}
