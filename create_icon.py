"""
니콘 친게 HiFi Music Player 아이콘 생성 스크립트.
- macOS에서 실행 시 .icns 자동 생성
- 그 외에는 PNG 저장
"""
from PIL import Image, ImageDraw
import os, sys, subprocess

def make_icon(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    # 배경 원
    draw.ellipse([0, 0, s-1, s-1], fill=(18, 14, 8, 255))
    # 골드 테두리
    lw = max(2, s // 40)
    draw.ellipse([lw//2, lw//2, s-1-lw//2, s-1-lw//2],
                 outline=(200, 169, 110, 220), width=lw)

    gold = (200, 169, 110, 255)
    cx, cy = s * 0.5, s * 0.5
    stem_w = max(2, s // 26)
    note_r = s * 0.095
    stem_h = s * 0.30
    beam_h = max(2, s // 32)
    lnx = cx - s * 0.14
    rnx = cx + s * 0.14
    note_y = cy + s * 0.10

    draw.rectangle([lnx - stem_w//2, note_y - stem_h, lnx + stem_w//2, note_y], fill=gold)
    draw.rectangle([rnx - stem_w//2, note_y - stem_h + s*0.06, rnx + stem_w//2, note_y + s*0.06], fill=gold)
    beam_y = note_y - stem_h
    draw.rectangle([lnx - stem_w//2, beam_y, rnx + stem_w//2, beam_y + beam_h], fill=gold)
    beam_y2 = beam_y + beam_h * 2.5
    draw.rectangle([lnx - stem_w//2, beam_y2, rnx + stem_w//2, beam_y2 + beam_h], fill=gold)
    draw.ellipse([lnx - note_r*1.3, note_y - note_r*0.75, lnx + note_r*0.7, note_y + note_r*0.75], fill=gold)
    draw.ellipse([rnx - note_r*1.3, note_y - note_r*0.75 + s*0.06, rnx + note_r*0.7, note_y + note_r*0.75 + s*0.06], fill=gold)

    wave_cx = s * 0.78
    wave_cy = s * 0.70
    for i in range(3):
        r1 = r2 = s * (0.06 + i * 0.055)
        alpha = 200 - i * 40
        draw.arc([wave_cx - r1, wave_cy - r2*1.2, wave_cx + r1, wave_cy + r2*1.2],
                 start=-60, end=60, fill=(200, 169, 110, alpha), width=max(1, stem_w-1))
    return img

HERE = os.path.dirname(os.path.abspath(__file__))

def create_icns():
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    iconset = os.path.join(HERE, 'AppIcon.iconset')
    os.makedirs(iconset, exist_ok=True)
    for sz in sizes:
        make_icon(sz).save(os.path.join(iconset, f'icon_{sz}x{sz}.png'))
        if sz <= 512:
            make_icon(sz*2).save(os.path.join(iconset, f'icon_{sz}x{sz}@2x.png'))
    result = subprocess.run(['iconutil', '-c', 'icns', iconset, '-o',
                             os.path.join(HERE, 'icon.icns')],
                            capture_output=True, text=True)
    import shutil; shutil.rmtree(iconset, ignore_errors=True)
    if result.returncode == 0:
        print("icon.icns 생성 완료")
    else:
        print("iconutil 오류:", result.stderr)

# 항상 PNG 생성
for sz in [256, 512, 1024]:
    make_icon(sz).save(os.path.join(HERE, f'icon_{sz}.png'))
    print(f"icon_{sz}.png 저장")

# macOS에서만 .icns 생성
if sys.platform == 'darwin':
    create_icns()

print("완료.")
