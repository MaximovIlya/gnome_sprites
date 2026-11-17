#!/usr/bin/env python3
"""Procedural pixel-art airship sprite generator (companion to fox-pet).

Draws a side-view airship (facing right) on a small canvas, outlines it,
upscales with nearest-neighbour and writes <anim>_<i>_<r|l>.png frames.
Same palette and outline style as the fox.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

W, H = 64, 34
TOP = 7                 # headroom above the ship for steam puffs
HT = H + TOP
SCALE = int(os.environ.get('AIRSHIP_SCALE', 3))

BODY = (236, 236, 238, 255)    # envelope
BODY_D = (176, 176, 184, 255)  # shading / seams
BODY_L = (250, 250, 252, 255)  # highlight
GONDOLA = (214, 214, 218, 255)
ACCENT = (40, 40, 44, 255)     # fins, stripe
DARK = (16, 16, 18, 255)
OUTLINE = (8, 8, 10, 255)
GLASS = (120, 150, 190, 255)
LIGHT_ON = (230, 70, 70, 255)
LIGHT_OFF = (110, 40, 40, 255)
STEAM = (230, 236, 255, 255)   # not outlined, like the fox's Zs

CX, CY, RX, RY = 33, 14, 23, 8.5   # envelope


def new():
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def ell(d, cx, cy, rx, ry, col):
    d.ellipse([round(cx - rx), round(cy - ry), round(cx + rx), round(cy + ry)], fill=col)


def inside(x, y):
    return ((x - CX) / RX) ** 2 + ((y - CY) / RY) ** 2 <= 1.0


def envelope(img):
    d = ImageDraw.Draw(img)
    # fins at the tail (left), drawn first so the envelope overlaps their roots
    d.polygon([(14, 10), (6, 3), (3, 3), (6, 12)], fill=ACCENT)        # top fin
    d.polygon([(14, 18), (6, 25), (3, 25), (6, 16)], fill=ACCENT)      # bottom fin
    d.polygon([(13, 13), (2, 12), (2, 16), (13, 15)], fill=BODY_D)     # side fin
    ell(d, CX, CY, RX, RY, BODY)
    px = img.load()
    for y in range(H):
        for x in range(W):
            if not inside(x + 0.5, y + 0.5):
                continue
            ny = (y + 0.5 - CY) / RY
            if ny > 0.45:
                px[x, y] = BODY_D                      # belly shading
            elif ny < -0.55 and 20 < x < 46:
                px[x, y] = BODY_L                      # top highlight
            if x in (19, 27, 35, 43) and abs(ny) < 0.85:
                px[x, y] = BODY_D                      # panel seams
    # accent stripe along the side
    d.line([(15, CY + 1), (51, CY + 1)], fill=ACCENT)
    # nose cap
    ell(d, CX + RX - 1, CY, 2, 2.5, ACCENT)


def gondola(d):
    gy = CY + RY + 3
    # rigging
    for x0, x1 in ((26, 28), (40, 38)):
        d.line([(x0, CY + RY - 1), (x1, gy)], fill=DARK)
    d.rounded_rectangle([26, gy, 41, gy + 5], radius=2, fill=GONDOLA)
    d.line([(27, gy + 5), (40, gy + 5)], fill=BODY_D)
    for wx in (29, 33, 37):
        d.rectangle([wx, gy + 1, wx + 1, gy + 2], fill=GLASS)
    return gy


def propeller(d, gy, phase):
    """Spinning prop at the back of the gondola; phase 0..3."""
    px, py = 23, gy + 2
    d.line([(px + 1, py), (26, py)], fill=DARK)       # shaft
    L = (4, 3, 1, 3)[phase]
    if phase in (1, 3):                               # blurred disc behind the blade
        d.line([(px, py - 4), (px, py + 4)], fill=BODY_D)
    d.line([(px, py - L), (px, py + L)], fill=DARK, width=1)
    d.point([(px, py)], fill=ACCENT)


def steam(d, k):
    """Puffs rising from the top of the envelope (canvas with headroom); k = 1..3."""
    base = [(39, 8, 1.6), (43, 4.5, 2.2), (48, 2.5, 2.6)]
    for i in range(k):
        x, y, r = base[i]
        ell(d, x, y, r + 0.7, r, STEAM)


def outline(img):
    px = img.load()
    out = img.copy()
    po = out.load()
    for y in range(H):
        for x in range(W):
            if px[x, y][3] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and px[nx, ny][3] > 0:
                        po[x, y] = OUTLINE
                        break
    return out


def pose(phase=0, light=True, puff=0):
    img = new()
    envelope(img)
    d = ImageDraw.Draw(img)
    gy = gondola(d)
    propeller(d, gy, phase)
    # tail light on the top fin
    d.point([(4, 4)], fill=LIGHT_ON if light else LIGHT_OFF)
    img = outline(img)
    tall = Image.new('RGBA', (W, HT), (0, 0, 0, 0))
    tall.alpha_composite(img, (0, TOP))
    if puff:
        steam(ImageDraw.Draw(tall), puff)
    return tall


def squash(img, f):
    """Fake 3D turn: squeeze horizontally around the centre."""
    w = max(2, round(W * f))
    s = img.resize((w, HT), Image.NEAREST)
    out = Image.new('RGBA', (W, HT), (0, 0, 0, 0))
    out.alpha_composite(s, ((W - w) // 2, 0))
    return out


def frames():
    out = {}
    out['fly'] = [pose(phase=i, light=(i < 2)) for i in range(4)]
    out['turn'] = [squash(pose(phase=0), f) for f in (0.66, 0.3)]
    out['puff'] = [pose(phase=i % 4, puff=k) for i, k in enumerate((1, 2, 3, 3, 2))]
    return out


def main(dst):
    os.makedirs(dst, exist_ok=True)
    allf = frames()
    for name, fl in allf.items():
        for i, f in enumerate(fl):
            big = f.resize((W * SCALE, HT * SCALE), Image.NEAREST)
            big.save(os.path.join(dst, f'{name}_{i}_r.png'))
            big.transpose(Image.FLIP_LEFT_RIGHT).save(os.path.join(dst, f'{name}_{i}_l.png'))
    # panel icon: one frame cropped to a square
    icon = allf['fly'][0].crop((0, TOP, W, TOP + W // 2 + 2)).resize((64, 36), Image.NEAREST)
    sq = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    sq.alpha_composite(icon, (0, 14))
    root = os.path.dirname(dst.rstrip('/')) or '.'
    sq.save(os.path.join(root, 'icon.png'))
    # preview sheet
    rows = list(allf.items())
    cols = max(len(v) for _, v in rows)
    sheet = Image.new('RGBA', (cols * W * 4, len(rows) * HT * 4), (90, 110, 130, 255))
    for r, (_, fl) in enumerate(rows):
        for c, f in enumerate(fl):
            sheet.alpha_composite(f.resize((W * 4, HT * 4), Image.NEAREST), (c * W * 4, r * HT * 4))
    sheet.save(os.path.join(root, 'preview.png'))


if __name__ == '__main__':
    main(sys.argv[1])
