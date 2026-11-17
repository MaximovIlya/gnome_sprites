#!/usr/bin/env python3
"""Procedural pixel-art cat sprite generator (companion to fox-pet).

Ginger tabby with white paws, chest and muzzle. Side view facing right,
same canvas, animation names and frame counts as the fox so the extension
logic can be shared. Upscales with nearest-neighbour and writes
<anim>_<i>_<r|l>.png frames.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

W, H = 44, 30
GROUND = 28
SCALE = int(os.environ.get('CAT_SCALE', 3))

GINGER = (234, 142, 58, 255)     # body
GINGER_D = (192, 104, 38, 255)   # far legs / shading
GINGER_L = (247, 172, 94, 255)   # highlights
STRIPE = (172, 82, 26, 255)      # tabby stripes
WHITE = (252, 248, 242, 255)     # paws, chest, muzzle
WHITE_D = (222, 214, 204, 255)   # far paws
PINK = (240, 146, 156, 255)      # nose, inner ears, tongue
EYE = (120, 196, 84, 255)
PUPIL = (20, 14, 8, 255)
OUTLINE = (36, 20, 10, 255)
ZCOL = (230, 236, 255, 255)


def new():
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def ell(d, cx, cy, rx, ry, col):
    d.ellipse([round(cx - rx), round(cy - ry), round(cx + rx), round(cy + ry)], fill=col)


def leg(d, x0, y0, x1, y1, col=GINGER, sock=WHITE, w=2):
    """Leg from hip/shoulder (x0,y0) to foot (x1,y1); lower part is a white sock."""
    mx = x0 + (x1 - x0) * 0.6
    my = y0 + (y1 - y0) * 0.6
    d.line([(x0, y0), (mx, my)], fill=col, width=w)
    d.line([(mx, my), (x1, y1)], fill=sock, width=w)
    d.point([(x1 + 1, y1)], fill=sock)  # paw toe


def tail(d, bx, by, angle, length=12, curl=0.6):
    """Thin striped tail from (bx,by) pointing back (left); curl > 0 bends the tip up."""
    n = 14
    for i in range(n + 1):
        t = i / n
        a = math.radians(angle) + curl * t * t
        x = bx - math.cos(a) * length * t
        y = by - math.sin(a) * length * t
        col = STRIPE if i % 4 == 3 or t > 0.93 else GINGER
        ell(d, x, y, 1.1, 1.1, col)


def head(d, hx, hy, look=0, blink=False, down=0, ear_flick=0):
    """Round cat head centred at (hx,hy), face to the right."""
    hy += down
    # ears: pointy triangles with pink inside
    d.polygon([(hx - 3, hy - 2), (hx - 2 - ear_flick, hy - 7), (hx + 0, hy - 3)], fill=GINGER)
    d.polygon([(hx + 1, hy - 3), (hx + 3, hy - 7), (hx + 4, hy - 2)], fill=GINGER)
    d.point([(hx - 2 - ear_flick, hy - 5), (hx + 3, hy - 5)], fill=PINK)
    # skull
    ell(d, hx, hy, 4.2, 3.6, GINGER)
    # short muzzle
    d.polygon([(hx + 2, hy - 1), (hx + 5 + look, hy), (hx + 5 + look, hy + 2), (hx + 2, hy + 3)], fill=GINGER)
    # white muzzle / chin
    d.polygon([(hx + 1, hy + 1), (hx + 5 + look, hy + 1), (hx + 4 + look, hy + 3), (hx, hy + 3)], fill=WHITE)
    # forehead stripes
    d.point([(hx - 1, hy - 3), (hx - 2, hy - 2), (hx + 1, hy - 3)], fill=STRIPE)
    # nose
    d.point([(hx + 5 + look, hy)], fill=PINK)
    # eye
    if blink:
        d.line([(hx + 1, hy - 1), (hx + 3, hy - 1)], fill=PUPIL)
    else:
        d.point([(hx + 2, hy - 1)], fill=EYE)
        d.point([(hx + 3, hy - 1)], fill=PUPIL)


def body(d, x0, y0, x1, y1):
    """Body ellipse with tabby stripes on the back and a white belly."""
    d.ellipse([x0, y0, x1, y1], fill=GINGER)
    cx = (x0 + x1) / 2
    d.ellipse([cx - (x1 - x0) * 0.3, y1 - 3, cx + (x1 - x0) * 0.3, y1], fill=WHITE)
    for sx in range(round(x0) + 4, round(x1) - 3, 4):
        d.line([(sx, y0 + 1), (sx + 1, y0 + 3)], fill=STRIPE)


def outline(img):
    px = img.load()
    out = img.copy()
    po = out.load()
    for y in range(H):
        for x in range(W):
            if px[x, y][3] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and px[nx, ny][3] > 0 and px[nx, ny] != ZCOL:
                        po[x, y] = OUTLINE
                        break
    return out


# ---------------------------------------------------------------- poses

def pose_stand(phase=0.0, blink=False, tail_a=60, walk=0.0, bob=0.0, run=False, look=0):
    img = new()
    d = ImageDraw.Draw(img)
    by = 16 + bob
    s = math.sin(phase)
    c = math.cos(phase)
    # far legs first
    if run:
        fr, hd = 4 * s, -4 * s
        leg(d, 28, by + 3, 28 + fr + 1, GROUND - 1 - max(0, c) * 2, GINGER_D, WHITE_D)
        leg(d, 16, by + 3, 16 + hd - 1, GROUND - 1 - max(0, -c) * 2, GINGER_D, WHITE_D)
    else:
        leg(d, 27, by + 3, 27 - 2.5 * walk * s, GROUND - 1 - max(0, -c) * walk * 1.5, GINGER_D, WHITE_D)
        leg(d, 17, by + 3, 17 + 2.5 * walk * s, GROUND - 1 - max(0, c) * walk * 1.5, GINGER_D, WHITE_D)
    tail(d, 13, by, tail_a + (8 * s if run else 4 * s * walk), length=12, curl=0.9 if not run else 0.2)
    body(d, 12, by - 2, 32, by + 5)
    if run:
        fr, hd = 4 * s, -4 * s
        leg(d, 30, by + 3, 30 + fr + 2, GROUND - 1 - max(0, -c) * 2)
        leg(d, 14, by + 3, 14 + hd - 2, GROUND - 1 - max(0, c) * 2)
    else:
        leg(d, 29, by + 3, 29 + 2.5 * walk * s, GROUND - 1 - max(0, c) * walk * 1.5)
        leg(d, 15, by + 3, 15 - 2.5 * walk * s, GROUND - 1 - max(0, -c) * walk * 1.5)
    # white chest
    d.ellipse([28, by - 1, 33, by + 4], fill=WHITE)
    head(d, 34, by - 5 + (bob * 0.5), blink=blink, look=look)
    return outline(img)


def pose_sit(tail_sway=0.0, blink=False, ear=0, groom=None):
    img = new()
    d = ImageDraw.Draw(img)
    # tail curled around the front paws on the ground
    tail(d, 17, GROUND - 2, -10 + tail_sway, length=13, curl=-0.5)
    # haunch + upright body
    ell(d, 20, GROUND - 5, 6, 5, GINGER)
    d.polygon([(18, GROUND - 9), (24, 12), (30, 14), (29, GROUND - 2), (19, GROUND - 1)], fill=GINGER)
    for sy in (15, 19):
        d.line([(19 + (sy - 15) * 0.3, sy + 2), (21 + (sy - 15) * 0.3, sy)], fill=STRIPE)
    # chest bib
    d.polygon([(26, 14), (30, 14), (29, GROUND - 3), (25, GROUND - 5)], fill=WHITE)
    # hind paw (white)
    d.line([(17, GROUND - 1), (21, GROUND - 1)], fill=WHITE, width=2)
    if groom is None:
        leg(d, 26, 19, 26, GROUND - 1, GINGER_D, WHITE_D)
        leg(d, 28, 19, 28, GROUND - 1)
        head(d, 29, 10, blink=blink, ear_flick=ear)
    else:
        # groom: one white paw raised to the mouth, head tilted down
        leg(d, 26, 19, 26, GROUND - 1, GINGER_D, WHITE_D)
        lift = groom
        leg(d, 28, 19, 32, 16 - lift)
        head(d, 29, 10, blink=True, down=2 + lift * 0.5, look=-1)
        d.point([(33, 14 + lift * 0.5)], fill=PINK)  # tongue
    return outline(img)


def pose_sleep(breath=0, z=0):
    img = new()
    d = ImageDraw.Draw(img)
    # curled ball with stripes
    ell(d, 21, GROUND - 4 - breath * 0.5, 8.5, 4.5 + breath * 0.5, GINGER)
    for sx in (15, 19, 23):
        d.line([(sx, GROUND - 8 - breath * 0.5), (sx + 1, GROUND - 6)], fill=STRIPE)
    # head tucked on the right, eyes closed
    hx, hy = 28, GROUND - 4
    d.polygon([(hx - 2, hy - 2), (hx - 1, hy - 6), (hx + 1, hy - 3)], fill=GINGER)
    d.polygon([(hx + 1, hy - 3), (hx + 3, hy - 6), (hx + 4, hy - 2)], fill=GINGER)
    d.point([(hx - 1, hy - 4), (hx + 3, hy - 4)], fill=PINK)
    ell(d, hx + 1, hy, 3.6, 3, GINGER)
    d.polygon([(hx + 2, hy + 1), (hx + 5, hy + 1.5), (hx + 4, hy + 3), (hx, hy + 3)], fill=WHITE)
    d.point([(hx + 5, hy + 1)], fill=PINK)
    d.line([(hx + 1, hy - 0), (hx + 3, hy - 0)], fill=PUPIL)
    # white front paws peeking out under the chin
    d.line([(hx - 2, GROUND), (hx + 2, GROUND)], fill=WHITE, width=1)
    # tail wrapped along the front
    for i, (x, y) in enumerate([(13, GROUND - 2), (16, GROUND - 0.5), (20, GROUND), (24, GROUND)]):
        ell(d, x, y - 1, 1.3, 1.2, STRIPE if i % 2 else GINGER)
    img = outline(img)
    d = ImageDraw.Draw(img)

    def zed(zx, zy, n):
        d.line([(zx, zy), (zx + n, zy)], fill=ZCOL)
        for k in range(n + 1):
            d.point([(zx + n - k, zy + k)], fill=ZCOL)
        d.line([(zx, zy + n), (zx + n, zy + n)], fill=ZCOL)
    if z > 0:
        zed(33, 12 - z, 3)
    if z > 1:
        zed(38, 3, 4)
    return img


def pose_jump(up=True):
    img = new()
    d = ImageDraw.Draw(img)
    by = 13
    if up:
        leg(d, 28, by + 3, 33, by - 1, GINGER_D, WHITE_D)
        leg(d, 16, by + 3, 10, by + 9, GINGER_D, WHITE_D)
        tail(d, 13, by, 10, length=12, curl=0.3)
        body(d, 12, by - 3, 32, by + 4)
        leg(d, 30, by + 3, 35, by)
        leg(d, 14, by + 3, 8, by + 10)
        head(d, 34, by - 6)
    else:
        leg(d, 28, by + 3, 30, by + 11, GINGER_D, WHITE_D)
        leg(d, 16, by + 3, 18, by + 10, GINGER_D, WHITE_D)
        tail(d, 13, by, 50, length=12, curl=0.8)
        body(d, 12, by - 2, 32, by + 5)
        leg(d, 30, by + 3, 33, by + 11)
        leg(d, 14, by + 3, 16, by + 11)
        head(d, 34, by - 3)
    return outline(img)


def frames():
    out = {}
    out['walk'] = [pose_stand(phase=i * 2 * math.pi / 6, walk=1.0, bob=(1 if i % 3 == 1 else 0)) for i in range(6)]
    out['run'] = [pose_stand(phase=i * 2 * math.pi / 6, run=True, bob=round(-1.5 * math.sin(i * 2 * math.pi / 6)), tail_a=15) for i in range(6)]
    out['stand'] = [pose_stand(tail_a=60 + a) for a in (0, 5, 10, 5)] + [pose_stand(blink=True)]
    out['sit'] = [pose_sit(tail_sway=s) for s in (0, 3, 6, 3)] + [pose_sit(blink=True), pose_sit(ear=1)]
    out['groom'] = [pose_sit(groom=g) for g in (0, 1, 2, 1)]
    out['sleep'] = [pose_sleep(breath=b, z=z) for b, z in ((0, 0), (1, 1), (1, 2), (0, 0))]
    out['jump'] = [pose_jump(True), pose_jump(False)]
    return out


def main(dst):
    os.makedirs(dst, exist_ok=True)
    allf = frames()
    for name, fl in allf.items():
        for i, f in enumerate(fl):
            big = f.resize((W * SCALE, H * SCALE), Image.NEAREST)
            big.save(os.path.join(dst, f'{name}_{i}_r.png'))
            big.transpose(Image.FLIP_LEFT_RIGHT).save(os.path.join(dst, f'{name}_{i}_l.png'))
    root = os.path.dirname(dst.rstrip('/')) or '.'
    # panel icon: sitting cat, cropped square
    icon = allf['sit'][0].crop((10, 0, 40, 30)).resize((60, 60), Image.NEAREST)
    sq = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    sq.alpha_composite(icon, (2, 2))
    sq.save(os.path.join(root, 'icon.png'))
    # preview sheet
    rows = list(allf.items())
    cols = max(len(v) for _, v in rows)
    sheet = Image.new('RGBA', (cols * W * 4, len(rows) * H * 4), (90, 110, 130, 255))
    for r, (_, fl) in enumerate(rows):
        for c, f in enumerate(fl):
            sheet.alpha_composite(f.resize((W * 4, H * 4), Image.NEAREST), (c * W * 4, r * H * 4))
    sheet.save(os.path.join(root, 'preview.png'))


if __name__ == '__main__':
    main(sys.argv[1])
