"""
DST (Direct Stream Transfer) 디코더
Philips DST 스펙 기반 순수 Python 구현

Jeff Beck ISO 구조 (실측):
  - Area TOC: DST encoded 플래그 확인됨 (0x28)
  - 오디오 섹터: hdr=0x45(pi=5,fi=0) 또는 0x21(pi=1,fi=4)
  - dt=2 패킷이 DST 압축 데이터 (엔트로피 7.09 bits/byte)
  - 패킷이 섹터 경계를 넘어 연속됨
  - frame_start=1 패킷이 DST 프레임 시작
"""

import struct
import numpy as np

SECTOR_SIZE = 2048

# ── DST 확률 테이블 (Philips IEC 62074-1 스펙) ──────────────
# P[i] = P(다음비트=1 | 예측기 출력=i)
# 128 = 0.5 (무정보), 255 = ~1.0, 1 = ~0
DST_P_TABLE = [
    128, 123, 118, 114, 109, 105, 101,  97,  93,  90,  86,  83,  80,  77,  74,  71,
     68,  65,  63,  60,  58,  56,  54,  52,  50,  48,  46,  44,  42,  41,  39,  38,
     36,  35,  33,  32,  31,  30,  29,  27,  26,  25,  24,  23,  22,  22,  21,  20,
     19,  18,  18,  17,  16,  16,  15,  14,  14,  13,  13,  12,  12,  11,  11,  10,
     10,   9,   9,   9,   8,   8,   8,   7,   7,   7,   6,   6,   6,   6,   5,   5,
      5,   5,   4,   4,   4,   4,   4,   4,   3,   3,   3,   3,   3,   3,   3,   2,
      2,   2,   2,   2,   2,   2,   2,   2,   1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,
]


class BitReader:
    def __init__(self, data: bytes):
        self.data  = data
        self.pos   = 0
        self.total = len(data) * 8

    def read_bit(self) -> int:
        if self.pos >= self.total:
            return 0
        b = self.data[self.pos >> 3]
        bit = (b >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return bit

    def read_bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.read_bit()
        return v

    def bits_left(self) -> int:
        return self.total - self.pos


class ArithDecoder:
    """DST 산술 디코더 (8비트 정밀도)"""
    def __init__(self, reader: BitReader):
        self.r = reader
        self.C = self.r.read_bits(8)  # 코드 레지스터
        self.A = 256                   # 구간 크기

    def decode(self, p: int) -> int:
        """p = P(1)×256 으로 비트 디코딩"""
        self.A -= 1
        t = (self.A * p + 128) >> 8
        if self.C > t:
            self.C -= t + 1
            self.A -= t
            bit = 1
        else:
            self.A = t + 1
            bit = 0
        # 재정규화
        while self.A < 128:
            self.A <<= 1
            self.C = ((self.C << 1) & 0xFF) | self.r.read_bit()
        return bit


class DSTChannelDecoder:
    """단일 채널 DST 디코더 (FIR 예측 + 산술 코딩)"""

    FILTER_ORDER = 16  # FIR 예측 필터 차수

    def __init__(self):
        self.history = [0] * self.FILTER_ORDER  # 비트 히스토리 (MSB first)
        self.coefs   = [0] * self.FILTER_ORDER  # FIR 계수
        self.ptab_i  = 0                         # 확률 테이블 오프셋

    def decode_frame(self, ac: ArithDecoder, n_bytes: int) -> bytes:
        """n_bytes 바이트 분량의 DSD 비트 디코딩"""
        result = bytearray(n_bytes)
        history = list(self.history)
        coefs   = list(self.coefs)

        for bi in range(n_bytes):
            byte_val = 0
            for _ in range(8):
                # FIR 예측
                pred = sum(c * h for c, h in zip(coefs, history))

                # 예측값 → 확률 인덱스
                idx = min(abs(pred) >> 3, len(DST_P_TABLE) - 1)
                p = DST_P_TABLE[idx]
                if pred < 0:
                    p = 256 - p

                # 산술 디코딩
                bit = ac.decode(p)
                byte_val = (byte_val << 1) | bit

                # FIR 계수 적응 업데이트 (LMS)
                error = bit - (1 if pred >= 0 else 0)
                if error != 0:
                    for i in range(self.FILTER_ORDER):
                        if history[i]:
                            coefs[i] += error
                        # 계수 클리핑
                        coefs[i] = max(-128, min(127, coefs[i]))

                # 히스토리 업데이트
                history = [bit] + history[:-1]

            result[bi] = byte_val

        self.history = history
        self.coefs   = coefs
        return bytes(result)


class DSTDecoder:
    """
    SACD ISO DST 프레임 디코더

    Jeff Beck ISO 기준:
    - 2채널
    - frame_size = 4704 bytes/ch (DSD64 1프레임)
    - DST 프레임 = frame_start=1 패킷부터 다음 frame_start=1 전까지
    """

    FRAME_SIZE = 4704  # bytes per channel per DST frame (DSD64)

    def __init__(self, channels: int = 2):
        self.channels = channels
        self.ch_dec   = [DSTChannelDecoder() for _ in range(channels)]

    def decode_frame(self, frame_data: bytes) -> bytes:
        """
        DST 프레임 데이터 → 인터리브 DSD bytes
        반환: ch0_b0, ch1_b0, ch0_b1, ch1_b1, ... (총 FRAME_SIZE×channels bytes)

        DST 스펙: 단일 산술코더, 채널 비트 인터리브
        순서: ch0_byte0 → ch1_byte0 → ch0_byte1 → ch1_byte1 → ...
        각 채널은 독립 FIR predictor 상태를 유지
        """
        if not frame_data:
            return bytes(self.FRAME_SIZE * self.channels)

        reader = BitReader(frame_data)
        ac = ArithDecoder(reader)

        ch_histories = [list(dec.history) for dec in self.ch_dec]
        ch_coefs     = [list(dec.coefs)   for dec in self.ch_dec]
        ch_bytes     = [bytearray(self.FRAME_SIZE) for _ in range(self.channels)]

        for bi in range(self.FRAME_SIZE):
            for ch in range(self.channels):
                byte_val = 0
                history  = ch_histories[ch]
                coefs    = ch_coefs[ch]
                for _ in range(8):
                    pred = sum(c * h for c, h in zip(coefs, history))
                    idx  = min(abs(pred) >> 3, len(DST_P_TABLE) - 1)
                    p    = DST_P_TABLE[idx]
                    if pred < 0:
                        p = 256 - p
                    bit = ac.decode(p)
                    byte_val = (byte_val << 1) | bit
                    err = bit - (1 if pred >= 0 else 0)
                    if err != 0:
                        for i in range(len(coefs)):
                            if history[i]:
                                coefs[i] = max(-128, min(127, coefs[i] + err))
                    history = [bit] + history[:-1]
                ch_bytes[ch][bi] = byte_val
                ch_histories[ch] = history
                ch_coefs[ch]     = coefs

        for ch in range(self.channels):
            self.ch_dec[ch].history = ch_histories[ch]
            self.ch_dec[ch].coefs   = ch_coefs[ch]

        result = bytearray(self.FRAME_SIZE * self.channels)
        for i in range(self.FRAME_SIZE):
            for ch in range(self.channels):
                result[i * self.channels + ch] = ch_bytes[ch][i]
        return bytes(result)

    def decode_frame_separate(self, frame_data: bytes):
        """채널별 별도 반환 (분석용)"""
        dsd = self.decode_frame(frame_data)
        return [bytes(dsd[ch::self.channels]) for ch in range(self.channels)]


def extract_dst_frames(iso_path: str, start_lsn: int, end_lsn: int,
                       channels: int = 2):
    """
    ISO에서 DST 프레임 스트림 추출 (크로스섹터 지원)

    반환: (frame_data_list, frame_count)
    각 frame_data = frame_start=1부터 다음 frame_start=1 전까지의 dt=2 패킷 데이터
    """
    frames = []
    frame_buf = bytearray()
    in_frame  = False

    # 크로스섹터 패킷 처리를 위한 carry 버퍼
    carry_data  = bytearray()   # 이전 섹터에서 잘린 패킷 데이터
    carry_pkts  = []            # 아직 처리 안된 패킷 메타 (fs, dt, remaining_len)

    with open(iso_path, 'rb') as f:
        for lsn in range(start_lsn, end_lsn):
            f.seek(lsn * SECTOR_SIZE)
            sec = f.read(SECTOR_SIZE)
            if not sec or len(sec) < 1:
                continue

            hdr = sec[0]
            if (hdr >> 7) & 1:
                continue  # DST 타임코드 섹터 건너뜀

            fi = (hdr >> 3) & 7
            pi = hdr & 7

            # 이 섹터의 패킷 메타 파싱
            ptr = 1
            new_pkts = []
            for _ in range(pi):
                if ptr + 2 > len(sec):
                    break
                b0 = sec[ptr]; b1 = sec[ptr+1]; ptr += 2
                fs = (b0 >> 7) & 1
                dt = (b0 >> 3) & 7
                pl = (b0 & 7) << 8 | b1
                new_pkts.append((fs, dt, pl))
            ptr += fi * 4

            # 데이터 페이로드 (헤더 제외)
            sec_payload = sec[ptr:]

            # carry 데이터와 합침
            stream = carry_data + sec_payload
            carry_data = bytearray()

            # carry 패킷 먼저 처리
            all_pkts = carry_pkts + new_pkts
            carry_pkts = []

            sptr = 0
            for fs, dt, pl in all_pkts:
                if sptr + pl <= len(stream):
                    pkt_data = stream[sptr:sptr+pl]
                    sptr += pl
                else:
                    # 섹터 경계를 넘음 → 남은 부분을 carry로
                    have = len(stream) - sptr
                    if dt in (1, 2) and have > 0:
                        if in_frame:
                            frame_buf.extend(stream[sptr:])
                    carry_data = bytearray()  # 다음 섹터가 나머지를 채움
                    remaining = pl - have
                    carry_pkts = [(fs, dt, remaining)]
                    break

                if dt not in (1, 2):
                    continue

                if fs == 1:
                    # 새 프레임 시작
                    if in_frame and frame_buf:
                        frames.append(bytes(frame_buf))
                    frame_buf = bytearray(pkt_data)
                    in_frame  = True
                elif in_frame:
                    frame_buf.extend(pkt_data)

    # 마지막 프레임
    if in_frame and frame_buf:
        frames.append(bytes(frame_buf))

    return frames


def run_avg(data: bytes, n: int = 512) -> float:
    """비트 런 길이 평균 (높을수록 저주파 = 음악)"""
    runs, cur, l = [], None, 0
    for b in data[:n]:
        for i in range(7, -1, -1):
            bit = (b >> i) & 1
            if cur is None: cur = bit; l = 1
            elif bit == cur: l += 1
            else: runs.append(l); cur = bit; l = 1
    if l: runs.append(l)
    return sum(runs) / len(runs) if runs else 0


# ── 테스트 ────────────────────────────────────────────────────
if __name__ == '__main__':
    ISO = "/Volumes/ HD/임시 음악/Jeff Beck - Blow By Blow (1975) [SACD] (2016 AP Remaster ISO)/Analogue Productions - Blow By Blow.iso"

    print("=== DST 프레임 추출 테스트 ===")

    # 트랙1 시작 LSN = 645 (SACDTRL1에서 확인된 값)
    # 실제 오디오 시작은 648부터
    frames = extract_dst_frames(ISO, 648, 800, channels=2)
    print(f"추출된 DST 프레임 수: {len(frames)}")

    if not frames:
        print("ERROR: 프레임 없음 — 섹터 파싱 문제")
    else:
        print(f"프레임 크기들: {[len(f) for f in frames[:10]]}")
        print(f"첫 프레임 첫 32B: {' '.join(f'{b:02X}' for b in frames[0][:32])}")

        print()
        print("=== DST 디코딩 테스트 (프레임 1~5, 채널별) ===")
        decoder = DSTDecoder(channels=2)
        # 프레임 0은 워밍업용으로 먼저 처리
        decoder.decode_frame(frames[0])

        all_dsd = bytearray()
        for i, frame in enumerate(frames[1:6], 1):
            print(f"프레임 {i}: {len(frame)}B 입력...")
            ch_data = decoder.decode_frame_separate(frame)
            for ch, data in enumerate(ch_data):
                rl   = run_avg(data)
                ones = sum(bin(b).count('1') for b in data[:256]) / (256*8)
                print(f"  ch{ch}: run={rl:.2f}, 1비율={ones:.3f}, 첫8B={' '.join(f'{b:02X}' for b in data[:8])}")
            # 인터리브 합치기
            interleaved = bytearray(len(ch_data[0]) * 2)
            for j in range(len(ch_data[0])):
                interleaved[j*2]   = ch_data[0][j]
                interleaved[j*2+1] = ch_data[1][j]
            all_dsd.extend(interleaved)

        print()
        print(f"총 DSD (인터리브): {len(all_dsd)}B")
        # ch0만 따로 런 확인
        ch0 = bytes(all_dsd[0::2])
        ch1 = bytes(all_dsd[1::2])
        print(f"ch0 런 길이: {run_avg(ch0):.2f}")
        print(f"ch1 런 길이: {run_avg(ch1):.2f}")
        print(f"전체 런 길이: {run_avg(bytes(all_dsd)):.2f} (>3.0이면 음악 신호)")
        print(f"첫 32B: {' '.join(f'{b:02X}' for b in all_dsd[:32])}")
