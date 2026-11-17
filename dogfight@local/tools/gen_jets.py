#!/usr/bin/env python3
"""Procedural pixel-art sprites for the dogfight extension.

Top-down fighter jets (nose to the right; the extension rotates them),
an explosion, smoke puff and spark. Upscaled with nearest-neighbour.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

SCALE = int(os.environ.get('JET_SCALE', 3))

JW, JH = 22, 19          # jet canvas (odd height: symmetric)
FL = 4                   # afterburner room behind the tail
EW = 24                  # explosion canvas (square)

BODY = (150, 158, 168, 255)
BODY_L = (192, 200, 208, 255)
BODY_D = (110, 116, 126, 255)
GLASS = (40, 70, 110, 255)
GLASS_L = (120, 170, 220, 255)
OUTLINE = (14, 16, 20, 255)
FLAME = [(255, 240, 160, 255), (255, 170, 60, 255), (230, 80, 30, 255)]

TEAMS = {
    'red': ((214, 52, 48, 255), (150, 28, 28, 255)),
    'blue': ((52, 112, 220, 255), (28, 64, 150, 255)),
}


def outline(img):
    w, h = img.size
    px = img.load()
    out = img.copy()
    po = out.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] > 0:
                        po[x, y] = OUTLINE
                        break
    return out


def jet(team, flame):
    """Symmetric top-down fighter: the top half is drawn, then mirrored."""
    col, col_d = TEAMS[team]
    cy = JH // 2  # centre row (JH is odd)
    half = Image.new('RGBA', (JW, JH), (0, 0, 0, 0))
    d = ImageDraw.Draw(half)
    # main wing: swept delta, root at the fuselage, tip near the top edge
    d.polygon([(15, cy - 1), (9, 1), (7, 1), (8, cy - 1)], fill=BODY)
    d.line([(9, 1), (15, cy - 1)], fill=BODY_L)          # leading edge highlight
    d.line([(7, 1), (9, 1)], fill=col)                    # wing tip
    d.point([(9, 5)], fill=col)                           # roundel
    # tailplane
    d.polygon([(5, cy - 1), (3, cy - 4), (1, cy - 4), (1, cy - 1)], fill=BODY)
    d.point([(1, cy - 4), (2, cy - 4)], fill=col)
    # intake / fuselage side
    d.rectangle([1, cy - 1, 17, cy - 1], fill=BODY_D)
    img = half.copy()
    img.alpha_composite(half.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, JW, JH)), (0, 0))
    d = ImageDraw.Draw(img)
    # fuselage spine (3 px wide) and nose cone
    d.rectangle([1, cy - 1, 17, cy + 1], fill=BODY)
    d.line([(2, cy), (17, cy)], fill=BODY_L)
    d.polygon([(17, cy - 1), (21, cy), (17, cy + 1)], fill=BODY)
    d.point([(20, cy), (21, cy)], fill=col)               # nose tip
    d.line([(4, cy - 1), (4, cy + 1)], fill=col)          # fuselage band
    d.point([(5, cy)], fill=col_d)                        # tail fin (seen from above)
    d.line([(2, cy), (5, cy)], fill=col_d)
    # canopy
    d.line([(13, cy), (16, cy)], fill=GLASS)
    d.point([(15, cy)], fill=GLASS_L)
    img = outline(img)
    # afterburner behind the tail (not outlined): shift the jet right by FL px
    out = Image.new('RGBA', (JW + FL, JH), (0, 0, 0, 0))
    out.alpha_composite(img, (FL, 0))
    d = ImageDraw.Draw(out)
    ln = FL if flame else FL - 2
    for i in range(ln):
        x = FL - 1 - i
        d.point([(x, cy)], fill=FLAME[min(i, 2)])
        if i < ln - 2:
            d.point([(x, cy - 1), (x, cy + 1)], fill=FLAME[min(i + 1, 2)])
    return out


def explosion(i):
    img = Image.new('RGBA', (EW, EW), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = EW / 2
    r = [3, 6, 8.5, 10, 10.5, 10][i]
    if i <= 3:
        layers = [(r, (220, 60, 30, 255)), (r * 0.72, (255, 150, 40, 255)), (r * 0.4, (255, 240, 170, 255))]
    else:
        g = 120 + i * 15
        layers = [(r, (g, g, g + 6, 220 - (i - 4) * 70)), (r * 0.55, (g - 30, g - 30, g - 26, 200 - (i - 4) * 70))]
    for rr, col in layers:
        d.ellipse([c - rr, c - rr, c + rr, c + rr], fill=col)
    # ragged edge: punch a few holes
    for k in range(7):
        a = k * 2 * math.pi / 7 + i
        hx, hy = c + math.cos(a) * r, c + math.sin(a) * r
        d.ellipse([hx - 1.5, hy - 1.5, hx + 1.5, hy + 1.5], fill=(0, 0, 0, 0))
    if 1 <= i <= 3:  # flying debris
        for k in range(5):
            a = k * 2 * math.pi / 5 + 0.4
            rr = r + 1.5 + i
            d.point([(c + math.cos(a) * rr, c + math.sin(a) * rr)], fill=(60, 60, 60, 255))
    return img


def puff():
    img = Image.new('RGBA', (10, 10), (0, 0, 0, 0))
    px = img.load()
    for y in range(10):
        for x in range(10):
            dd = math.hypot(x - 4.5, y - 4.5) / 5
            if dd < 1:
                px[x, y] = (196, 196, 202, int(210 * (1 - dd ** 2)))
    return img


def spark():
    img = Image.new('RGBA', (7, 7), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(3, 0), (3, 6)], fill=(255, 220, 120, 255))
    d.line([(0, 3), (6, 3)], fill=(255, 220, 120, 255))
    d.point([(1, 1), (5, 5), (1, 5), (5, 1)], fill=(255, 160, 60, 255))
    d.point([(3, 3)], fill=(255, 255, 230, 255))
    return img


def save(img, path):
    img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST).save(path)


def main(dst):
    os.makedirs(dst, exist_ok=True)
    sheet_items = []
    for team in TEAMS:
        for f in (0, 1):
            im = jet(team, f)
            save(im, os.path.join(dst, f'jet_{team}_{f}.png'))
            sheet_items.append(im)
    for i in range(6):
        im = explosion(i)
        save(im, os.path.join(dst, f'expl_{i}.png'))
        sheet_items.append(im)
    save(puff(), os.path.join(dst, 'puff.png'))
    save(spark(), os.path.join(dst, 'spark.png'))
    sheet_items += [puff(), spark()]

    root = os.path.dirname(dst.rstrip('/')) or '.'
    # panel icon: red jet pointing up-right
    ic = jet('red', 1).rotate(35, resample=Image.NEAREST, expand=True)
    ic = ic.resize((ic.width * 2, ic.height * 2), Image.NEAREST)
    sq = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    sq.alpha_composite(ic, ((64 - ic.width) // 2, (64 - ic.height) // 2))
    sq.save(os.path.join(root, 'icon.png'))
    # preview sheet
    cell = 26 * 4
    sheet = Image.new('RGBA', (cell * 6, cell * 2), (90, 110, 130, 255))
    for k, im in enumerate(sheet_items):
        big = im.resize((im.width * 4, im.height * 4), Image.NEAREST)
        sheet.alpha_composite(big, ((k % 6) * cell + (cell - big.width) // 2, (k // 6) * cell + (cell - big.height) // 2))
    sheet.save(os.path.join(root, 'preview.png'))


if __name__ == '__main__':
    main(sys.argv[1])
