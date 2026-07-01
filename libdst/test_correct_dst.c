/*
 * 이전에 ch0=3.45~6.81 성공했던 버전 기반
 * 추가 디버깅: ch1=0.00 원인 파악
 * - DST_FramDSTDecode 출력 포맷 확인
 * - 채널 인터리브 vs 순차 배치
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_init.h"
#include "dst_fram.h"
#include "types.h"

#define SECTOR_SIZE    2048
#define MAX_DST_SIZE   131072
#define FRAME_SIZE_64  4704
#define DATA_TYPE_AUDIO 2

static double run_avg(const uint8_t *d, int n) {
    double s=0; int c=0,cur=-1,l=0;
    for(int i=0;i<n;i++)
        for(int b=7;b>=0;b--){
            int bit=(d[i]>>b)&1;
            if(cur<0){cur=bit;l=1;}
            else if(bit==cur)l++;
            else{s+=l;c++;cur=bit;l=1;}
        }
    if(l&&c){s+=l;c++;}
    return c?s/c:0;
}

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    /* 채널 수 테스트: 1ch, 2ch, 6ch */
    for (int nch = 1; nch <= 6; nch += 1) {
        if (nch == 3 || nch == 4 || nch == 5) continue;

        ebunch D;
        memset(&D, 0, sizeof(D));
        int ret = DST_InitDecoder(&D, nch, 64);
        if (ret != 0) continue;

        int buf_size = FRAME_SIZE_64 * nch;
        uint8_t *out       = calloc(1, buf_size + 16);
        uint8_t *frame_buf = malloc(MAX_DST_SIZE);
        uint8_t  sec[SECTOR_SIZE];

        int frame_started = 0;
        int frame_size    = 0;
        int sector_count  = 0;
        int dst_encoded   = 0;
        int frame_cnt     = 0;
        int decoded_ok    = 0;

        FILE *f = fopen(iso, "rb");
        if (!f) { fprintf(stderr, "ISO 열기 실패\n"); return 1; }

        printf("\n=== nch=%d 테스트 ===\n", nch);

        for (int lsn = 647; lsn < 1500 && decoded_ok < 3; lsn++) {
            fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
            if (fread(sec, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

            uint8_t *ptr = sec;
            uint8_t hdr = *ptr++;

            if ((hdr >> 7) & 1) continue;

            int dst_enc  = (hdr >> 6) & 1;
            int fi_count = (hdr >> 3) & 7;
            int pi_count = hdr & 7;
            if (pi_count == 0) continue;

            struct { int fs, dt, pl; } pkts[8];
            int np = 0;
            for (int i = 0; i < pi_count && i < 7; i++) {
                uint8_t b0 = ptr[0], b1 = ptr[1]; ptr += 2;
                pkts[np].fs = (b0 >> 7) & 1;
                pkts[np].dt = (b0 >> 3) & 7;
                pkts[np].pl = ((b0 & 7) << 8) | b1;
                np++;
            }

            struct { int sector_count; } finfos[8];
            int nf = 0;
            if (dst_enc && fi_count > 0) {
                for (int i = 0; i < fi_count && i < 7; i++) {
                    uint8_t byte3 = ptr[3];
                    finfos[nf].sector_count = (byte3 >> 2) & 0x1F;
                    ptr += 4;
                    nf++;
                }
            }

            int finfo_idx = 0;
            for (int i = 0; i < np; i++) {
                if (pkts[i].dt != DATA_TYPE_AUDIO) { ptr += pkts[i].pl; continue; }

                if (pkts[i].fs) {
                    if (frame_started && frame_size > 0 && dst_encoded) {
                        memset(out, 0, buf_size + 16);
                        ret = DST_FramDSTDecode(frame_buf, out, frame_size, frame_cnt, &D);
                        if (ret == 0) {
                            /* 순차 배치: ch0[4704] + ch1[4704] */
                            double r0_seq = run_avg(out,              FRAME_SIZE_64);
                            double r1_seq = run_avg(out+FRAME_SIZE_64, FRAME_SIZE_64);
                            /* 인터리브 (4바이트 단위): ch0|ch1|ch0|ch1... */
                            uint8_t *il0 = malloc(FRAME_SIZE_64);
                            uint8_t *il1 = malloc(FRAME_SIZE_64);
                            if (nch == 2) {
                                for (int k = 0; k < FRAME_SIZE_64/4; k++) {
                                    memcpy(il0+k*4, out+k*8,   4);
                                    memcpy(il1+k*4, out+k*8+4, 4);
                                }
                                double r0_il = run_avg(il0, FRAME_SIZE_64);
                                double r1_il = run_avg(il1, FRAME_SIZE_64);
                                printf("F%d(%dB) 순차: ch0=%.2f ch1=%.2f | 인터리브(4B): ch0=%.2f ch1=%.2f",
                                    frame_cnt, frame_size, r0_seq, r1_seq, r0_il, r1_il);
                                free(il0); free(il1);
                            } else {
                                printf("F%d(%dB) run=%.2f", frame_cnt, frame_size, r0_seq);
                            }
                            /* 첫 32바이트 덤프 */
                            printf(" [");
                            for (int k = 0; k < 16 && k < buf_size; k++)
                                printf("%02X", out[k]);
                            printf("]");
                            if (r0_seq > 3.0) { printf(" ✓"); decoded_ok++; }
                            printf("\n");
                        }
                        frame_cnt++;
                    }

                    frame_size    = 0;
                    frame_started = 1;
                    dst_encoded   = dst_enc;
                    if (finfo_idx < nf) {
                        sector_count = finfos[finfo_idx].sector_count;
                        finfo_idx++;
                    } else {
                        sector_count = 0;
                    }
                }

                if (frame_started && pkts[i].pl > 0) {
                    if (frame_size + pkts[i].pl <= MAX_DST_SIZE) {
                        memcpy(frame_buf + frame_size, ptr, pkts[i].pl);
                        frame_size += pkts[i].pl;
                    }
                    if (dst_encoded && sector_count > 0) sector_count--;
                }
                ptr += pkts[i].pl;
            }
        }

        printf("nch=%d: 디코딩=%d 성공=%d\n", nch, frame_cnt, decoded_ok);
        DST_CloseDecoder(&D);
        free(out); free(frame_buf);
        fclose(f);
    }
    return 0;
}
