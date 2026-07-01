#!/bin/bash
set -e
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
OUT="$(dirname "$0")"

echo "=== dst_fram.h의 핵심 함수 확인 ==="
grep -E "^(int|void|DST)" "$LIBDST/dst_fram.h" | head -20
echo ""
grep -E "^(int|void|DST)" "$LIBDST/unpack_dst.h" | head -20
echo ""
grep -E "^(int|void|DST)" "$LIBDST/dst_init.h" | head -20

echo ""
echo "=== 래퍼 C 파일 생성 ==="
cat > /tmp/dst_wrap.c << 'CWRAP'
/*
 * sacd-ripper libdstdec 래퍼
 * dst_fram.c의 실제 디코더를 직접 호출
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "dst_fram.h"
#include "dst_init.h"
#include "unpack_dst.h"

/* 외부에서 호출 가능한 심플 래퍼 */
typedef struct {
    FrameHdr   FrameHdr;
    CodedTable FiltCoef;
    CodedTable ProbCoef;
    BOOL       Calcfilter;
} DstWrapCtx;

void* dstwrap_create(void) {
    DstWrapCtx *ctx = calloc(1, sizeof(DstWrapCtx));
    return ctx;
}

void dstwrap_destroy(void *ctx) {
    free(ctx);
}

/* frame_data: DST 프레임, frame_len: 바이트, channels: 채널 수
   out: 출력 버퍼 (4704*channels 바이트)
   반환: 0=성공, 음수=오류 */
int dstwrap_decode(void *ctx_v, const uint8_t *frame_data, int frame_len,
                   int channels, uint8_t *out, int out_size)
{
    DstWrapCtx *ctx = (DstWrapCtx*)ctx_v;
    (void)out_size;
    
    /* unpack_dst.h의 함수로 프레임 파싱 */
    memset(out, 0, 4704 * channels);
    return DST_FramDSTDecode((uint8_t*)frame_data, out, channels, 64, &ctx->FrameHdr,
                              &ctx->FiltCoef, &ctx->ProbCoef);
}
CWRAP

echo "래퍼 파일 생성됨"

echo ""
echo "=== 실제 함수 시그니처 확인 ==="
grep -n "DST_Fram\|DSTDecode\|dst_decode\|Decode" "$LIBDST/dst_fram.h" "$LIBDST/unpack_dst.h" 2>/dev/null
