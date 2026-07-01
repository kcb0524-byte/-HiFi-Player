/*
 * dst_cli — SACD ISO DST 섹터 파서 + 단일스레드 디코더
 * scarletbook_read.c의 실제 파싱 로직 기반
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_init.h"
#include "dst_fram.h"

#define SECTOR_SIZE      2048
#define MAX_PACKETS      7
#define MAX_FRAMES       7
#define DSD_FRAME_BYTES  4704   /* 588*64/8 per channel */
#define DATA_TYPE_AUDIO  2

int main(int argc, char *argv[])
{
    int channels = 2;
    if (argc > 1) channels = atoi(argv[1]);

    ebunch D;
    memset(&D, 0, sizeof(ebunch));
    if (DST_InitDecoder(&D, channels, 64) != 0) {
        fprintf(stderr, "DST_InitDecoder failed\n");
        return 1;
    }

    int dsd_out_bytes  = DSD_FRAME_BYTES * channels;
    uint8_t *sector    = (uint8_t *)malloc(SECTOR_SIZE);
    uint8_t *dst_frame = (uint8_t *)malloc(SECTOR_SIZE * 8);
    uint8_t *dsd_out   = (uint8_t *)malloc(dsd_out_bytes + 64);

    int frame_cnt       = 0;
    int dst_frame_size  = 0;
    int sectors_left    = 0;   /* 현재 DST 프레임에 남은 섹터 수 */

    size_t n;
    while ((n = fread(sector, 1, SECTOR_SIZE, stdin)) == SECTOR_SIZE) {
        uint8_t *ptr = sector;

        /* byte 0: audio_frame_header (scarletbook_read.c LE manual parse)
         * BE layout: packet_info_count:3 | frame_info_count:3 | reserved:1 | dst_encoded:1
         * LE read:   bits[7]=dst_encoded, bits[6]=reserved, bits[5:3]=frame_info_count, bits[2:0]=packet_info_count
         */
        uint8_t hdr = *ptr++;
        int dst_encoded       = (hdr >> 7) & 1;
        int frame_info_count  = (hdr >> 3) & 7;
        int packet_info_count = (hdr >> 0) & 7;

        /* packet_info 파싱 (각 2바이트, LE manual)
         * byte0: frame_start:1(bit7) | reserved:1 | data_type:3(bits5:3) | packet_length_hi:3(bits2:0)
         * byte1: packet_length_lo:8
         */
        int pkt_frame_start[MAX_PACKETS];
        int pkt_data_type[MAX_PACKETS];
        int pkt_length[MAX_PACKETS];
        int np = packet_info_count < MAX_PACKETS ? packet_info_count : MAX_PACKETS;
        for (int i = 0; i < np; i++) {
            uint8_t b0 = ptr[0], b1 = ptr[1];
            pkt_frame_start[i] = (b0 >> 7) & 1;
            pkt_data_type[i]   = (b0 >> 3) & 7;
            pkt_length[i]      = (b0 & 7) << 8 | b1;
            ptr += 2;
        }

        /* frame_info 파싱 (DST only, 각 4바이트)
         * byte3 LE: channel_bit_3:1 | channel_bit_2:1 | sector_count:5 | channel_bit_1:1
         */
        int nf = frame_info_count < MAX_FRAMES ? frame_info_count : MAX_FRAMES;
        int frame_sector_count[MAX_FRAMES];
        for (int i = 0; i < nf; i++) {
            if (dst_encoded) {
                frame_sector_count[i] = (ptr[3] >> 1) & 0x1f;
            }
            ptr += 4;
        }

        /* 오디오 패킷 처리 */
        int frame_idx = 0;
        for (int i = 0; i < np; i++) {
            int plen = pkt_length[i];
            if (pkt_data_type[i] != DATA_TYPE_AUDIO || plen == 0) {
                ptr += plen;
                continue;
            }

            if (dst_encoded) {
                if (pkt_frame_start[i]) {
                    /* 새 DST 프레임 시작 */
                    dst_frame_size = 0;
                    if (frame_idx < nf)
                        sectors_left = frame_sector_count[frame_idx++];
                    else
                        sectors_left = 1;
                }

                /* 데이터 누적 */
                memcpy(dst_frame + dst_frame_size, ptr, plen);
                dst_frame_size += plen;
                sectors_left--;

                if (sectors_left <= 0 && dst_frame_size > 0) {
                    memset(dsd_out, 0, dsd_out_bytes);
                    int ret = DST_FramDSTDecode(dst_frame, dsd_out,
                                                dst_frame_size, frame_cnt, &D);
                    if (ret == 0) {
                        fwrite(dsd_out, 1, dsd_out_bytes, stdout);
                    }
                    frame_cnt++;
                    dst_frame_size = 0;
                    sectors_left   = 0;
                }
            } else {
                fwrite(ptr, 1, plen, stdout);
            }
            ptr += plen;
        }
    }

    fflush(stdout);
    DST_CloseDecoder(&D);
    free(sector); free(dst_frame); free(dsd_out);
    return 0;
}
