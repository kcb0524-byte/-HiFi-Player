#!/bin/bash
# libdst_wrapper.dylib 빌드 스크립트
# 실행: bash build_libdst.sh
# 결과: hifi_player/ 디렉토리에 libdst_wrapper.dylib 생성

SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
DIR="$(cd "$(dirname "$0")"; pwd)"
OUT="$DIR/libdst_wrapper.dylib"

if [ ! -d "$LIBDST" ]; then
    echo "sacd-ripper 클론 중..."
    git clone --depth=1 https://github.com/sacd-ripper/sacd-ripper.git "$SACD"
fi

cat > /tmp/dst_wrapper.c << 'CWRAPPER'
#include <stdlib.h>
#include <string.h>
#include "dst_init.h"
#include "dst_fram.h"

typedef struct { ebunch D; int frame_cnt; } DSTHandle;

DSTHandle* dst_create(int nch, int fs_mult) {
    DSTHandle *h = (DSTHandle*)calloc(1, sizeof(DSTHandle));
    if (!h) return NULL;
    if (DST_InitDecoder(&h->D, nch, fs_mult) != 0) { free(h); return NULL; }
    return h;
}

int dst_decode_frame(DSTHandle *h,
                     const unsigned char *in_data, int in_size,
                     unsigned char *out_data, int out_size) {
    if (!h || !in_data || !out_data) return -1;
    memset(out_data, 0, out_size);
    int ret = DST_FramDSTDecode((unsigned char*)in_data, out_data,
                                 in_size, h->frame_cnt, &h->D);
    if (ret == 0) h->frame_cnt++;
    return ret;
}

void dst_reset(DSTHandle *h) { if (h) h->frame_cnt = 0; }

void dst_destroy(DSTHandle *h) {
    if (!h) return;
    DST_CloseDecoder(&h->D);
    free(h);
}
CWRAPPER

echo "=== 컴파일 중 ==="
gcc -O2 -shared -fPIC \
    -I"$LIBDST" \
    /tmp/dst_wrapper.c \
    "$LIBDST/dst_ac.c" \
    "$LIBDST/dst_data.c" \
    "$LIBDST/dst_init.c" \
    "$LIBDST/dst_fram.c" \
    "$LIBDST/unpack_dst.c" \
    "$LIBDST/ccp_calc.c" \
    -o "$OUT" 2>&1

if [ $? -eq 0 ]; then
    echo "✓ 빌드 성공: $OUT"
    ls -la "$OUT"
else
    echo "✗ 빌드 실패"
    exit 1
fi
