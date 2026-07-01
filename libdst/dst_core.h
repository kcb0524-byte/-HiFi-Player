#pragma once
#include <stdint.h>

#define DST_MAX_CHANNELS 6

typedef struct DSTContext DSTContext;

DSTContext *dst_create(int channels);
void        dst_destroy(DSTContext *ctx);
void        dst_reset(DSTContext *ctx);

/* frame_data: DST 압축 프레임, out: FRAME_SIZE*channels bytes */
int  dst_decode_frame(DSTContext *ctx,
                      const uint8_t *frame_data, int frame_len,
                      uint8_t *out);

int  dst_frame_size(void);  /* = 4704 */
