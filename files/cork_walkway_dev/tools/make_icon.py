"""앱 아이콘 생성(개발용): assets/app.ico(여러 크기) + assets/app.png(256px).

실행: .venv\\Scripts\\python.exe tools\\make_icon.py
디자인: 짙은 남색 하늘 + 초록 언덕 + 원근으로 멀어지는 굽은 코르크 길(알갱이 질감) + 'AI 시뮬레이션' 반짝임.
1024px로 그린 뒤 줄여서 작은 크기(16px)에서도 길 모양이 보이게 한다. 외부 이미지·글꼴을 쓰지 않는다.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 1024
ROOT = Path(__file__).resolve().parent.parent
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _vgrad(top, bottom, h, w):
    t = np.linspace(0, 1, h)[:, None, None]
    return (np.array(top) * (1 - t) + np.array(bottom) * t).repeat(w, 1)


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return m


def _path_polygon():
    """원근 길: 아래는 넓고 위(지평선)로 갈수록 좁아지며 S자로 굽는다."""
    left, right = [], []
    n = 80
    for i in range(n + 1):
        t = i / n                                   # 0 = 앞(아래), 1 = 먼 곳
        y = S * (1.02 - 0.58 * t ** 0.9)
        x = S * (0.50 + 0.13 * math.sin(math.pi * (t * 1.25 + 0.05)) - 0.06 * t)
        half = S * (0.30 * (1 - t) ** 1.25 + 0.012)
        left.append((x - half, y))
        right.append((x + half, y))
    return left + right[::-1]


def draw() -> Image.Image:
    rng = np.random.default_rng(3)
    horizon = int(S * 0.44)
    sky = _vgrad((15, 40, 82), (3, 105, 161), horizon, S)                    # 남색 → CTA 파랑
    ground = _vgrad((74, 168, 92), (21, 101, 52), S - horizon, S)             # 밝은 → 짙은 초록
    base = Image.fromarray(np.concatenate([sky, ground]).astype(np.uint8), "RGB")

    # 먼 언덕(부드러운 곡선)
    hill = Image.new("L", (S, S), 0)
    pts = [(x, horizon - S * 0.035 * (1 + math.sin(x / S * 2 * math.pi * 1.1 + 0.6))) for x in range(0, S + 1, 8)]
    ImageDraw.Draw(hill).polygon(pts + [(S, horizon + 4), (0, horizon + 4)], fill=255)
    base.paste((52, 140, 78), (0, 0), hill.filter(ImageFilter.GaussianBlur(2)))

    # 코르크 길: 그라데이션 + 알갱이
    poly = _path_polygon()
    pmask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(pmask).polygon(poly, fill=255)
    cork = _vgrad((214, 182, 146), (196, 150, 108), S, S)
    grain = rng.normal(0, 16, (S, S, 1))
    chips = (rng.random((S, S, 1)) > 0.985) * rng.choice([-45, 40], (S, S, 1))
    cork = np.clip(cork + grain + chips, 0, 255).astype(np.uint8)
    cork_img = Image.fromarray(cork, "RGB").filter(ImageFilter.GaussianBlur(1.2))
    shadow = pmask.filter(ImageFilter.GaussianBlur(14))
    base.paste((12, 60, 30), (0, 10), shadow.point(lambda v: v * 0.45))        # 길 아래 은은한 그림자
    base.paste(cork_img, (0, 0), pmask)
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).line(poly + [poly[0]], fill=255, width=10)
    base.paste((248, 236, 220), (0, 0), Image.composite(edge, Image.new("L", (S, S), 0), pmask).point(lambda v: v // 3))

    # AI 반짝임(4각 별 2개)
    d = ImageDraw.Draw(base)
    for cx, cy, r in ((0.76, 0.20, 0.115), (0.89, 0.34, 0.05)):
        cx, cy, r = cx * S, cy * S, r * S
        k = r * 0.22
        d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
                   (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)], fill=(255, 255, 255))

    # 둥근 사각형 + 얇은 안쪽 하이라이트
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    radius = int(S * 0.225)
    out.paste(base, (0, 0), _rounded_mask(S, radius))
    hl = Image.new("L", (S, S), 0)
    ImageDraw.Draw(hl).rounded_rectangle((6, 6, S - 7, S - 7), radius - 6, outline=70, width=6)
    out.paste((255, 255, 255), (0, 0), hl)
    return out


def main() -> None:
    big = draw()
    assets = ROOT / "assets"
    big.resize((256, 256), Image.LANCZOS).save(assets / "app.png")
    imgs = [big.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    imgs[-1].save(assets / "app.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=imgs[:-1])
    big.resize((512, 512), Image.LANCZOS).save(ROOT / "tools" / "icon_preview.png")
    print("saved:", assets / "app.ico", assets / "app.png")


if __name__ == "__main__":
    main()
