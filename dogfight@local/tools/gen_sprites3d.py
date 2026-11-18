#!/usr/bin/env python3
"""Pre-rendered 3D sprites for dogfight v2 (pure Python + Pillow, no numpy).

A generic single-engine fighter is built from parametric surfaces, painted
with a procedural camouflage and rendered (painter's algorithm, back-face
culling, 3x supersampling) from every view direction on a sphere:

  columns: azimuth 0..180 deg (step 7.5; negative azimuth = mirrored sprite)
  rows:    elevation -82.5..82.5 deg (step 15)

Body frame: x = nose, y = up (canopy), z = cross(x, y).  The sprite camera
sits at direction d = (cos el cos az, sin el, cos el sin az) from the jet,
fwd = -d, right = norm(cross(fwd, y)), up = cross(right, fwd).  The
extension uses exactly the same convention to pick a cell and rotate it.

Also renders explosions, smoke, parachutes, ejection seats and debris.
Usage: gen_sprites3d.py <extension-dir>
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageChops

CELL = 112
SS = 3
K = 0.85                     # sprite px per body unit = K * CELL
AZ_N, AZ_STEP = 25, 7.5
EL_N, EL0, EL_STEP = 12, -82.5, 15.0

# ------------------------------------------------------------ vector utils


def add(a, b, k=1.0):
    return (a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k)


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    ln = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / ln, a[1] / ln, a[2] / ln)


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ noise

def _hash(i, j, k, seed):
    n = (i * 374761393 + j * 668265263 + k * 2147483647 + seed * 144665) & 0xffffffff
    n = ((n ^ (n >> 13)) * 1274126177) & 0xffffffff
    return ((n ^ (n >> 16)) & 0xffff) / 65535.0


def vnoise(x, y, z, seed=0):
    xi, yi, zi = math.floor(x), math.floor(y), math.floor(z)
    xf, yf, zf = smooth(x - xi), smooth(y - yi), smooth(z - zi)
    c = [[[_hash(xi + a, yi + b, zi + cc, seed) for cc in (0, 1)] for b in (0, 1)] for a in (0, 1)]
    x00 = lerp(c[0][0][0], c[1][0][0], xf)
    x10 = lerp(c[0][1][0], c[1][1][0], xf)
    x01 = lerp(c[0][0][1], c[1][0][1], xf)
    x11 = lerp(c[0][1][1], c[1][1][1], xf)
    return lerp(lerp(x00, x10, yf), lerp(x01, x11, yf), zf)


def fbm(x, y, z, seed=0, oct=3):
    s, a, f, tot = 0.0, 1.0, 1.0, 0.0
    for o in range(oct):
        s += a * vnoise(x * f, y * f, z * f, seed + o * 17)
        tot += a
        a *= 0.5
        f *= 2.03
    return s / tot


# --------------------------------------------------------------- liveries

LIVERIES = {
    'wood': {
        'camo': [(84, 94, 54), (44, 58, 38), (98, 76, 50), (34, 36, 30)],
        'belly': (150, 160, 162),
        'radome': (62, 66, 64),
        'roundel': [(200, 40, 36), (235, 235, 230), (200, 40, 36)],
        'seed': 3,
    },
    'desert': {
        'camo': [(196, 168, 118), (150, 112, 72), (176, 152, 104), (112, 88, 60)],
        'belly': (172, 184, 194),
        'radome': (120, 112, 98),
        'roundel': [(36, 80, 170), (235, 235, 230), (36, 80, 170)],
        'seed': 11,
    },
}

GLASS = (28, 38, 52)
FRAME = (60, 62, 60)
METAL = (78, 76, 74)
METAL_D = (30, 28, 28)
MISSILE = (214, 214, 206)
INTAKE = (16, 16, 18)


def camo(liv, p):
    s = liv['seed']
    x, y, z = p[0] * 5.2, p[1] * 5.2, abs(p[2]) * 5.2 + (0.37 if p[2] < 0 else 0)
    c = liv['camo']
    f1 = fbm(x, y, z, s)
    f2 = fbm(x + 13.1, y - 4.2, z + 7.7, s + 5)
    f3 = fbm(x * 1.6 - 3, y * 1.6, z * 1.6 + 9, s + 9)
    col = c[0]
    if f1 > 0.53:
        col = c[1]
    if f2 > 0.58:
        col = c[2]
    if f3 > 0.66:
        col = c[3]
    return col


# ------------------------------------------------------------------ model


class Mesh:
    def __init__(self):
        self.v = []
        self.faces = []   # dicts: idx, n, c, part, spec, bias, color(liv,p,n)

    def vert(self, p):
        self.v.append(p)
        return len(self.v) - 1

    def grid(self, fn, nu, nv, part, out, wrap_v=False, spec=0.08, paint=None):
        """fn(u, v) -> point; out(centroid) -> outward hint vector."""
        idx = []
        nvv = nv if wrap_v else nv + 1
        for i in range(nu + 1):
            row = []
            for j in range(nvv):
                row.append(self.vert(fn(i / nu, j / nv)))
            idx.append(row)
        for i in range(nu):
            for j in range(nv):
                j1 = (j + 1) % nvv if wrap_v else j + 1
                q = [idx[i][j], idx[i + 1][j], idx[i + 1][j1], idx[i][j1]]
                self.face(q, part, out, spec, paint)

    def face(self, q, part, out, spec=0.08, paint=None, bias=0.0):
        pts = [self.v[k] for k in q]
        c = mul(pts[0], 0)
        for p in pts:
            c = add(c, p)
        c = mul(c, 1 / len(pts))
        n = cross(sub(pts[2], pts[0]), sub(pts[3 % len(pts)], pts[1]))
        if dot(n, n) < 1e-14:
            n = cross(sub(pts[1], pts[0]), sub(pts[2], pts[0]))
        if dot(n, n) < 1e-14:
            return
        n = norm(n)
        if dot(n, out(c)) < 0:
            n = mul(n, -1)
        self.faces.append({'idx': q, 'n': n, 'c': c, 'part': part, 'spec': spec,
                           'paint': paint, 'bias': bias})


def fus_section(x):
    """half-width, half-height (top), half-height (bottom), centre y."""
    if x > 0.22:
        t = (0.5 - x) / 0.28
        r = 0.066 * math.sqrt(max(0.0, 1 - (1 - t) ** 2))
        return r, r, r, -0.006 * t
    if x < -0.38:
        t = (x + 0.5) / 0.12
        r = lerp(0.046, 0.066, t)
        return r, lerp(0.048, 0.07, t), r, 0.0
    spine = 0.016 * smooth((0.2 - x) / 0.1) * smooth((x + 0.36) / 0.12)
    return 0.066, 0.07 + spine, 0.064, 0.0


def build():
    m = Mesh()
    # fuselage ----------------------------------------------------------
    def fus(u, v):
        x = 0.5 - u
        a, bt, bb, yc = fus_section(x)
        th = v * 2 * math.pi
        s = math.sin(th)
        return (x, yc + (bt if s > 0 else bb) * s, a * math.cos(th))
    m.grid(fus, 80, 28, 'fus', lambda c: (0, c[1] - fus_section(c[0])[3], c[2]), wrap_v=True)
    # nozzle
    def noz(u, v):
        x = -0.5 - 0.035 * u
        r = lerp(0.046, 0.04, u)
        th = v * 2 * math.pi
        return (x, r * math.sin(th), r * math.cos(th))
    m.grid(noz, 3, 20, 'nozzle', lambda c: (0, c[1], c[2]), wrap_v=True, spec=0.35)
    def cap(u, v):
        r = 0.04 * (1 - u)
        th = v * 2 * math.pi
        return (-0.535 + 0.01 * u, r * math.sin(th), r * math.cos(th))
    m.grid(cap, 2, 20, 'cap', lambda c: (-1, 0, 0), wrap_v=True, spec=0.0)
    # canopy -------------------------------------------------------------
    cc = (0.215, 0.058, 0.0)
    cr = (0.105, 0.052, 0.04)
    def can(u, v):
        th = u * math.pi            # along x
        ph = v * math.pi            # around, upper half
        return (cc[0] + cr[0] * math.cos(th), cc[1] + cr[1] * math.sin(th) * math.sin(ph),
                cr[2] * math.sin(th) * math.cos(ph))
    m.grid(can, 18, 12, 'canopy', lambda c: sub(c, (cc[0], cc[1] - 0.03, 0)), spec=0.9)
    # intakes (boxes on both cheeks) ----------------------------------------
    for sg in (1, -1):
        x0, x1 = -0.06, 0.17
        z0, z1 = 0.055, 0.108
        y0, y1 = -0.058, 0.006
        m.grid(lambda u, v: (lerp(x1, x0, u), y1, sg * lerp(z0, z1, v)), 10, 3, 'intake',
               lambda c: (0, 1, 0))
        m.grid(lambda u, v: (lerp(x1, x0, u), y0, sg * lerp(z0, z1, v)), 10, 3, 'intake',
               lambda c: (0, -1, 0))
        m.grid(lambda u, v: (lerp(x1, x0, u), lerp(y0, y1, v), sg * z1), 10, 3, 'intake',
               lambda c, sg=sg: (0, 0, sg))
        m.grid(lambda u, v: (x1, lerp(y0, y1, v), sg * lerp(z0, z1, u)), 1, 1, 'intake_mouth',
               lambda c: (1, 0, 0), spec=0.0)
    # lifting surfaces ---------------------------------------------------
    def surface(part, root, tip, z0, z1, th0, th1, y0, dih, nu, nv, vertical=False):
        """root/tip = (LE x, TE x); thickness profile closes at LE and TE."""
        for side in (1, -1):
            for top in (1, -1):
                def fn(u, v, side=side, top=top):
                    le = lerp(root[0], tip[0], u)
                    te = lerp(root[1], tip[1], u)
                    x = lerp(le, te, v)
                    t = lerp(th0, th1, u) * 2.6 * v ** 0.6 * (1 - v)
                    span = lerp(z0, z1, u)
                    if vertical:
                        return (x, span, top * t / 2)
                    return (x, y0 + (span - z0) * dih + top * t / 2, side * span)
                if vertical:
                    hint = (lambda c, top=top: (0, 0, top))
                else:
                    hint = (lambda c, top=top: (0, top, 0))
                m.grid(fn, nu, nv, part, hint, spec=0.08)
            if vertical:
                break
    surface('wing', (0.12, -0.24), (-0.15, -0.245), 0.05, 0.37, 0.024, 0.008, -0.012, -0.03, 22, 14)
    surface('stab', (-0.30, -0.475), (-0.42, -0.49), 0.04, 0.17, 0.013, 0.005, -0.004, 0.0, 8, 7)
    surface('fin', (-0.17, -0.46), (-0.39, -0.475), 0.05, 0.255, 0.015, 0.005, 0, 0, 10, 9,
            vertical=True)
    # wing-tip missiles --------------------------------------------------
    for sg in (1, -1):
        zc, yc, r = sg * 0.378, -0.022, 0.0085
        def mis(u, v, zc=zc):
            x = lerp(0.02, -0.22, u)
            rr = r * (min(1.0, u / 0.12) ** 0.6)
            th = v * 2 * math.pi
            return (x, yc + rr * math.sin(th), zc + rr * math.cos(th))
        m.grid(mis, 12, 8, 'missile', lambda c, zc=zc: (0, c[1] - yc, c[2] - zc), wrap_v=True,
               spec=0.4)
        # launch rail
        m.grid(lambda u, v, zc=zc: (lerp(-0.04, -0.2, u), lerp(yc, -0.012, v), zc), 3, 1, 'rail',
               lambda c, sg=sg: (0, 0, sg))
    decals(m)
    return m


def disc(m, centre, n, u_ax, v_ax, r, color, ring=None):
    pts = []
    for k in range(18):
        a = k / 18 * 2 * math.pi
        pts.append(m.vert(add(add(centre, u_ax, r * math.cos(a)), v_ax, r * math.sin(a))))
    c0 = centre
    m.faces.append({'idx': pts, 'n': n, 'c': c0, 'part': 'decal', 'spec': 0.05,
                    'paint': color, 'bias': -0.015 * (1 if ring is None else ring)})


def decals(m):
    # roundels on wings (top and bottom) and fuselage sides; fin flash
    for sg in (1, -1):
        for top in (1, -1):
            y = -0.012 + (0.24 - 0.05) * -0.03 + top * 0.0045
            c = (-0.15, y, sg * 0.24)
            n = (0, top, 0)
            for k, r in enumerate((0.05, 0.034, 0.016)):
                disc(m, add(c, n, 0.0005 * k), n, (1, 0, 0), (0, 0, 1), r, ('roundel', k), ring=1 + k)
        c = (-0.25, 0.0, sg * 0.0695)
        n = (0, 0, sg)
        for k, r in enumerate((0.032, 0.022, 0.011)):
            disc(m, add(c, n, 0.0007 * k), n, (1, 0, 0), (0, 1, 0), r, ('roundel', k), ring=1 + k)
        # fin flash
        for k, r in enumerate((0.026, 0.018, 0.009)):
            fc = (-0.37, 0.19, sg * 0.0045 + sg * 0.0006 * k)
            disc(m, fc, (0, 0, sg), (1, 0, 0), (0, 1, 0), r, ('roundel', k), ring=1 + k)


def base_color(f, liv):
    p, n, part = f['c'], f['n'], f['part']
    paint = f['paint']
    if isinstance(paint, tuple) and paint and paint[0] == 'roundel':
        return liv['roundel'][paint[1]]
    if part == 'canopy':
        if abs(p[0] - 0.165) < 0.007 or abs(p[0] - 0.27) < 0.006:
            return FRAME
        return GLASS
    if part == 'nozzle':
        return METAL
    if part == 'cap':
        return METAL_D
    if part == 'intake_mouth':
        return INTAKE
    if part == 'missile':
        return (180, 40, 30) if p[0] > -0.005 else MISSILE
    if part == 'rail':
        return (70, 72, 70)
    if part == 'fus' and p[0] > 0.4:
        return liv['radome']
    belly = n[1] < -0.3 and part in ('fus', 'wing', 'stab', 'intake')
    col = liv['belly'] if belly else camo(liv, p)
    # panel lines / control surfaces
    dark = False
    if part == 'fus':
        for xl in (0.36, 0.06, -0.12, -0.33):
            if abs(p[0] - xl) < 0.0063:
                dark = True
    if dark:
        col = tuple(int(c * 0.8) for c in col)
    return col


# ----------------------------------------------------------------- render

L = norm((-0.35, 0.5, 0.8))
H = norm(add(L, (0, 0, 1)))


def cam_basis(az, el):
    a, e = math.radians(az), math.radians(el)
    d = (math.cos(e) * math.cos(a), math.sin(e), math.cos(e) * math.sin(a))
    fwd = mul(d, -1)
    right = norm(cross(fwd, (0, 1, 0)))
    up = cross(right, fwd)
    return d, fwd, right, up


def render(m, colors, az, el, size=CELL):
    d, fwd, right, up = cam_basis(az, el)
    S = size * SS
    k = K * S
    cx = cy = S / 2
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    scr = [(cx + k * dot(p, right), cy - k * dot(p, up)) for p in m.v]
    todo = []
    for f, col in zip(m.faces, colors):
        n = f['n']
        nd = dot(n, d)
        if nd <= 0.0:
            continue
        depth = dot(f['c'], fwd) + f['bias']
        nc = (dot(n, right), dot(n, up), nd)
        dif = max(0.0, dot(nc, L))
        spec = f['spec'] * max(0.0, dot(nc, H)) ** 24 * 255
        shade = (0.42 + 0.68 * dif) * (0.82 + 0.18 * nd)
        c = tuple(min(255, int(ch * shade + spec)) for ch in col) + (255,)
        todo.append((depth, f['idx'], c))
    todo.sort(key=lambda t: -t[0])
    for _depth, idx, c in todo:
        pts = [scr[i] for i in idx]
        dr.polygon(pts, fill=c, outline=c)
    img = img.resize((size, size), Image.BOX)
    return outline(img)


def outline(img, alpha=0.55, col=(12, 14, 16)):
    a = img.getchannel('A')
    dil = a.filter(ImageFilter.MaxFilter(3))
    ring = ImageChops.subtract(dil, a).point(lambda v: int(v * alpha))
    o = Image.new('RGBA', img.size, col + (0,))
    o.putalpha(ring)
    return Image.alpha_composite(o, img)


def atlas(m, liv_name, dst):
    liv = LIVERIES[liv_name]
    colors = [base_color(f, liv) for f in m.faces]
    sheet = Image.new('RGBA', (CELL * AZ_N, CELL * EL_N), (0, 0, 0, 0))
    for r in range(EL_N):
        el = EL0 + r * EL_STEP
        for c in range(AZ_N):
            az = c * AZ_STEP
            sheet.paste(render(m, colors, az, el), (c * CELL, r * CELL))
    sheet.save(os.path.join(dst, f'jet_{liv_name}.png'), optimize=True)
    half = sheet.resize((sheet.width // 2, sheet.height // 2), Image.LANCZOS)
    half.save(os.path.join(dst, f'jet_{liv_name}_half.png'), optimize=True)
    return sheet, colors


# ---------------------------------------------------------------- effects

def ramp(h):
    stops = [(0.0, (34, 30, 28)), (0.25, (120, 36, 14)), (0.45, (220, 90, 18)),
             (0.65, (255, 168, 40)), (0.85, (255, 228, 120)), (1.0, (255, 252, 228))]
    h = max(0.0, min(1.0, h))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if h <= b:
            t = (h - a) / (b - a)
            return tuple(int(lerp(x, y, t)) for x, y in zip(ca, cb))
    return stops[-1][1]


def fireball(i, n=8, size=128):
    t = i / (n - 1)
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    px = img.load()
    R = size / 2 * (0.3 + 0.62 * math.sqrt(t))
    c = size / 2
    for y in range(size):
        for x in range(size):
            dx, dy = (x - c) / R, (y - c) / R
            dd = math.hypot(dx, dy)
            if dd > 1.45:
                continue
            nz = fbm(x / size * 5, y / size * 5, i * 0.45, 7)
            edge = 0.78 + 0.5 * (nz - 0.5) * 1.6
            if dd > edge:
                continue
            core = 1 - dd / edge
            heat = core * 1.5 * (1 - t) ** 1.2 + (nz - 0.5) * 0.5 - t * 0.15
            col = ramp(heat)
            # later frames: smoke takes over
            smoke = smooth((t - 0.35) / 0.6) * (1 - smooth(heat * 2))
            g = int(lerp(70, 40, nz))
            col = tuple(int(lerp(cc, g, smoke)) for cc in col)
            a = smooth((edge - dd) / 0.12) * (1 - smooth((t - 0.7) / 0.3) * 0.85)
            px[x, y] = col + (int(255 * a),)
    return img


def puff(kind, size=40):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    px = img.load()
    c = size / 2
    seed = {'smoke': 1, 'dark': 2, 'fire': 3}[kind]
    for y in range(size):
        for x in range(size):
            dd = math.hypot(x - c + 0.5, y - c + 0.5) / c
            nz = fbm(x / size * 3, y / size * 3, seed, seed)
            e = dd + (nz - 0.5) * 0.5
            if e >= 1:
                continue
            a = (1 - e) ** 1.3
            if kind == 'smoke':
                g = int(lerp(220, 175, nz))
                col, a = (g, g, g + 4), a * 0.8
            elif kind == 'dark':
                g = int(lerp(70, 30, nz))
                col, a = (g, g - 2, g - 4), a * 0.9
            else:
                col = ramp(0.45 + (1 - e) * 0.6)
            px[x, y] = col + (int(255 * min(1, a * 1.4)),)
    return img


def spark(size=21):
    S = size * 4
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = S / 2
    for k in range(8):
        a = k * math.pi / 4
        r = S * (0.48 if k % 2 == 0 else 0.28)
        d.line([(c, c), (c + math.cos(a) * r, c + math.sin(a) * r)], fill=(255, 200, 90, 255), width=5)
    d.ellipse([c - 12, c - 12, c + 12, c + 12], fill=(255, 250, 220, 255))
    return img.resize((size, size), Image.LANCZOS)


def debris(size=12):
    S = size * 4
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rnd = random.Random(5)
    pts = [(S / 2 + math.cos(a) * rnd.uniform(0.25, 0.48) * S, S / 2 + math.sin(a) * rnd.uniform(0.2, 0.45) * S)
           for a in [k * 2 * math.pi / 7 for k in range(7)]]
    d.polygon(pts, fill=(52, 54, 50, 255), outline=(20, 20, 20, 255), width=3)
    d.line([pts[0], pts[3]], fill=(96, 98, 90, 255), width=3)
    return img.resize((size, size), Image.LANCZOS)


def shard(size=12):
    S = size * 4
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(6, 10), (40, 4), (44, 30), (14, 42)], fill=(40, 56, 74, 255), outline=(70, 72, 70, 255), width=4)
    d.line([(14, 14), (32, 10)], fill=(170, 200, 230, 255), width=3)
    return img.resize((size, size), Image.LANCZOS)


SUIT = (88, 96, 66)
HELMET = (226, 226, 218)
VISOR = (30, 34, 40)


def seat(size=28):
    """Ejection seat with the pilot, side view (facing right)."""
    S = size * 4
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # seat back + headbox
    d.rounded_rectangle([22, 18, 40, 92], 5, fill=(52, 54, 56, 255), outline=(16, 16, 16, 255), width=3)
    d.rectangle([20, 10, 42, 30], fill=(64, 66, 68, 255), outline=(16, 16, 16, 255), width=3)
    # seat pan
    d.rounded_rectangle([28, 78, 76, 92], 4, fill=(52, 54, 56, 255), outline=(16, 16, 16, 255), width=3)
    # pilot: torso, thighs, shins, helmet
    d.rounded_rectangle([38, 36, 58, 82], 8, fill=SUIT + (255,), outline=(20, 22, 16, 255), width=3)
    d.rounded_rectangle([42, 68, 88, 82], 7, fill=SUIT + (255,), outline=(20, 22, 16, 255), width=3)
    d.rounded_rectangle([76, 72, 90, 108], 6, fill=SUIT + (255,), outline=(20, 22, 16, 255), width=3)
    d.rectangle([76, 100, 98, 110], fill=(30, 28, 26, 255))
    d.ellipse([38, 12, 64, 38], fill=HELMET + (255,), outline=(30, 30, 30, 255), width=3)
    d.chord([48, 18, 66, 34], -70, 70, fill=VISOR + (255,))
    # rocket nozzle under the seat
    d.rectangle([30, 92, 42, 100], fill=(40, 40, 40, 255))
    return img.resize((size, size), Image.LANCZOS)


CHUTES = {'wood': ((96, 106, 62), (170, 160, 112)), 'desert': ((214, 194, 146), (238, 234, 222))}


def chute(team, w=72, h=96):
    S = 4
    W, Hh = w * S, h * S
    img = Image.new('RGBA', (W, Hh), (0, 0, 0, 0))
    c1, c2 = CHUTES[team]
    cx = W / 2
    top, bot = 6 * S, 36 * S
    rx = W / 2 - 3 * S
    # dome mask (upper half ellipse + scalloped skirt)
    mask = Image.new('L', (W, Hh), 0)
    md = ImageDraw.Draw(mask)
    md.pieslice([cx - rx, top, cx + rx, top + 2 * (bot - top)], 180, 360, fill=255)
    gores = 10
    for k in range(gores):
        a0 = math.pi * k / gores
        a1 = math.pi * (k + 1) / gores
        x0 = cx - rx * math.cos(a0)
        x1 = cx - rx * math.cos(a1)
        md.chord([x0, bot - 3 * S, x1, bot + 4 * S], 0, 180, fill=255)
    dome = Image.new('RGBA', (W, Hh), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dome)
    for k in range(gores):
        a0 = math.pi * k / gores
        a1 = math.pi * (k + 1) / gores
        x0 = cx - rx * math.cos(a0)
        x1 = cx - rx * math.cos(a1)
        col = c1 if k % 2 == 0 else c2
        # shading: darker towards the limbs, lit from upper left
        mid = (a0 + a1) / 2
        sh = 0.62 + 0.38 * math.sin(mid) + 0.1 * math.cos(mid)
        col = tuple(min(255, int(ch * sh)) for ch in col)
        dd.rectangle([x0, 0, x1 + 1, bot + 6 * S], fill=col + (255,))
    # vertical shading gradient (top brighter)
    shade = Image.new('L', (W, Hh), 0)
    sd = ImageDraw.Draw(shade)
    for y in range(top, bot + 6 * S):
        t = (y - top) / (bot - top)
        sd.line([(0, y), (W, y)], fill=int(70 * t))
    dark = Image.new('RGBA', (W, Hh), (0, 0, 0, 255))
    dark.putalpha(ImageChops.multiply(shade, mask))
    dome.putalpha(mask)
    dome = Image.alpha_composite(dome, dark)
    d = ImageDraw.Draw(img)
    # suspension lines to the harness
    hx, hy = cx, 70 * S
    for k in range(gores + 1):
        x = cx - rx * math.cos(math.pi * k / gores) * 0.96
        d.line([(x, bot + 2 * S), (hx + (k - gores / 2) * 0.6 * S, hy)], fill=(60, 60, 56, 200), width=S // 2 + 1)
    img = Image.alpha_composite(img, dome)
    d = ImageDraw.Draw(img)
    ol = (24, 24, 20, 255)
    d.arc([cx - rx, top, cx + rx, top + 2 * (bot - top)], 180, 360, fill=ol, width=S)
    # pilot hanging under the risers
    d.line([(hx - 4 * S, hy), (hx - 3 * S, hy + 4 * S)], fill=(40, 40, 36, 255), width=S)
    d.line([(hx + 4 * S, hy), (hx + 3 * S, hy + 4 * S)], fill=(40, 40, 36, 255), width=S)
    d.rounded_rectangle([hx - 4 * S, hy + 6 * S, hx + 4 * S, hy + 17 * S], 2 * S, fill=SUIT + (255,), outline=ol, width=S // 2 + 1)
    d.line([(hx - 4 * S, hy + 7 * S), (hx - 5 * S, hy + 1 * S)], fill=SUIT + (255,), width=2 * S)  # arms up
    d.line([(hx + 4 * S, hy + 7 * S), (hx + 5 * S, hy + 1 * S)], fill=SUIT + (255,), width=2 * S)
    d.ellipse([hx - 3.2 * S, hy + 1.2 * S, hx + 3.2 * S, hy + 7.4 * S], fill=HELMET + (255,), outline=ol, width=S // 2 + 1)
    d.rounded_rectangle([hx - 3.6 * S, hy + 16 * S, hx - 0.6 * S, hy + 25 * S], S, fill=SUIT + (255,), outline=ol, width=S // 2)
    d.rounded_rectangle([hx + 0.6 * S, hy + 16 * S, hx + 3.6 * S, hy + 25 * S], S, fill=SUIT + (255,), outline=ol, width=S // 2)
    d.rectangle([hx - 4 * S, hy + 24 * S, hx - 0.4 * S, hy + 26 * S], fill=(30, 28, 26, 255))
    d.rectangle([hx + 0.4 * S, hy + 24 * S, hx + 4 * S, hy + 26 * S], fill=(30, 28, 26, 255))
    return img.resize((w, h), Image.LANCZOS)


# ------------------------------------------------------------------- main

def main(root):
    dst = os.path.join(root, 'sprites')
    os.makedirs(dst, exist_ok=True)
    only = os.environ.get('ONLY')
    m = build()
    print(f'mesh: {len(m.v)} verts, {len(m.faces)} faces')
    if only != 'fx':
        sheets = {}
        for liv in LIVERIES:
            sheets[liv], colors = atlas(m, liv, dst)
            print('atlas', liv, 'done')
        # panel icon and preview: 3/4 views
        wood = LIVERIES['wood']
        colors = [base_color(f, wood) for f in m.faces]
        ic = render(m, colors, 125, 28, 64)
        ic.save(os.path.join(root, 'icon.png'))
        prev = Image.new('RGBA', (900, 300), (118, 150, 182, 255))
        for k, (liv, az, el) in enumerate([('wood', 70, 10), ('desert', 135, 35), ('wood', 100, -40)]):
            cols = [base_color(f, LIVERIES[liv]) for f in m.faces]
            im = render(m, cols, az, el, 300)
            prev.alpha_composite(im, (k * 300, 0))
        prev.save(os.path.join(root, 'preview.png'))
    if only != 'jets':
        for i in range(8):
            fireball(i).save(os.path.join(dst, f'boom_{i}.png'))
        for kind in ('smoke', 'dark', 'fire'):
            puff(kind).save(os.path.join(dst, f'puff_{kind}.png'))
        spark().save(os.path.join(dst, 'spark.png'))
        debris().save(os.path.join(dst, 'debris.png'))
        shard().save(os.path.join(dst, 'shard.png'))
        seat().save(os.path.join(dst, 'seat.png'))
        for team in CHUTES:
            chute(team).save(os.path.join(dst, f'chute_{team}.png'))
        print('fx done')


if __name__ == '__main__':
    main(sys.argv[1])
