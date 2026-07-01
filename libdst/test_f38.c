/*
 * F38이 성공했던 정확한 상황 재현
 * LSN별로 추적해서 F38 프레임 데이터의 정확한 위치 파악
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
    DST_InitDecoder(&D, 2, 64);

    uint8_t *out = malloc(FRAME_SIZE_64 * 2);
    uint8_t *frame_buf = malloc(MAX_DST_SIZE);
    uint8_t *sec = malloc(SECTOR_SIZE);

    int frame_started=0, frame_size=0, dst_encoded=0;
    int frame_cnt=0;
    int frame_start_lsn=0;  /* 현재 프레임이 시작된 LSN */

    FILE *f = fopen(iso, "rb");
    if (!f) return 1;

    printf("프레임별 상세 추적 (F35~F42):\n\n");

    for (int lsn=647; lsn<1000 && frame_cnt<45; lsn++) {
        fseek(f, (long)lsn*SECTOR_SIZE, SEEK_SET);
        if (fread(sec,1,SECTOR_SIZE,f)!=SECTOR_SIZE) break;

        uint8_t *ptr=sec;
        uint8_t hdr=*ptr++;
        if ((hdr>>7)&1) continue;

        int dst_enc=(hdr>>6)&1, fi=(hdr>>3)&7, pi=hdr&7;
        if (!pi) continue;

        struct {int fs,dt,pl;} pkts[8]; int np=0;
        for(int i=0;i<pi&&i<7;i++){
            uint8_t b0=ptr[0],b1=ptr[1]; ptr+=2;
            pkts[np].fs=(b0>>7)&1; pkts[np].dt=(b0>>3)&7;
            pkts[np].pl=((b0&7)<<8)|b1; np++;
        }
        if (dst_enc) ptr+=fi*4;

        for(int i=0;i<np;i++){
            if(pkts[i].dt==DATA_TYPE_AUDIO){
                if(pkts[i].fs){
                    if(frame_started&&frame_size>0&&dst_encoded){
                        memset(out,0,FRAME_SIZE_64*2);
                        int ret=DST_FramDSTDecode(frame_buf,out,frame_size,frame_cnt,&D);
                        if (frame_cnt>=35 && frame_cnt<=42) {
                            double r0=(ret==0)?run_avg(out,FRAME_SIZE_64):0;
                            double r1=(ret==0)?run_avg(out+FRAME_SIZE_64,FRAME_SIZE_64):0;
                            printf("F%d: start_lsn=%d size=%d ret=%d r0=%.2f r1=%.2f %s\n",
                                   frame_cnt, frame_start_lsn, frame_size, ret, r0, r1,
                                   (ret==0&&r0>3.0)?"✓":"");
                            if (ret==0) {
                                printf("  첫32B: ");
                                for(int j=0;j<32;j++) printf("%02X",out[j]);
                                printf("\n");
                                printf("  offset4704: ");
                                for(int j=4704;j<4736;j++) printf("%02X",out[j]);
                                printf("\n");
                            }
                        }
                        frame_cnt++;
                    }
                    frame_size=0; frame_started=1; dst_encoded=dst_enc;
                    frame_start_lsn=lsn;
                }
                if(frame_started&&frame_size+pkts[i].pl<=MAX_DST_SIZE){
                    memcpy(frame_buf+frame_size,ptr,pkts[i].pl);
                    frame_size+=pkts[i].pl;
                }
            }
            ptr+=pkts[i].pl;
        }
    }

    /* F38 데이터를 nch=1로도 시도 */
    printf("\n=== F38을 nch=1로 재시도 ===\n");
    {
        ebunch D2; memset(&D2,0,sizeof(D2));
        DST_InitDecoder(&D2,1,64);

        frame_started=0; frame_size=0; dst_encoded=0; frame_cnt=0;
        rewind(f);

        for (int lsn=647; lsn<1000 && frame_cnt<40; lsn++) {
            fseek(f,(long)lsn*SECTOR_SIZE,SEEK_SET);
            if(fread(sec,1,SECTOR_SIZE,f)!=SECTOR_SIZE) break;
            uint8_t *ptr=sec;
            uint8_t hdr=*ptr++;
            if((hdr>>7)&1) continue;
            int dst_enc=(hdr>>6)&1,fi=(hdr>>3)&7,pi=hdr&7;
            if(!pi) continue;
            struct{int fs,dt,pl;}pkts[8]; int np=0;
            for(int i=0;i<pi&&i<7;i++){
                uint8_t b0=ptr[0],b1=ptr[1]; ptr+=2;
                pkts[np].fs=(b0>>7)&1; pkts[np].dt=(b0>>3)&7;
                pkts[np].pl=((b0&7)<<8)|b1; np++;
            }
            if(dst_enc) ptr+=fi*4;
            for(int i=0;i<np;i++){
                if(pkts[i].dt==DATA_TYPE_AUDIO){
                    if(pkts[i].fs){
                        if(frame_started&&frame_size>0&&dst_encoded&&frame_cnt==38){
                            memset(out,0,FRAME_SIZE_64);
                            int ret=DST_FramDSTDecode(frame_buf,out,frame_size,frame_cnt,&D2);
                            printf("F38 nch=1: ret=%d r0=%.2f\n",
                                   ret, (ret==0)?run_avg(out,FRAME_SIZE_64):0.0);
                        }
                        if(frame_started) frame_cnt++;
                        frame_size=0; frame_started=1; dst_encoded=dst_enc;
                    }
                    if(frame_started&&frame_size+pkts[i].pl<=MAX_DST_SIZE){
                        memcpy(frame_buf+frame_size,ptr,pkts[i].pl); frame_size+=pkts[i].pl;
                    }
                }
                ptr+=pkts[i].pl;
            }
        }
        DST_CloseDecoder(&D2);
    }

    fclose(f);
    DST_CloseDecoder(&D);
    free(out); free(frame_buf); free(sec);
    return 0;
}
