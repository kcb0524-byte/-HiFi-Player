#!/bin/bash
SACD="/tmp/sacd-ripper"
LIBDST="$SACD/libs/libdstdec"
DIR="$(cd "$(dirname "$0")"; pwd)"

if [ ! -d "$LIBDST" ]; then
    git clone --depth=1 https://github.com/sacd-ripper/sacd-ripper.git "$SACD"
fi

gcc -O2 -I"$LIBDST" \
    "$DIR/test_sector_count.c" \
    "$LIBDST/dst_ac.c" "$LIBDST/dst_data.c" "$LIBDST/dst_init.c" \
    "$LIBDST/dst_fram.c" "$LIBDST/unpack_dst.c" "$LIBDST/ccp_calc.c" \
    -o "$DIR/test_sector_count" && "$DIR/test_sector_count" 2>&1 | head -80
