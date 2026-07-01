/*
 * sacd-ripper libdstdec 실제 테스트
 * DST_InitDecoder + DST_FramDSTDecode 직접 호출
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "dst_init.h"
#include "dst_fram.h"
#include "types.h"

#define SECTOR_SIZE 2048
#define MAX_FRAME   131072
#define FRAME_SIZE  4704   /* DSD64 bytes/ch */

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

/* 크로스섹터 프레임 추출 */
typedef struct{uint8_t*data;int len;}Frame;

static int extract_frames(const char*iso,int s0,int s1,Frame*out,int maxf){
    FILE*f=fopen(iso,"rb"); if(!f)return -1;
    uint8_t*fbuf=malloc(MAX_FRAME);
    int flen=0,inframe=0,nf=0;
    uint8_t cbuf[MAX_FRAME]; int chave=0,cneed=0,cfs=0,cdt=0;
    uint8_t sec[SECTOR_SIZE];
    for(int lsn=s0;lsn<s1&&nf<maxf;lsn++){
        fseek(f,(long)lsn*SECTOR_SIZE,SEEK_SET);
        if(fread(sec,1,SECTOR_SIZE,f)!=SECTOR_SIZE)break;
        uint8_t hdr=sec[0]; if((hdr>>7)&1)continue;
        int fi=(hdr>>3)&7,pi=hdr&7,ptr=1;
        typedef struct{int fs,dt,pl;}Pkt;
        Pkt pkts[8];int np=0;
        for(int i=0;i<pi&&ptr+2<=SECTOR_SIZE;i++){
            uint8_t b0=sec[ptr],b1=sec[ptr+1];ptr+=2;
            pkts[np].fs=(b0>>7)&1;pkts[np].dt=(b0>>3)&7;
            pkts[np].pl=(b0&7)<<8|b1;np++;
        }
        ptr+=fi*4;
        const uint8_t*pay=sec+ptr;int paylen=SECTOR_SIZE-ptr,sptr=0;
#define PUSH(FS,DT,D,L) do{if((DT)==1||(DT)==2){\
    if(FS){if(inframe&&flen>0&&nf<maxf){out[nf].data=malloc(flen);memcpy(out[nf].data,fbuf,flen);out[nf].len=flen;nf++;}\
    flen=0;inframe=1;}\
    if(inframe&&flen+(int)(L)<MAX_FRAME){memcpy(fbuf+flen,(D),(L));flen+=(L);}}}while(0)
        if(cneed>0){
            int tk=paylen-sptr;if(tk>cneed)tk=cneed;
            memcpy(cbuf+chave,pay+sptr,tk);chave+=tk;cneed-=tk;sptr+=tk;
            if(cneed==0){PUSH(cfs,cdt,cbuf,chave);chave=0;}
        }
        for(int i=0;i<np&&nf<maxf;i++){
            int fs=pkts[i].fs,dt=pkts[i].dt,pl=pkts[i].pl;
            int av=paylen-sptr;
            if(av>=pl){PUSH(fs,dt,pay+sptr,pl);sptr+=pl;}
            else{cfs=fs;cdt=dt;chave=av;cneed=pl-av;
                if(av>0)memcpy(cbuf,pay+sptr,av);break;}
        }
    }
    if(inframe&&flen>0&&nf<maxf){out[nf].data=malloc(flen);memcpy(out[nf].data,fbuf,flen);out[nf].len=flen;nf++;}
    free(fbuf);fclose(f);return nf;
}

int main(void){
    const char*iso="/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    /* 1. 디코더 초기화 */
    ebunch D;
    memset(&D,0,sizeof(D));
    int ret=DST_InitDecoder(&D,2,64); /* 2ch, DSD64 */
    printf("DST_InitDecoder: %d (%s)\n",ret,ret==0?"OK":"FAIL");
    if(ret!=0)return 1;

    /* 2. 프레임 추출 */
    Frame frames[30];
    int nf=extract_frames(iso,647,1000,frames,30);
    printf("추출 프레임: %d\n",nf);
    for(int i=0;i<nf&&i<8;i++) printf("  F%d: %dB\n",i,frames[i].len);

    /* 3. 디코딩 */
    uint8_t *out=malloc(FRAME_SIZE*2);
    printf("\n=== DST 디코딩 ===\n");
    int ok=0;
    for(int fi=0;fi<nf&&fi<20;fi++){
        memset(out,0,FRAME_SIZE*2);
        ret=DST_FramDSTDecode(frames[fi].data, out, frames[fi].len, fi, &D);
        printf("F%d(%dB) ret=%d",fi,frames[fi].len,ret);
        if(ret==0){
            /* MuxedDSD: ch0,ch1 인터리브 (4바이트 단위) */
            /* sacd-ripper 출력: ch0 bytes at [0,2,4,...], ch1 at [1,3,5,...] 또는
               [0..4703]=ch0, [4704..9407]=ch1 — 확인 필요 */
            double r0=run_avg(out,FRAME_SIZE);
            double r1=run_avg(out+FRAME_SIZE,FRAME_SIZE);
            double ri=run_avg(out,FRAME_SIZE*2);
            printf(" ch0_run=%.2f ch1_run=%.2f interleave_run=%.2f",r0,r1,ri);
            printf(" 첫8B: %02X %02X %02X %02X %02X %02X %02X %02X",
                out[0],out[1],out[2],out[3],out[4],out[5],out[6],out[7]);
            if(r0>3.0||r1>3.0) ok=1;
        } else {
            const char*msg=DST_GetErrorMessage(ret);
            printf(" ERR: %s",msg?msg:"unknown");
        }
        printf("\n");
    }

    printf("\n%s\n", ok ? "✓ 성공 — 음악 신호 감지됨!" : "✗ 아직 노이즈");

    DST_CloseDecoder(&D);
    free(out);
    for(int i=0;i<nf;i++) free(frames[i].data);
    return 0;
}
