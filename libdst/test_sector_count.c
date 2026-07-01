/*
 * sector_count 실제 동작 추적
 * 처음 50개 프레임의 sector_count 변화 출력
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

    int frame_started = 0, frame_size = 0;
    int sector_count = 0, dst_encoded = 0;
    int frame_cnt = 0, ok = 0, fail = 0;

    FILE *f = fopen(iso, "rb");
    if (!f) return 1;

    printf("frame_cnt | frame_size | sector_count_at_decode | ret | run0\n");
    printf("----------+-----------+------------------------+-----+-----\n");

    for (int lsn = 647; lsn < 2000 && frame_cnt < 100; lsn++) {
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
        int finfos[8]; int nf=0;
        if (dst_enc&&fi_count>0) for(int i=0;i<fi_count&&i<7;i++){
            finfos[nf++]=(ptr[3]>>2)&0x1F; ptr+=4;
        }

        int fi_idx=0;
        for (int i=0;i<np;i++){
            if (pkts[i].dt==DATA_TYPE_AUDIO){
                if (pkts[i].fs){
                    /* frame_start: 이전 프레임을 sector_count 관계없이 무조건 디코딩 시도 */
                    if (frame_started && frame_size > 0 && dst_encoded){
                        memset(out, 0, FRAME_SIZE_64*2);
                        int ret = DST_FramDSTDecode(frame_buf, out, frame_size, frame_cnt, &D);
                        double r0 = (ret==0) ? run_avg(out, FRAME_SIZE_64) : 0;
                        printf("F%-4d | %5dB | sc_at_decode=%-3d | %2d | %.2f %s\n",
                               frame_cnt, frame_size, sector_count, ret, r0,
                               (ret==0&&r0>3.0)?"✓":"");
                        if (ret==0&&r0>3.0) ok++;
                        else if (ret!=0) fail++;
                        frame_cnt++;
                    }
                    frame_size=0; frame_started=1; dst_encoded=dst_enc;
                    if (fi_idx<nf){ sector_count=finfos[fi_idx++]; }
                    else sector_count=0;
                    printf("  → new frame sc_init=%d\n", sector_count);
                }
                if (frame_started&&frame_size+pkts[i].pl<=MAX_DST_SIZE){
                    memcpy(frame_buf+frame_size, ptr, pkts[i].pl);
                    frame_size+=pkts[i].pl;
                }
                if (dst_enc&&sector_count>0) sector_count--;
            }
            ptr+=pkts[i].pl;
        }
    }

    printf("\n성공(run>3): %d  실패: %d  합계: %d\n", ok, fail, frame_cnt);
    printf("성공률: %.1f%%\n", frame_cnt>0 ? ok*100.0/frame_cnt : 0);

    fclose(f);
    DST_CloseDecoder(&D);
    free(out); free(frame_buf);
    return 0;
}
