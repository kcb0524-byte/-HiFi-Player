/*
 * DST 출력 포맷 정밀 분석
 * - 실제 WAV로 저장해서 귀로 확인
 * - 채널 인터리브 방식 확인
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
#define FRAME_SIZE_64  4704   /* bytes per channel per frame */
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

/* WAV 헤더 쓰기 (PCM 16bit) */
static void write_wav_header(FILE *f, int sample_rate, int channels, int num_samples) {
    int byte_rate = sample_rate * channels * 2;
    int block_align = channels * 2;
    int data_size = num_samples * channels * 2;
    int chunk_size = 36 + data_size;

    fwrite("RIFF", 1, 4, f);
    fwrite(&chunk_size, 4, 1, f);
    fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f);
    int fmt_size = 16; fwrite(&fmt_size, 4, 1, f);
    short audio_fmt = 1; fwrite(&audio_fmt, 2, 1, f);
    short ch = channels; fwrite(&ch, 2, 1, f);
    fwrite(&sample_rate, 4, 1, f);
    fwrite(&byte_rate, 4, 1, f);
    fwrite(&block_align, 2, 1, f);
    short bps = 16; fwrite(&bps, 2, 1, f);
    fwrite("data", 1, 4, f);
    fwrite(&data_size, 4, 1, f);
}

/* DSD 바이트 → PCM 샘플 (간단한 1차 저역통과 필터) */
static void dsd_to_pcm_simple(const uint8_t *dsd, int dsd_bytes, int channels,
                               int16_t *pcm_out, int *pcm_samples) {
    /* DSD64: 64fs = 2822400 Hz → PCM 44100 Hz (64:1 데시메이션) */
    int decimation = 64;
    int total_bits = dsd_bytes * 8;
    int n_samples = total_bits / (decimation * channels);
    *pcm_samples = n_samples;

    float *acc = calloc(channels, sizeof(float));
    float alpha = 0.01f;  /* 간단한 RC 필터 */

    for (int s = 0; s < n_samples; s++) {
        for (int ch = 0; ch < channels; ch++) {
            float sum = 0;
            for (int d = 0; d < decimation; d++) {
                int bit_idx = (s * decimation * channels + d * channels + ch) * 1;
                /* 바이트 인터리브 가정: byte = bit_idx/8, bit = 7-(bit_idx%8) */
                int byte_idx = (s * decimation + d) * channels + ch;
                int bit_pos  = 7 - (byte_idx % 8);  /* MSB first */
                byte_idx /= 8;
                if (byte_idx < dsd_bytes) {
                    int bit = (dsd[byte_idx] >> bit_pos) & 1;
                    sum += bit ? 1.0f : -1.0f;
                }
            }
            acc[ch] = acc[ch] * (1-alpha) + (sum/decimation) * alpha;
            if (s < n_samples) {
                pcm_out[s * channels + ch] = (int16_t)(acc[ch] * 32767.0f);
            }
        }
    }
    free(acc);
}

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    ebunch D;
    memset(&D, 0, sizeof(D));
    if (DST_InitDecoder(&D, 2, 64) != 0) { fprintf(stderr, "init fail\n"); return 1; }

    int out_size = FRAME_SIZE_64 * 2;
    uint8_t *out = malloc(out_size);
    uint8_t *frame_buf = malloc(MAX_DST_SIZE);
    uint8_t sec[SECTOR_SIZE];

    int frame_started = 0, frame_size = 0, sector_count = 0;
    int dst_encoded = 0, frame_cnt = 0;

    /* 성공 프레임 수집 (F38, F49, F100 등) */
    int collect_frames = 20;
    uint8_t *collected = calloc(out_size * collect_frames, 1);
    int n_collected = 0;

    FILE *f = fopen(iso, "rb");
    if (!f) { fprintf(stderr, "ISO 열기 실패\n"); return 1; }

    for (int lsn = 647; lsn < 2000 && n_collected < collect_frames; lsn++) {
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
        struct { int sc; } fi[8]; int nf=0;
        if (dst_enc&&fi_count>0) for(int i=0;i<fi_count&&i<7;i++){
            fi[nf++].sc=(ptr[3]>>2)&0x1F; ptr+=4;
        }

        int fi_idx=0;
        for (int i=0;i<np;i++){
            if (pkts[i].dt==DATA_TYPE_AUDIO){
                if (pkts[i].fs){
                    if (frame_started&&frame_size>0&&dst_encoded){
                        memset(out,0,out_size);
                        int ret=DST_FramDSTDecode(frame_buf,out,frame_size,frame_cnt,&D);
                        if (ret==0){
                            double r0=run_avg(out,FRAME_SIZE_64);
                            double r1=run_avg(out+FRAME_SIZE_64,FRAME_SIZE_64);
                            if (r0>3.0&&n_collected<collect_frames){
                                memcpy(collected+n_collected*out_size,out,out_size);
                                printf("F%d r0=%.2f r1=%.2f → 수집[%d]\n",
                                       frame_cnt,r0,r1,n_collected);
                                n_collected++;
                            }
                        }
                        frame_cnt++;
                    }
                    frame_size=0; frame_started=1; dst_encoded=dst_enc;
                    if (fi_idx<nf){ sector_count=fi[fi_idx++].sc; } else sector_count=0;
                }
                if (frame_started&&frame_size+pkts[i].pl<=MAX_DST_SIZE){
                    memcpy(frame_buf+frame_size,ptr,pkts[i].pl);
                    frame_size+=pkts[i].pl;
                }
                if (dst_encoded&&sector_count>0) sector_count--;
            }
            ptr+=pkts[i].pl;
        }
    }
    fclose(f);
    DST_CloseDecoder(&D);

    printf("\n수집 프레임: %d\n", n_collected);
    if (n_collected == 0) return 1;

    /*
     * 수집된 프레임 분석:
     * out = [ch0_4704B][ch1_4704B]
     * 바이트 배열: ch0[0..4703] + ch1[0..4703]
     *
     * 이를 DSD 재생 가능한 포맷으로 변환:
     * A) 바이트 인터리브: ch0[0],ch1[0],ch0[1],ch1[1],...
     * B) 이미 인터리브?: ch0의 4바이트 블록, ch1의 4바이트 블록 교대
     *
     * → 간단한 비트 카운팅으로 PCM 변환 후 WAV 저장
     */

    /* 방법 1: ch0 순차, ch1 순차 (바이트 레벨 인터리브로 합치기) */
    int total_frames = n_collected;
    int frame_bytes  = FRAME_SIZE_64 * 2;
    int dsd_total    = total_frames * FRAME_SIZE_64 * 2;  /* 2ch */

    uint8_t *dsd_interleaved = malloc(dsd_total);
    for (int fr = 0; fr < total_frames; fr++) {
        uint8_t *src = collected + fr * out_size;
        uint8_t *ch0 = src;
        uint8_t *ch1 = src + FRAME_SIZE_64;
        for (int b = 0; b < FRAME_SIZE_64; b++) {
            dsd_interleaved[fr * FRAME_SIZE_64*2 + b*2]   = ch0[b];
            dsd_interleaved[fr * FRAME_SIZE_64*2 + b*2+1] = ch1[b];
        }
    }

    /* 간단한 DSD→PCM: 64샘플 평균 */
    int pcm_ch_samples = (dsd_total * 8) / (64 * 2);  /* 2ch */
    int16_t *pcm = calloc(pcm_ch_samples * 2, sizeof(int16_t));

    /* 비트 추출 (바이트 인터리브 가정: ch0,ch1,ch0,ch1...) */
    for (int s = 0; s < pcm_ch_samples; s++) {
        float sum0 = 0, sum1 = 0;
        for (int d = 0; d < 64; d++) {
            int bit_pair = s * 64 + d;
            int byte_idx = bit_pair * 2 / 8;     /* 2ch → 2배 */
            int bit_pos  = 7 - (bit_pair % 4);   /* 4비트씩 ch0,ch1 교대... */

            /* ch0: 짝수 비트 (byte 내 MSB부터) */
            int byte0 = (s * 64 + d) * 2 / 8;
            int bpos0 = 7 - ((s * 64 + d) % 4);
            int byte1 = byte0;
            int bpos1 = bpos0 - 4;
            /* 단순화: 바이트 단위 인터리브 */
            byte0 = (s * 64 + d) / 8 * 2;
            byte1 = byte0 + 1;
            bpos0 = 7 - ((s * 64 + d) % 8);
            bpos1 = bpos0;

            if (byte0 < dsd_total) sum0 += ((dsd_interleaved[byte0] >> bpos0) & 1) ? 1.f : -1.f;
            if (byte1 < dsd_total) sum1 += ((dsd_interleaved[byte1] >> bpos1) & 1) ? 1.f : -1.f;
        }
        pcm[s*2]   = (int16_t)((sum0/64.f) * 32767.f);
        pcm[s*2+1] = (int16_t)((sum1/64.f) * 32767.f);
    }

    /* WAV 파일 저장 */
    const char *wav_path = "/tmp/dst_test.wav";
    FILE *wf = fopen(wav_path, "wb");
    if (wf) {
        write_wav_header(wf, 44100, 2, pcm_ch_samples);
        fwrite(pcm, sizeof(int16_t), pcm_ch_samples * 2, wf);
        fclose(wf);
        printf("WAV 저장: %s (%d 샘플, %.1f초)\n",
               wav_path, pcm_ch_samples, (float)pcm_ch_samples/44100.f);
    }

    /* 분석 출력 */
    printf("\n=== 첫 수집 프레임 분석 ===\n");
    uint8_t *fr0 = collected;
    printf("ch0 첫16B:"); for(int i=0;i<16;i++) printf(" %02X", fr0[i]); printf("\n");
    printf("ch1 첫16B:"); for(int i=0;i<16;i++) printf(" %02X", fr0[FRAME_SIZE_64+i]); printf("\n");
    printf("ch0 run=%.2f ch1 run=%.2f\n",
           run_avg(fr0, FRAME_SIZE_64), run_avg(fr0+FRAME_SIZE_64, FRAME_SIZE_64));

    free(collected); free(dsd_interleaved); free(pcm);
    free(out); free(frame_buf);
    return 0;
}
