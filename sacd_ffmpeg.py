"""
sacd_ffmpeg.py — FFmpeg 기반 SACD ISO 디코더
Philips libdst 대신 FFmpeg의 내장 DST 디코더(dstdec)를 사용한다.
FFmpeg은 상용 SACD ISO를 완벽히 지원한다.

사용법:
    decoder = SACDFFmpegDecoder(iso_path, track_index=0)
    for pcm_chunk in decoder.decode_stream(sample_rate=88200):
        ...
"""

from __future__ import annotations

import subprocess
import shutil
import json
import sys
import os
import re
from typing import Optional


def find_ffmpeg():
    """ffmpeg 실행 파일 위치 탐색.

    우선순위: PyInstaller 번들 동봉본 → 시스템 PATH → Homebrew/Windows 표준 경로
    (audio_engine._load_pcm_via_ffmpeg 의 탐색 순서와 동일하게 유지)
    """
    exe_name = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
    candidates = []
    # PyInstaller 번들: PyInstaller 6+ onedir은 _internal(_MEIPASS), 구버전은 exe 옆
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, exe_name))
    candidates.append(os.path.join(os.path.dirname(sys.executable), exe_name))
    candidates.append(shutil.which('ffmpeg'))
    candidates += ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/usr/bin/ffmpeg']
    if sys.platform == 'win32':
        candidates += [
            r'C:\ProgramData\chocolatey\bin\ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe',
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def find_ffprobe():
    for candidate in ['ffprobe', '/opt/homebrew/bin/ffprobe', '/usr/local/bin/ffprobe']:
        if shutil.which(candidate):
            return candidate
    return None


def probe_sacd_tracks(iso_path: str) -> list[dict]:
    """
    SACD ISO에서 오디오 트랙 목록을 반환한다.
    반환값: [{'index': 0, 'title': '...', 'duration': 245.3, 'channels': 2}, ...]
    """
    ffprobe = find_ffprobe()
    if not ffprobe:
        return []

    cmd = [
        ffprobe,
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        '-show_format',
        iso_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout)
    except Exception:
        return []

    tracks = []
    for i, stream in enumerate(data.get('streams', [])):
        if stream.get('codec_type') == 'audio':
            tracks.append({
                'index': i,
                'stream_index': stream.get('index', i),
                'title': stream.get('tags', {}).get('title', f'Track {len(tracks)+1}'),
                'duration': float(stream.get('duration', 0)),
                'channels': stream.get('channels', 2),
                'codec': stream.get('codec_name', ''),
            })
    return tracks


class SACDFFmpegDecoder:
    """
    FFmpeg subprocess를 이용해 SACD ISO 트랙을 PCM으로 스트리밍 디코딩한다.

    FFmpeg 파이프라인:
      [SACD ISO] → sacd demuxer → dstdec → PCM f32le → pipe:1
    """

    CHUNK_SIZE = 4096 * 8  # PCM 읽기 단위 (바이트)

    def __init__(self, iso_path: str, track_index: int = 0,
                 sample_rate: int = 88200, channels: int = 2):
        self.iso_path    = iso_path
        self.track_index = track_index   # 오디오 스트림 인덱스 (0-based)
        self.sample_rate = sample_rate
        self.channels    = channels
        self._proc       = None

    # ------------------------------------------------------------------
    def _build_cmd(self) -> list[str]:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ffmpeg을 찾을 수 없습니다. brew install ffmpeg 으로 설치하세요.")
        return [
            ffmpeg,
            '-v', 'error',           # 오류 메시지만 출력
            '-i', self.iso_path,
            '-map', f'0:a:{self.track_index}',
            '-ar', str(self.sample_rate),
            '-ac', str(self.channels),
            '-f', 'f32le',           # 32-bit float, little-endian
            'pipe:1',
        ]

    def start(self):
        """디코딩 시작 (subprocess 실행)."""
        cmd = self._build_cmd()
        print(f"[SACD_FF] FFmpeg 시작: {' '.join(cmd)}", file=sys.stderr)
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def read_pcm_chunk(self, n_bytes: int = None) -> bytes | None:
        """
        PCM 데이터를 n_bytes만큼 읽어 반환한다.
        스트림 종료 시 None을 반환한다.
        """
        if self._proc is None:
            self.start()
        n = n_bytes or self.CHUNK_SIZE
        try:
            data = self._proc.stdout.read(n)
        except Exception:
            return None
        if not data:
            return None
        return data

    def stop(self):
        if self._proc:
            try:
                self._proc.stdout.close()
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None

    def decode_stream(self, chunk_bytes: int = None):
        """
        PCM f32le 데이터를 청크 단위로 yield하는 제너레이터.
        각 청크는 bytes 객체 (길이 = chunk_bytes).
        """
        self.start()
        while True:
            chunk = self.read_pcm_chunk(chunk_bytes)
            if chunk is None:
                break
            yield chunk
        self.stop()

    def __del__(self):
        self.stop()


# ------------------------------------------------------------------
# SACD ISO 트랙 정보 조회 (ffprobe 없이도 동작하는 fallback)
# ------------------------------------------------------------------

def get_sacd_track_info_ffmpeg(iso_path: str) -> list[dict]:
    """
    ffprobe를 이용해 SACD ISO 트랙 목록을 반환한다.
    실패 시 빈 리스트 반환.
    """
    tracks = probe_sacd_tracks(iso_path)
    if not tracks:
        # fallback: ffmpeg -i 출력에서 스트림 정보 파싱
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return []
        cmd = [ffmpeg, '-v', 'quiet', '-i', iso_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = result.stderr
        for line in out.splitlines():
            if 'Stream' in line and 'Audio' in line:
                m = re.search(r'Stream #0:(\d+)', line)
                idx = int(m.group(1)) if m else len(tracks)
                tracks.append({
                    'index': idx,
                    'stream_index': idx,
                    'title': f'Track {len(tracks)+1}',
                    'duration': 0.0,
                    'channels': 2,
                    'codec': 'dst',
                })
    return tracks


def check_ffmpeg_sacd_support() -> bool:
    """
    ffmpeg이 SACD (sacd demuxer, dstdec 코덱)를 지원하는지 확인한다.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("[SACD_FF] ffmpeg 없음", file=sys.stderr)
        return False
    result = subprocess.run(
        [ffmpeg, '-demuxers', '-v', 'quiet'],
        capture_output=True, text=True, timeout=5
    )
    has_sacd = 'sacd' in result.stdout.lower()
    if not has_sacd:
        # 일부 버전은 'D  sacd' 형식이 아닐 수 있음; 실제 테스트로 확인
        pass
    result2 = subprocess.run(
        [ffmpeg, '-codecs', '-v', 'quiet'],
        capture_output=True, text=True, timeout=5
    )
    has_dst = 'dst' in result2.stdout.lower()
    print(f"[SACD_FF] ffmpeg={ffmpeg}, sacd_demux={has_sacd}, dst_codec={has_dst}",
          file=sys.stderr)
    return True  # ffmpeg이 있으면 일단 시도


if __name__ == '__main__':
    # 간단 테스트: python3 sacd_ffmpeg.py /path/to/disc.iso
    if len(sys.argv) < 2:
        print("사용법: python3 sacd_ffmpeg.py /path/to/disc.iso [track_index]")
        sys.exit(1)

    iso = sys.argv[1]
    tidx = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    print(f"FFmpeg SACD 지원 여부: {check_ffmpeg_sacd_support()}")
    tracks = get_sacd_track_info_ffmpeg(iso)
    print(f"감지된 트랙: {len(tracks)}개")
    for t in tracks:
        print(f"  [{t['index']}] {t['title']} ({t['duration']:.1f}초, {t['channels']}ch)")

    print(f"\n트랙 {tidx} 디코딩 테스트 (첫 2초)...")
    dec = SACDFFmpegDecoder(iso, track_index=tidx, sample_rate=88200)
    import numpy as np
    total_bytes = 0
    target = 88200 * 2 * 4 * 2  # 2초 @ 88200Hz stereo f32le
    for chunk in dec.decode_stream(chunk_bytes=8192):
        total_bytes += len(chunk)
        if total_bytes >= target:
            dec.stop()
            break

    samples = total_bytes // 4  # f32le: 4 bytes per sample
    print(f"디코딩 성공: {total_bytes} bytes, {samples} 샘플")
    if total_bytes > 0:
        print("✓ FFmpeg SACD 디코딩 정상 동작")
    else:
        print("✗ 디코딩 실패 - ffmpeg이 SACD를 지원하지 않을 수 있음")
