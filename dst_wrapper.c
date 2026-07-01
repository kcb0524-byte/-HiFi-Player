/*
 * DST 동기식 래퍼
 * 섹터(2048바이트)를 1개씩 dst_decoder에 투입하고
 * destroy 시 write_thread flush로 결과를 수집
 */
#include <stdlib.h>
#include <string.h>
#include "dst_decoder.h"

#define SECTOR_SIZE 2048

typedef struct {
    uint8_t *data;
    size_t   size;
    size_t   capacity;
} out_buf_t;

static void grow(out_buf_t *b, size_t need)
{
    if (b->size + need <= b->capacity) return;
    size_t cap = b->capacity ? b->capacity : (1024 * 1024);
    while (cap < b->size + need) cap *= 2;
    b->data = (uint8_t *)realloc(b->data, cap);
    b->capacity = cap;
}

static void on_decoded(uint8_t *frame_data, size_t frame_size, void *userdata)
{
    out_buf_t *b = (out_buf_t *)userdata;
    grow(b, frame_size);
    memcpy(b->data + b->size, frame_data, frame_size);
    b->size += frame_size;
}

static void on_error(int fc, int ec, const char *msg, void *ud)
{
    (void)fc; (void)ec; (void)msg; (void)ud;
}

/*
 * dst_decode_sectors:
 *   섹터(2048B)를 1개씩 decoder에 투입 → destroy 시 전체 flush
 *   반환: 디코딩된 DSD 버퍼 (호출자가 dst_free_buffer()로 해제)
 */
uint8_t *dst_decode_sectors(const uint8_t *in_data, size_t in_size,
                             int channel_count, size_t *out_size)
{
    out_buf_t buf = {NULL, 0, 0};
    *out_size = 0;

    size_t n_sectors = in_size / SECTOR_SIZE;
    if (n_sectors == 0) return NULL;

    dst_decoder_t *dec = dst_decoder_create(channel_count,
                                             on_decoded, on_error, &buf);
    if (!dec) return NULL;

    /* 섹터 1개씩 투입 (buffer_pool 슬롯 크기 초과 방지) */
    for (size_t i = 0; i < n_sectors; i++) {
        dst_decoder_decode(dec,
                           (uint8_t *)(in_data + i * SECTOR_SIZE),
                           SECTOR_SIZE);
    }

    /* destroy → write_thread flush → on_decoded 콜백 호출됨 */
    dst_decoder_destroy(dec);

    *out_size = buf.size;
    return buf.data;
}

void dst_free_buffer(uint8_t *buf)
{
    free(buf);
}
