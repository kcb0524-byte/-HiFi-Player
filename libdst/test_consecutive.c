/*
 * frame_cnt를 연속으로 증가 (리셋 없음) + 채널수 1로 테스트
 * 그리고 nch=1 vs nch=2 출력 비교
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

/* 프레임 추출 (공통) */
typedef struct {
    uint8_t *data;  /* malloc으로 할당 */
    int size;
} FrameData;

static int extract_frames(const char *iso, FrameData *frames, int max_frames) {
    FILE *f = fopen(iso, "rb");
    if (!f) return 0;

    uint8_t *sec = malloc(SECTOR_SIZE);
    uint8_t *frame_buf = malloc(MAX_DST_SIZE);
    int frame_started=0, frame_size=0, dst_encoded=0;
    int n=0;

    for (int lsn=647; lsn<3000 && n<max_frames; lsn++) {
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
                        frames[n].data = malloc(frame_size);
                        memcpy(frames[n].data, frame_buf, frame_size);
                        frames[n].size=frame_size;
                        n++;
                    }
                    frame_size=0; frame_started=1; dst_encoded=dst_enc;
                }
                if(frame_started&&frame_size+pkts[i].pl<=MAX_DST_SIZE){
                    memcpy(frame_buf+frame_size,ptr,pkts[i].pl);
                    frame_size+=pkts[i].pl;
                }
            }
            ptr+=pkts[i].pl;
        }
    }
    fclose(f); free(frame_buf); free(sec);
    return n;
}

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    /* 프레임 200개 추출 */
    int MAX_F = 200;
    FrameData *frames = calloc(MAX_F, sizeof(FrameData));
    printf("프레임 추출 중...\n");
    int n = extract_frames(iso, frames, MAX_F);
    printf("추출 완료: %d개\n\n", n);

    /* 테스트 1: nch=1, frame_cnt 연속 */
    printf("=== nch=1, frame_cnt 연속 ===\n");
    {
        ebunch D; memset(&D,0,sizeof(D));
        DST_InitDecoder(&D,1,64);
        uint8_t *out=calloc(FRAME_SIZE_64+64,1);
        int ok=0,fail=0;
        for(int i=0;i<n;i++){
            memset(out,0,FRAME_SIZE_64+64);
            int ret=DST_FramDSTDecode(frames[i].data,out,frames[i].size,i,&D);
            if(ret==0){ double r=run_avg(out,FRAME_SIZE_64); if(r>3.0) ok++; else fail++; }
            else fail++;
        }
        printf("성공: %d / %d (%.1f%%)\n", ok, n, ok*100.0/n);
        DST_CloseDecoder(&D); free(out);
    }

    /* 테스트 2: nch=2, frame_cnt 연속 */
    printf("\n=== nch=2, frame_cnt 연속 ===\n");
    {
        ebunch D; memset(&D,0,sizeof(D));
        DST_InitDecoder(&D,2,64);
        uint8_t *out=calloc(FRAME_SIZE_64*2+64,1);
        int ok=0,fail=0;
        for(int i=0;i<n;i++){
            memset(out,0,FRAME_SIZE_64*2+64);
            int ret=DST_FramDSTDecode(frames[i].data,out,frames[i].size,i,&D);
            if(ret==0){
                double r0=run_avg(out,FRAME_SIZE_64);
                double r1=run_avg(out+FRAME_SIZE_64,FRAME_SIZE_64);
                if(r0>3.0) ok++;
                else fail++;
                if(i<10) printf("  F%d ret=0 r0=%.2f r1=%.2f\n",i,r0,r1);
            } else {
                fail++;
                if(i<10) printf("  F%d ret=%d\n",i,ret);
            }
        }
        printf("성공: %d / %d (%.1f%%)\n", ok, n, ok*100.0/n);
        DST_CloseDecoder(&D); free(out);
    }

    /* 테스트 3: nch=2, frame_cnt=0 고정 (매번 리셋 효과) */
    printf("\n=== nch=2, frame_cnt=0 고정 ===\n");
    {
        ebunch D; memset(&D,0,sizeof(D));
        DST_InitDecoder(&D,2,64);
        uint8_t *out=calloc(FRAME_SIZE_64*2+64,1);
        int ok=0,fail=0;
        for(int i=0;i<n;i++){
            /* 매 프레임마다 디코더 리셋 */
            DST_CloseDecoder(&D);
            memset(&D,0,sizeof(D));
            DST_InitDecoder(&D,2,64);
            memset(out,0,FRAME_SIZE_64*2+64);
            int ret=DST_FramDSTDecode(frames[i].data,out,frames[i].size,0,&D);
            if(ret==0){
                double r0=run_avg(out,FRAME_SIZE_64);
                double r1=run_avg(out+FRAME_SIZE_64,FRAME_SIZE_64);
                if(r0>3.0||r1>3.0) ok++;
                else fail++;
                if(i<10) printf("  F%d ret=0 r0=%.2f r1=%.2f\n",i,r0,r1);
            } else {
                fail++;
                if(i<10) printf("  F%d ret=%d\n",i,ret);
            }
        }
        printf("성공: %d / %d (%.1f%%)\n", ok, n, ok*100.0/n);
        DST_CloseDecoder(&D); free(out);
    }

    /* 테스트 4: nch=2, frame_cnt=0 고정, 출력 분석 */
    printf("\n=== nch=2 출력 포맷 분석 (첫 5개 성공 프레임) ===\n");
    {
        ebunch D; memset(&D,0,sizeof(D));
        DST_InitDecoder(&D,2,64);
        uint8_t *out=calloc(FRAME_SIZE_64*2+64,1);
        int shown=0;
        for(int i=0;i<n&&shown<5;i++){
            DST_CloseDecoder(&D); memset(&D,0,sizeof(D)); DST_InitDecoder(&D,2,64);
            memset(out,0,FRAME_SIZE_64*2+64);
            int ret=DST_FramDSTDecode(frames[i].data,out,frames[i].size,0,&D);
            if(ret==0){
                double r0=run_avg(out,FRAME_SIZE_64);
                double r1=run_avg(out+FRAME_SIZE_64,FRAME_SIZE_64);
                if(r0<3.0) continue;
                shown++;
                printf("F%d: r0=%.2f r1=%.2f (sequential ch0+ch1)\n",i,r0,r1);
                /* 인터리브 해석 (바이트 단위) */
                double ri0=run_avg(out,FRAME_SIZE_64*2); /* 전체 */
                printf("  전체 run=%.2f\n",ri0);
                /* ch0만 따로 */
                uint8_t *ch0b=malloc(FRAME_SIZE_64), *ch1b=malloc(FRAME_SIZE_64);
                for(int j=0;j<FRAME_SIZE_64;j++){
                    ch0b[j]=out[j*2];
                    ch1b[j]=out[j*2+1];
                }
                printf("  바이트인터리브 ch0=%.2f ch1=%.2f\n",
                       run_avg(ch0b,FRAME_SIZE_64),run_avg(ch1b,FRAME_SIZE_64));
                free(ch0b); free(ch1b);
                printf("  첫16B: ");
                for(int j=0;j<16;j++) printf("%02X ",out[j]); printf("\n");
                printf("  중간16B(offset 4704): ");
                for(int j=4704;j<4720;j++) printf("%02X ",out[j]); printf("\n");
            }
        }
        DST_CloseDecoder(&D); free(out);
    }

    free(frames);
    return 0;
}
