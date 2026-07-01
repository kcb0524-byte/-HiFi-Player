/*
 * ffmpeg libavcodec DST 디코더 직접 사용
 * arm64: gcc -o dst_via_ffmpeg dst_via_ffmpeg.c \
 *   -I/opt/homebrew/include -L/opt/homebrew/lib \
 *   -lavcodec -lavutil -lavformat
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include <libavcodec/avcodec.h>
#include <libavutil/frame.h>
#include <libavutil/samplefmt.h>

#define SECTOR_SIZE 2048
#define MAX_FRAME   131072

/* ── ISO 크로스섹터 프레임 추출 ─────────────────────────────── */
typedef struct {
    uint8_t *data;
    int      len;
} Frame;

static double run_avg(const uint8_t *d, int n) {
    double s = 0; int c = 0, cur = -1, l = 0;
    for (int i = 0; i < n; i++)
        for (int b = 7; b >= 0; b--) {
            int bit = (d[i]>>b)&1;
            if (cur<0){cur=bit;l=1;}
            else if(bit==cur)l++;
            else{s+=l;c++;cur=bit;l=1;}
        }
    if(l&&c){s+=l;c++;}
    return c?s/c:0;
}

static int extract_frames(const char *iso, int start_lsn, int end_lsn,
                           Frame *out_frames, int max_frames)
{
    FILE *f = fopen(iso, "rb");
    if (!f) return -1;

    uint8_t *frame_buf = malloc(MAX_FRAME);
    int      frame_len = 0, in_frame = 0, nframes = 0;
    uint8_t  carry_buf[MAX_FRAME];
    int      carry_have=0, carry_need=0, carry_fs=0, carry_dt=0;
    uint8_t  sec[SECTOR_SIZE];

    for (int lsn = start_lsn; lsn < end_lsn && nframes < max_frames; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sec, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;
        uint8_t hdr = sec[0];
        if ((hdr>>7)&1) continue;
        int fi=(hdr>>3)&7, pi=hdr&7, ptr=1;

        typedef struct{int fs,dt,pl;}Pkt;
        Pkt pkts[8]; int np=0;
        for(int i=0;i<pi&&ptr+2<=SECTOR_SIZE;i++){
            uint8_t b0=sec[ptr],b1=sec[ptr+1];ptr+=2;
            pkts[np].fs=(b0>>7)&1;
            pkts[np].dt=(b0>>3)&7;
            pkts[np].pl=(b0&7)<<8|b1;
            np++;
        }
        ptr+=fi*4;
        const uint8_t *pay=sec+ptr;
        int paylen=SECTOR_SIZE-ptr, sptr=0;

#define PUSH(FS,DT,DATA,LEN) do { \
    if((DT)==1||(DT)==2){ \
        if(FS){ \
            if(in_frame&&frame_len>0&&nframes<max_frames){ \
                out_frames[nframes].data=malloc(frame_len); \
                memcpy(out_frames[nframes].data,frame_buf,frame_len); \
                out_frames[nframes].len=frame_len; nframes++; \
            } \
            frame_len=0; in_frame=1; \
        } \
        if(in_frame&&frame_len+(LEN)<MAX_FRAME){ \
            memcpy(frame_buf+frame_len,(DATA),(LEN)); frame_len+=(LEN); \
        } \
    } \
} while(0)

        if(carry_need>0){
            int take=paylen-sptr; if(take>carry_need)take=carry_need;
            memcpy(carry_buf+carry_have,pay+sptr,take);
            carry_have+=take; carry_need-=take; sptr+=take;
            if(carry_need==0){PUSH(carry_fs,carry_dt,carry_buf,carry_have);carry_have=0;}
        }

        for(int i=0;i<np&&nframes<max_frames;i++){
            int fs=pkts[i].fs,dt=pkts[i].dt,pl=pkts[i].pl;
            int avail=paylen-sptr;
            if(avail>=pl){
                PUSH(fs,dt,pay+sptr,pl); sptr+=pl;
            } else {
                carry_fs=fs;carry_dt=dt;
                carry_have=avail;carry_need=pl-avail;
                if(avail>0)memcpy(carry_buf,pay+sptr,avail);
                break;
            }
        }
    }
    if(in_frame&&frame_len>0&&nframes<max_frames){
        out_frames[nframes].data=malloc(frame_len);
        memcpy(out_frames[nframes].data,frame_buf,frame_len);
        out_frames[nframes].len=frame_len; nframes++;
    }
    free(frame_buf);
    fclose(f);
    return nframes;
}

int main(void)
{
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    /* ── 프레임 추출 ── */
    Frame frames[20];
    int nf = extract_frames(iso, 647, 1000, frames, 20);
    printf("추출 프레임: %d\n", nf);
    for(int i=0;i<nf&&i<8;i++) printf("  F%d: %dB\n",i,frames[i].len);

    if(nf <= 0) return 1;

    /* ── ffmpeg DST 코덱 초기화 ── */
    const AVCodec *codec = avcodec_find_decoder_by_name("dst");
    if(!codec){fprintf(stderr,"DST 코덱 없음\n");return 1;}
    printf("코덱: %s\n", codec->name);

    AVCodecContext *ctx = avcodec_alloc_context3(codec);
    /* DST DSD64 파라미터 */
    ctx->sample_rate  = 2822400;
    ctx->ch_layout.nb_channels = 2;
    av_channel_layout_default(&ctx->ch_layout, 2);
    ctx->block_align  = 4704;  /* DSD64: 4704 bytes/ch/frame */

    int ret = avcodec_open2(ctx, codec, NULL);
    printf("avcodec_open2: %d (%s)\n", ret, ret==0?"OK":av_err2str(ret));
    if(ret < 0) return 1;

    AVPacket *pkt   = av_packet_alloc();
    AVFrame  *frame = av_frame_alloc();

    /* ── 디코딩 ── */
    printf("\n=== DST 디코딩 ===\n");
    for(int fi=0; fi<nf && fi<8; fi++){
        pkt->data = frames[fi].data;
        pkt->size = frames[fi].len;

        ret = avcodec_send_packet(ctx, pkt);
        printf("F%d(%dB) send=%d", fi, frames[fi].len, ret);

        if(ret==0){
            ret = avcodec_receive_frame(ctx, frame);
            printf(" recv=%d", ret);
            if(ret==0){
                printf(" nb=%d fmt=%d", frame->nb_samples, frame->format);
                if(frame->data[0] && frame->nb_samples>0){
                    double ra = run_avg(frame->data[0], 
                                        frame->nb_samples < 512 ? frame->nb_samples : 512);
                    printf(" run=%.2f", ra);
                    printf(" 첫8B:");
                    for(int k=0;k<8&&k<frame->nb_samples;k++)
                        printf(" %02X", frame->data[0][k]);
                }
            }
        }
        printf("\n");
        av_frame_unref(frame);
    }

    av_packet_free(&pkt);
    av_frame_free(&frame);
    avcodec_free_context(&ctx);
    for(int i=0;i<nf;i++) free(frames[i].data);

    printf("\n완료\n");
    return 0;
}
