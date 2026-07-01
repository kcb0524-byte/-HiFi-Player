/*
 * 실패 프레임마다 디코더 리셋 → 성공률 확인
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
    for(int i=0;i<n;i++) for(int b=7;b>=0;b--){
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

    ebunch D;
    memset(&D, 0, sizeof(D));
    if (DST_InitDecoder(&D, 2, 64) != 0) return 1;

    uint8_t *out = malloc(FRAME_SIZE_64 * 2);
    uint8_t *frame_buf = malloc(MAX_DST_SIZE);
    uint8_t sec[SECTOR_SIZE];

    int frame_started=0, frame_size=0, dst_encoded=0;
    int frame_cnt=0, ok=0, fail=0;
    int consecutive_fail=0;

    FILE *f = fopen(iso, "rb");
    if (!f) return 1;

    for (int lsn = 647; lsn < 3000 && frame_cnt < 200; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sec, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

        uint8_t *ptr = sec;
        uint8_t hdr = *ptr++;
        if ((hdr >> 7) & 1) continue;

        int dst_enc  = (hdr >> 6) & 1;
        int fi_count = (hdr >> 3) & 7;
        int pi_count = hdr & 7;
        if (pi_count == 0) continue;

        struct { int fs, dt, pl; } pkts[8]; int np=0;
        for (int i=0;i<pi_count&&i<7;i++){
            uint8_t b0=ptr[0],b1=ptr[1]; ptr+=2;
            pkts[np].fs=(b0>>7)&1; pkts[np].dt=(b0>>3)&7;
            pkts[np].pl=((b0&7)<<8)|b1; np++;
        }
        /* frame_info 건너뜀 */
        if (dst_enc) ptr += fi_count * 4;

        for (int i=0;i<np;i++){
            if (pkts[i].dt==DATA_TYPE_AUDIO){
                if (pkts[i].fs){
                    if (frame_started && frame_size > 0 && dst_encoded){
                        memset(out, 0, FRAME_SIZE_64*2);
                        int ret = DST_FramDSTDecode(frame_buf, out, frame_size, frame_cnt, &D);
                        double r0 = (ret==0) ? run_avg(out, FRAME_SIZE_64) : 0;
                        double r1 = (ret==0) ? run_avg(out+FRAME_SIZE_64, FRAME_SIZE_64) : 0;

                        if (ret==0 && r0>3.0) {
                            ok++;
                            consecutive_fail=0;
                            printf("F%-4d %5dB ret=0 r0=%.2f r1=%.2f ✓\n",
                                   frame_cnt, frame_size, r0, r1);
                        } else {
                            fail++;
                            consecutive_fail++;
                            /* 연속 실패 시 디코더 리셋 */
                            if (consecutive_fail >= 1) {
                                DST_CloseDecoder(&D);
                                memset(&D, 0, sizeof(D));
                                DST_InitDecoder(&D, 2, 64);
                                consecutive_fail=0;
                                /* frame_cnt도 리셋해야 디코더 내부 카운터와 맞음 */
                                frame_cnt = 0;
                            }
                        }
                        frame_cnt++;
                    }
                    frame_size=0; frame_started=1; dst_encoded=dst_enc;
                }
                if (frame_started && frame_size+pkts[i].pl<=MAX_DST_SIZE){
                    memcpy(frame_buf+frame_size, ptr, pkts[i].pl);
                    frame_size+=pkts[i].pl;
                }
            }
            ptr+=pkts[i].pl;
        }
    }

    printf("\n성공: %d  실패: %d  성공률: %.1f%%\n",
           ok, fail, (ok+fail)>0 ? ok*100.0/(ok+fail) : 0);

    fclose(f);
    DST_CloseDecoder(&D);
    free(out); free(frame_buf);
    return 0;
}
