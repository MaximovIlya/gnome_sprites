#!/usr/bin/env python3
"""Procedural pixel-art fox sprite generator.

Draws a side-view fox (facing right) on a small canvas, outlines it,
upscales with nearest-neighbour and writes <anim>_<i>_<r|l>.png frames.
"""
import math
import os
import sys

from PIL import Image, ImageDraw

W, H = 44, 30
GROUND = 28
SCALE = int(os.environ.get('FOX_SCALE', 3))

# white fox with black accents (inverse of the wallpaper silver fox)
ORANGE = (236, 236, 238, 255)   # body
ORANGE_D = (176, 176, 184, 255) # shading / far legs
ORANGE_L = (214, 214, 218, 255) # tail middle
HEAD = (224, 224, 228, 255)     # head
WHITE = (255, 255, 255, 255)    # bright cheeks, chest, belly
TIP = (40, 40, 44, 255)         # black tail tip
MASK = (60, 60, 66, 255)        # stripe over the eye
DARK = (16, 16, 18, 255)
OUTLINE = (8, 8, 10, 255)
NOSE = (6, 6, 8, 255)
ZCOL = (230, 236, 255, 255)


def new():
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def ell(d, cx, cy, rx, ry, col):
    d.ellipse([round(cx - rx), round(cy - ry), round(cx + rx), round(cy + ry)], fill=col)


def leg(d, x0, y0, x1, y1, col=ORANGE, sock=DARK, w=2):
    """Leg from hip/shoulder (x0,y0) to foot (x1,y1); lower third is a dark sock."""
    mx = x0 + (x1 - x0) * 0.55
    my = y0 + (y1 - y0) * 0.55
    d.line([(x0, y0), (mx, my)], fill=col, width=w)
    d.line([(mx, my), (x1, y1)], fill=sock, width=w)
    d.point([(x1 + 1, y1)], fill=sock)  # paw toe


def tail(d, bx, by, angle, length=13, droop=0.0):
    """Bushy tail starting at (bx,by), pointing back (left) with given angle (deg, + = up)."""
    pts = []
    n = 9
    for i in range(n + 1):
        t = i / n
        a = math.radians(angle) - droop * t * t
        x = bx - math.cos(a) * length * t
        y = by - math.sin(a) * length * t
        pts.append((x, y, t))
    for x, y, t in pts:
        r = 1.6 + 2.6 * math.sin(math.pi * min(1.0, t * 1.15)) if t < 0.95 else 2.2
        col = TIP if t > 0.8 else (ORANGE_D if t < 0.2 else ORANGE_L)
        ell(d, x, y, r, r * 0.9, col)


def head(d, hx, hy, look=0, blink=False, down=0, ear_flick=0):
    """Head centred at (hx,hy), snout to the right."""
    hy += down
    # ears
    d.polygon([(hx - 3, hy - 3), (hx - 1 - ear_flick, hy - 8), (hx + 1, hy - 3)], fill=DARK)
    d.polygon([(hx + 1, hy - 3), (hx + 3, hy - 8), (hx + 4, hy - 3)], fill=DARK)
    d.point([(hx - 1 - ear_flick, hy - 5), (hx + 3, hy - 5)], fill=ORANGE)
    d.point([(hx - 1 - ear_flick, hy - 4)], fill=ORANGE)
    # skull
    ell(d, hx, hy, 4.2, 3.6, HEAD)
    # snout
    d.polygon([(hx + 2, hy - 1), (hx + 8 + look, hy + 1), (hx + 7 + look, hy + 2.5), (hx + 1, hy + 3)], fill=HEAD)
    # dark mask over the eye
    d.line([(hx, hy - 1), (hx + 4, hy - 1)], fill=MASK)
    # white cheek / jaw
    d.polygon([(hx - 2, hy + 1), (hx + 1, hy + 4), (hx + 7 + look, hy + 2.5), (hx + 3, hy + 1.5)], fill=WHITE)
    # nose
    d.point([(hx + 8 + look, hy + 1)], fill=NOSE)
    # eye
    if blink:
        d.line([(hx + 1, hy), (hx + 2, hy)], fill=NOSE)
    else:
        d.point([(hx + 2, hy - 1)], fill=NOSE)
        d.point([(hx + 2, hy)], fill=NOSE)


def body(d, x0, y0, x1, y1):
    """Body as ellipse with lighter belly."""
    d.ellipse([x0, y0, x1, y1], fill=ORANGE)
    # back shading
    d.arc([x0, y0, x1, y1], 200, 340, fill=ORANGE_D)
    # belly
    cx = (x0 + x1) / 2
    d.ellipse([cx - (x1 - x0) * 0.32, y1 - 3, cx + (x1 - x0) * 0.32, y1], fill=WHITE)


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

def pose_stand(phase=0.0, blink=False, tail_a=20, walk=0.0, bob=0.0, run=False, look=0):
    img = new()
    d = ImageDraw.Draw(img)
    by = 15 + bob
    # far legs (darker), drawn first
    s = math.sin(phase)
    c = math.cos(phase)
    if run:
        # gallop: front pair together, hind pair together
        fr = 4 * s
        hd = -4 * s
        leg(d, 29, by + 4, 29 + fr + 1, GROUND - 1 - max(0, c) * 2, ORANGE_D)
        leg(d, 15, by + 4, 15 + hd - 1, GROUND - 1 - max(0, -c) * 2, ORANGE_D)
    else:
        leg(d, 28, by + 4, 28 - 2.5 * walk * s, GROUND - 1 - max(0, -c) * walk * 1.5, ORANGE_D)
        leg(d, 16, by + 4, 16 + 2.5 * walk * s, GROUND - 1 - max(0, c) * walk * 1.5, ORANGE_D)
    tail(d, 13, by, tail_a + (6 * s if run else 3 * s * walk), length=10, droop=0.25)
    body(d, 11, by - 2, 33, by + 6)
    if run:
        fr = 4 * s
        hd = -4 * s
        leg(d, 31, by + 4, 31 + fr + 2, GROUND - 1 - max(0, -c) * 2)
        leg(d, 13, by + 4, 13 + hd - 2, GROUND - 1 - max(0, c) * 2)
    else:
        leg(d, 30, by + 4, 30 + 2.5 * walk * s, GROUND - 1 - max(0, c) * walk * 1.5)
        leg(d, 14, by + 4, 14 - 2.5 * walk * s, GROUND - 1 - max(0, -c) * walk * 1.5)
    head(d, 34, by - 4 + (bob * 0.5), blink=blink, look=look)
    return outline(img)


def pose_sit(tail_sway=0.0, blink=False, ear=0, groom=None):
    img = new()
    d = ImageDraw.Draw(img)
    # tail wrapped on the ground in front-left
    tail(d, 18, GROUND - 3, -8 + tail_sway, length=12, droop=-0.35)
    # haunch + upright body
    ell(d, 19, GROUND - 5, 6, 5, ORANGE)
    d.polygon([(17, GROUND - 9), (24, 11), (30, 13), (29, GROUND - 2), (19, GROUND - 1)], fill=ORANGE)
    # chest bib
    d.polygon([(26, 14), (30, 14), (29, GROUND - 3), (25, GROUND - 5)], fill=WHITE)
    # hind paw
    d.line([(17, GROUND - 1), (21, GROUND - 1)], fill=DARK, width=2)
    # front legs
    if groom is None:
        leg(d, 26, 19, 26, GROUND - 1, ORANGE_D)
        leg(d, 28, 19, 28, GROUND - 1)
        head(d, 29, 10, blink=blink, ear_flick=ear)
    else:
        # groom: one paw raised to mouth, head tilted down
        leg(d, 26, 19, 26, GROUND - 1, ORANGE_D)
        lift = groom
        leg(d, 28, 19, 32, 17 - lift)
        head(d, 29, 10, blink=True, down=2 + lift * 0.5, look=-1)
        # tongue
        d.point([(35, 15 + lift * 0.5)], fill=(230, 110, 130, 255))
    return outline(img)


def pose_sleep(breath=0, z=0):
    img = new()
    d = ImageDraw.Draw(img)
    # curled ball
    ell(d, 22, GROUND - 4 - breath * 0.5, 9, 4.5 + breath * 0.5, ORANGE)
    d.arc([13, GROUND - 9 - breath, 31, GROUND], 180, 300, fill=ORANGE_D)
    # head resting on the right, eyes closed
    hx, hy = 29, GROUND - 4
    d.polygon([(hx - 2, hy - 3), (hx, hy - 7), (hx + 1, hy - 3)], fill=DARK)
    d.polygon([(hx + 1, hy - 3), (hx + 3, hy - 7), (hx + 4, hy - 3)], fill=DARK)
    d.point([(hx, hy - 4), (hx + 3, hy - 4)], fill=ORANGE)
    ell(d, hx + 1, hy, 3.6, 3, HEAD)
    d.polygon([(hx + 2, hy), (hx + 7, hy + 1.5), (hx + 6, hy + 3), (hx, hy + 3)], fill=WHITE)
    d.point([(hx + 7, hy + 1)], fill=NOSE)
    d.line([(hx + 1, hy), (hx + 2, hy)], fill=NOSE)
    # tail wrapped over the front, white tip covering the nose
    pts = [(13, GROUND - 3), (16, GROUND - 1), (21, GROUND), (26, GROUND), (30, GROUND - 1)]
    for i, (x, y) in enumerate(pts):
        col = TIP if i >= 4 else ORANGE_L
        ell(d, x, y - 1, 2.4, 2, col)
    img = outline(img)
    # floating Zs (no outline)
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
        leg(d, 29, by + 3, 34, by - 1, ORANGE_D)
        leg(d, 15, by + 4, 9, by + 9, ORANGE_D)
        tail(d, 13, by, 5, length=10, droop=0.1)
        body(d, 11, by - 3, 33, by + 5)
        leg(d, 31, by + 3, 36, by, )
        leg(d, 13, by + 4, 7, by + 10)
        head(d, 34, by - 6)
    else:
        leg(d, 29, by + 4, 31, by + 11, ORANGE_D)
        leg(d, 15, by + 4, 17, by + 10, ORANGE_D)
        tail(d, 13, by, 35, length=10, droop=0.3)
        body(d, 11, by - 2, 33, by + 6)
        leg(d, 31, by + 4, 34, by + 11)
        leg(d, 13, by + 4, 15, by + 11)
        head(d, 34, by - 3)
    return outline(img)


def frames():
    out = {}
    out['walk'] = [pose_stand(phase=i * 2 * math.pi / 6, walk=1.0, bob=(1 if i % 3 == 1 else 0), tail_a=18) for i in range(6)]
    out['run'] = [pose_stand(phase=i * 2 * math.pi / 6, run=True, bob=round(-1.5 * math.sin(i * 2 * math.pi / 6)), tail_a=8) for i in range(6)]
    out['stand'] = [pose_stand(tail_a=22 + a) for a in (0, 3, 6, 3)] + [pose_stand(tail_a=22, blink=True)]
    out['sit'] = [pose_sit(tail_sway=s) for s in (0, 2, 4, 2)] + [pose_sit(blink=True), pose_sit(ear=1)]
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
    # preview sheet
    rows = list(allf.items())
    cols = max(len(v) for _, v in rows)
    sheet = Image.new('RGBA', (cols * W * 4, len(rows) * H * 4), (90, 110, 130, 255))
    for r, (_, fl) in enumerate(rows):
        for c, f in enumerate(fl):
            sheet.alpha_composite(f.resize((W * 4, H * 4), Image.NEAREST), (c * W * 4, r * H * 4))
    sheet.save(os.path.join(os.path.dirname(dst.rstrip('/')) or '.', 'preview.png'))


if __name__ == '__main__':
    main(sys.argv[1])
