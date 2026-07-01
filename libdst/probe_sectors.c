/*
 * 섹터 구조 프로빙 — 실제 frame_start, dt값 확인
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define SECTOR_SIZE 2048

int main(void) {
    const char *iso = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso";

    FILE *f = fopen(iso, "rb");
    if (!f) { fprintf(stderr, "ISO 열기 실패\n"); return 1; }

    uint8_t sec[SECTOR_SIZE];
    int fs_count = 0;

    printf("LSN  | hdr  | fi | pi | 패킷정보\n");
    printf("-----|------|----|----|----------\n");

    for (int lsn = 640; lsn < 700; lsn++) {
        fseek(f, (long)lsn * SECTOR_SIZE, SEEK_SET);
        if (fread(sec, 1, SECTOR_SIZE, f) != SECTOR_SIZE) break;

        uint8_t hdr = sec[0];
        int tc  = (hdr >> 7) & 1;
        int fi  = (hdr >> 3) & 7;
        int pi  = hdr & 7;

        printf("%4d | 0x%02X | %2d | %2d | ", lsn, hdr, fi, pi);

        if (tc) { printf("[TC 타임코드]\n"); continue; }

        int ptr = 1;
        for (int i = 0; i < pi && ptr+2 <= SECTOR_SIZE; i++) {
            uint8_t b0 = sec[ptr], b1 = sec[ptr+1]; ptr += 2;
            int fs = (b0 >> 7) & 1;
            int dt = (b0 >> 3) & 7;
            int pl = (b0 & 7) << 8 | b1;
            printf("(fs=%d dt=%d len=%d) ", fs, dt, pl);
            if (fs && (dt==1||dt==2)) fs_count++;
        }
        printf("\n");
    }

    printf("\n총 frame_start(dt=1/2) 수: %d\n", fs_count);
    fclose(f);
    return 0;
}
