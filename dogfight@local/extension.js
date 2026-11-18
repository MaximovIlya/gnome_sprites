// Dogfight v2 — camouflaged fighter jets in a pseudo-3D sky over the desktop.
//
// World: right-handed, x = screen right, y = altitude (ground = bottom edge of
// the work area), z = towards the viewer (depth = -z).  Perspective:
//   s = FOCAL / (FOCAL + depth),  screen = (cx + x*s, groundY - y*s).
//
// Jets are pre-rendered from a 3D model (tools/gen_sprites3d.py) into an atlas
// of view directions (azimuth 0..180 x elevation -82.5..82.5).  Each tick the
// direction to the camera is expressed in the jet's body frame, the nearest
// cell is shown (mirrored for negative azimuth) and the remaining roll around
// the view axis is done with Clutter's rotation_angle_z.
//
// Shot-down jets fall burning and explode on the ground; pilots eject and come
// down on parachutes.  v1 (flat top-down pixel art) is kept in v1_backup/.
//
// v3: tanks fight on the ground strip along the bottom edge.  The camera sits
// CAM_H above the ground, so farther tanks stand a little higher on screen.
// Hull and turret come from one atlas (row 0 hull, row 1 turret), so the
// turret turns on its own; a killed tank burns and may lose its turret.

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const TICK_MS = 33;

// sprite geometry (logical px) — must match gen_sprites3d.py
const CELL = 176;
const AZ_N = 25, AZ_STEP = Math.PI / 24;
const EL_N = 12, EL0 = -82.5 * Math.PI / 180, EL_STEP = Math.PI / 12;
const ATLAS_W = CELL * AZ_N, ATLAS_H = CELL * EL_N;
const BODY = 0.85 * CELL;          // world units per body-length unit
const BOOM = 128, BOOM_FRAMES = 8, BOOM_TICKS = 3;
const PUFF = 40;
const TCELL = 128;                 // tank atlas cell (must match gen_sprites3d.py)
const TBODY = 0.75 * TCELL;        // world units per tank body unit
const TYOFF = 0.16;                // tank model offset inside its cell
const TEL = 12 * Math.PI / 180;    // camera elevation the tanks were rendered at
const SPARK = 21;
const BIT = 12;
const SEAT = 28;
const CHUTE_W = 72, CHUTE_H = 96;

const TEAMS = ['wood', 'desert'];
const TEAM_NAMES = {wood: 'лес', desert: 'пустыня'};
const TRACER = {wood: '#ffa050', desert: '#fff27a'};

// tuning (world units are logical px at depth 0, multiplied by scale factor)
const FOCAL = 1000;
const DZ_MIN = -60, DZ_MAX = 1100;
const MAX_HP = 9;
const SPEED = 6.5;
const ROLL = 0.17;                 // rad/tick
const PULL = 0.068;                // rad/tick
const BULLET_SPEED = 24;
const BULLET_LIFE = 34;
const HIT_R = 40;
const GRAV = 0.2;
const CAM_H = 110;                 // camera height above the ground
const T_DZ_MIN = 30, T_DZ_MAX = 560;
const T_HP = 3;
const T_SPEED = 1.15;
const T_TURN = 0.028;
const T_TURRET = 0.032;
const SHELL_SPEED = 13;
const SHELL_G = 0.05;
const SHELL_LIFE = 140;

const DEFAULTS = {visible: true, aboveWindows: true, perTeam: 2, tanksPerTeam: 2};

const rand = (a, b) => a + Math.random() * (b - a);
const randi = (a, b) => Math.floor(rand(a, b + 1));
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const add = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const len = a => Math.hypot(a[0], a[1], a[2]);
const norm = a => {
    const l = len(a) || 1;
    return [a[0] / l, a[1] / l, a[2] / l];
};
const UP = [0, 1, 0];
const wrapA = a => Math.atan2(Math.sin(a), Math.cos(a));
const dirA = a => [Math.cos(a), 0, Math.sin(a)];

function sprite(dir, name, w, h) {
    const path = GLib.build_filenamev([dir, 'sprites', `${name}.png`]);
    return new St.Widget({
        reactive: false,
        style: `background-image: url("${path}"); width: ${w}px; height: ${h}px; background-size: ${w}px ${h}px;`,
    });
}

// keep `u` perpendicular to `f`, unit length
function ortho(f, u) {
    const r = sub(u, mul(f, dot(u, f)));
    return len(r) < 1e-6 ? norm(cross(f, [0, 0, 1])) : norm(r);
}

// rotate unit vector u (perpendicular to axis f) around f
function rotAround(f, u, a) {
    return add(mul(u, Math.cos(a)), cross(f, u), Math.sin(a));
}

// ------------------------------------------------------------------ jets

class Jet {
    constructor(world, team) {
        this.world = world;
        this.team = team;
        const sf = world.sf;
        this.size = CELL * sf;
        this.actor = new St.Widget({reactive: false, width: this.size, height: this.size, visible: false});
        this.actor.set_pivot_point(0.5, 0.5);
        this.flipper = new St.Widget({reactive: false, width: this.size, height: this.size, clip_to_allocation: true});
        this.flipper.set_pivot_point(0.5, 0.5);
        this.actor.add_child(this.flipper);
        // full-res atlas and a half-res one for far (small) jets
        this.lod = [
            sprite(world.dir, `jet_${team}`, ATLAS_W, ATLAS_H),
            sprite(world.dir, `jet_${team}_half`, ATLAS_W, ATLAS_H),
        ];
        this.lod.forEach(a => this.flipper.add_child(a));
        this.lod[1].hide();
        world.mid.add_child(this.actor);
        this.skill = rand(0.88, 1.12);
        this.state = 'dead';
        this.respawnT = 0;
        this.age = 0;
        this._cell = [-1, -1, 0, 0];
        this._rot = 0;
        this.depth = 0;
    }

    get alive() {
        return this.state === 'fly';
    }

    get vel() {
        return this.state === 'down' ? this.dv : mul(this.F, this.v);
    }

    spawn(side = null) {
        const w = this.world, sf = w.sf;
        const dz = rand(100, 850) * sf;
        const s = w.focal / (w.focal + dz);
        const halfW = w.W / 2 / s;
        side ??= randi(0, 1);
        const sx = side === 0 ? -1 : 1;
        this.p = [sx * (halfW + 80 * sf), rand(0.4, 0.8) * w.H / s, -dz];
        this.F = norm([-sx, rand(-0.08, 0.12), rand(-0.35, 0.35)]);
        this.U = ortho(this.F, UP);
        this.v = SPEED * sf;
        this.hp = MAX_HP;
        this.ai = 'attack';
        this.aiT = 0;
        this.target = null;
        this.cool = randi(10, 30);
        this.burst = randi(4, 8);
        this.state = 'fly';
        this.age = 0;
        this.actor.show();
    }

    _pickTarget(enemies) {
        let best = null, bd = Infinity;
        for (const e of enemies) {
            const d = len(sub(e.p, this.p));
            if (d < bd) {
                bd = d;
                best = e;
            }
        }
        if (this.target && this.target.alive) {
            const cd = len(sub(this.target.p, this.p));
            if (cd < bd * 1.5)
                return this.target;
        }
        return best;
    }

    _threatened(enemies) {
        const sf = this.world.sf;
        for (const e of enemies) {
            const to = sub(this.p, e.p);
            if (len(to) > 420 * sf)
                continue;
            const n = norm(to);
            if (dot(e.F, n) > 0.94 && dot(this.F, n) > 0.2)
                return true;
        }
        return false;
    }

    think() {
        const w = this.world, sf = w.sf;
        const enemies = w.jets.filter(j => j.alive && j.team !== this.team);
        this.target = enemies.length ? this._pickTarget(enemies) : null;
        const t = this.target;
        let D, aim = Infinity, dist = Infinity;

        if ((this.ai === 'evade' || this.ai === 'extend') && --this.aiT <= 0)
            this.ai = 'attack';

        if (this.ai === 'evade') {
            D = norm(add(this.F, this.evadeDir, 1.6));
        } else if (this.ai === 'extend') {
            D = this.F;
        } else if (t) {
            dist = len(sub(t.p, this.p));
            const lead = add(t.p, t.vel, dist / (BULLET_SPEED * sf));
            D = norm(sub(lead, this.p));
            aim = Math.acos(clamp(dot(D, this.F), -1, 1));
            if (this._threatened(enemies) && Math.random() < 0.05) {
                this.ai = 'evade';
                this.aiT = randi(25, 50);
                this.evadeDir = norm(cross(this.F, [rand(-1, 1), rand(-1, 1), rand(-1, 1)]));
            } else if (dist < 130 * sf && aim < 1.2) {
                this.ai = 'extend';
                this.aiT = randi(20, 35);
            }
        } else {
            // nobody to fight: lazy circles
            const r = norm(sub([0, w.H * 0.6, -500 * sf], this.p));
            D = norm(add(r, cross(UP, r), 0.9));
        }

        // don't ram anybody
        for (const o of w.jets) {
            if (o === this || o.state !== 'fly')
                continue;
            const away = sub(this.p, o.p);
            if (len(away) < 80 * sf)
                D = norm(add(D, norm(away), 0.9));
        }

        // stay inside the visible volume
        const dz = -this.p[2];
        const s = w.focal / (w.focal + dz);
        const halfW = w.W / 2 / s;
        const top = (w.H - 50 * sf - w.camH * (1 - s)) / s;
        const floor = 120 * sf / s;
        const midY = (top + floor) / 2;
        const midZ = (DZ_MIN + DZ_MAX) / 2 * sf;
        const nx = Math.abs(this.p[0]) / halfW;
        const ny = Math.abs(this.p[1] - midY) / ((top - floor) / 2);
        const nz = Math.abs(dz - midZ) / ((DZ_MAX - DZ_MIN) / 2 * sf);
        const out = Math.max(nx - 0.72, ny - 0.62, nz - 0.75, 0) / 0.28;
        if (out > 0) {
            const home = norm(sub([0, midY, -midZ], this.p));
            const k = Math.min(1, out);
            D = norm(add(mul(D, 1 - k), home, k * 1.2));
        }
        if (this.p[1] < floor * 1.3)
            D = norm(add(D, UP, 0.5 + 2 * (floor * 1.3 - this.p[1]) / floor));

        this._fly(D);

        const vt = SPEED * sf * this.skill *
            (this.ai === 'evade' ? 1.2 : this.ai === 'extend' ? 1.15 : 1) - this.F[1] * 1.5 * sf;
        this.v += (vt - this.v) * 0.05;

        // guns
        if (this.cool > 0)
            this.cool--;
        // no head-on passes: only shoot at somebody who isn't pointing back at us
        if (this.ai === 'attack' && t && dist < 560 * sf && aim < 0.09 && this.cool === 0 &&
            dot(this.F, t.F) > -0.3) {
            w.fire(this);
            if (--this.burst > 0) {
                this.cool = 3;
            } else {
                this.cool = randi(18, 35);
                this.burst = randi(4, 8);
            }
        }
    }

    // put the lift vector on the desired direction and pull
    _fly(D) {
        let F = this.F, U = this.U;
        const R = ROLL * this.skill * (this.ai === 'evade' ? 1.3 : 1);
        const P = PULL * this.skill * (this.ai === 'evade' ? 1.25 : 1);
        const c = clamp(dot(F, D), -1, 1);
        const E = sub(D, mul(F, c));
        const lvl = Math.abs(F[1]) < 0.97 ? ortho(F, UP) : U;
        let Ud, q;
        if (Math.acos(c) < 0.35) {
            // fine tracking: mostly wings level, bank a bit towards the side
            const lat = sub(E, mul(lvl, dot(E, lvl)));
            Ud = norm(add(lvl, lat, 5));
            q = clamp(dot(E, U) * 0.5, -P * 0.4, P);
            F = norm(add(F, E, 0.16));
            U = ortho(F, U);
        } else {
            Ud = len(E) > 1e-6 ? norm(E) : U;
            q = P * (dot(U, Ud) > 0.3 ? 1 : 0.3);
        }
        Ud = ortho(F, Ud);
        const phi = Math.atan2(dot(cross(U, Ud), F), dot(U, Ud));
        U = rotAround(F, U, clamp(phi, -R, R));
        const nF = add(mul(F, Math.cos(q)), U, Math.sin(q));
        const nU = sub(mul(U, Math.cos(q)), mul(F, Math.sin(q)));
        this.F = norm(nF);
        this.U = ortho(this.F, nU);
    }

    tick() {
        const w = this.world, sf = w.sf;
        if (this.state === 'dead') {
            if (--this.respawnT <= 0)
                this.spawn();
            return;
        }
        this.age++;
        if (this.state === 'fly') {
            this.think();
            this.p = add(this.p, this.F, this.v);
            if (this.hp <= MAX_HP / 2 && this.age % (this.hp <= 2 ? 2 : 3) === 0)
                w.fx.puff(this.tail(), 'smoke', this.hp <= 2 ? 1.2 : 0.9, 40);
            return;
        }
        // 'down': burning, spinning, falling
        this.dv[1] -= GRAV * sf;
        this.dv[0] *= 0.988;
        this.dv[2] *= 0.988;
        this.p = add(this.p, this.dv);
        this.F = norm(add(this.F, sub(norm(this.dv), this.F), 0.1));
        this.U = rotAround(this.F, ortho(this.F, this.U), this.spin);
        const tail = this.tail();
        w.fx.puff(tail, 'dark', 1.3, randi(40, 60), 0.5);
        if (this.age % 2 === 0)
            w.fx.puff(add(tail, this.F, 6 * sf), 'fire', 0.8, 8, 0);
        if (this.ejectT > 0 && --this.ejectT === 0)
            w.eject(this);
        if (this.p[1] <= 0)
            w.crash(this);
    }

    tail() {
        return add(this.p, this.F, -0.5 * BODY * this.world.sf);
    }

    nose() {
        return add(this.p, this.F, 0.5 * BODY * this.world.sf);
    }

    hit(by) {
        if (--this.hp <= 0)
            this.world.kill(this, by);
    }

    render() {
        if (this.state === 'dead')
            return;
        const w = this.world, sf = w.sf;
        const [sx, sy, s] = w.proj(this.p);
        this.depth = -this.p[2];
        const F = this.F, U = this.U, Z = cross(F, U);
        // direction to the camera (+z) in body coordinates
        const db = [F[2], U[2], Z[2]];
        const el = Math.asin(clamp(db[1], -1, 1));
        const az = Math.atan2(db[2], db[0]);
        const col = clamp(Math.round(Math.abs(az) / AZ_STEP), 0, AZ_N - 1);
        const row = clamp(Math.round((el - EL0) / EL_STEP), 0, EL_N - 1);
        const flip = az < 0 ? -1 : 1;
        if (Math.abs(db[1]) < 0.999) {
            // the sprite camera's "up" (body frame) mapped to the world -> roll on screen
            const fs = mul(db, -1);
            const rs = norm(cross(fs, UP));
            const us = cross(rs, fs);
            const Wd = add(add(mul(F, us[0]), U, us[1]), Z, us[2]);
            this._rot = Math.atan2(Wd[0], Wd[1]) * 180 / Math.PI;
        }
        const lod = s < 0.62 ? 1 : 0;
        const c = this._cell;
        if (c[0] !== col || c[1] !== row || c[3] !== lod) {
            this.lod[lod].set_position(-col * CELL * sf, -row * CELL * sf);
            this.lod[lod].show();
            this.lod[1 - lod].hide();
            c[0] = col;
            c[1] = row;
            c[3] = lod;
        }
        if (c[2] !== flip) {
            this.flipper.scale_x = flip;
            c[2] = flip;
        }
        this.actor.set_position(Math.round(sx - this.size / 2), Math.round(sy - this.size / 2));
        this.actor.set_scale(s, s);
        this.actor.rotation_angle_z = this._rot;
    }

    destroy() {
        this.actor.destroy();
    }
}


// ----------------------------------------------------------------- tanks

class Tank {
    constructor(world, team) {
        this.world = world;
        this.team = team;
        const sf = world.sf;
        this.size = TCELL * sf;
        const path = GLib.build_filenamev([world.dir, 'sprites', `tank_${team}.png`]);
        const aw = TCELL * AZ_N, ah = TCELL * 2;
        const style = `background-image: url("${path}"); width: ${aw}px; height: ${ah}px; background-size: ${aw}px ${ah}px;`;
        const cell = () => {
            const w = new St.Widget({reactive: false, width: this.size, height: this.size});
            w.set_pivot_point(0.5, 0.5);
            return w;
        };
        this.actor = cell();
        this.actor.hide();
        this.hullFlip = cell();
        this.hullFlip.clip_to_allocation = true;
        this.hullAtlas = new St.Widget({reactive: false, style});
        this.hullFlip.add_child(this.hullAtlas);
        this.turFrame = cell();
        this.turFlip = cell();
        this.turFlip.clip_to_allocation = true;
        this.turAtlas = new St.Widget({reactive: false, style});
        this.turFlip.add_child(this.turAtlas);
        this.turFrame.add_child(this.turFlip);
        this.actor.add_child(this.hullFlip);
        this.actor.add_child(this.turFrame);
        world.mid.add_child(this.actor);
        this.skill = rand(0.85, 1.15);
        this.state = 'gone';
        this.respawnT = 0;
        this.depth = 0;
        this._cells = [-1, 0, -1, 0];
        this._dark = null;
    }

    get alive() {
        return this.state === 'fight';
    }

    get vel() {
        return this.alive ? mul(dirA(this.a), this.v) : [0, 0, 0];
    }

    // centre of mass (used for hits)
    get centre() {
        return add(this.p, UP, 0.17 * TBODY * this.world.sf);
    }

    bounds(dz) {
        const w = this.world;
        const s = w.focal / (w.focal + dz);
        return w.W / 2 / s - 70 * w.sf;
    }

    spawn() {
        const w = this.world, sf = w.sf;
        const dz = rand(T_DZ_MIN + 20, T_DZ_MAX - 40) * sf;
        const side = this.team === 'wood' ? -1 : 1;
        this.p = [side * (this.bounds(dz) + 150 * sf), 0, -dz];
        this.a = side < 0 ? rand(-0.3, 0.3) : Math.PI + rand(-0.3, 0.3);
        this.ta = this.a;
        this.v = 0;
        this.hp = T_HP;
        this.reload = randi(40, 90);
        this.wp = [side * rand(0.1, 0.6) * this.bounds(dz), 0, this.p[2]];
        this.wpT = randi(150, 250);
        this.target = null;
        this.kick = 0;
        this.tOff = [0, 0, 0];
        this.tVel = null;
        this.tSpin = 0;
        this.tSpinA = 0;
        this.age = 0;
        this.state = 'fight';
        this._setDark(false);
        this.actor.opacity = 255;
        this.turFrame.rotation_angle_z = 0;
        this.actor.show();
    }

    _setDark(on) {
        if (on && !this._dark) {
            this._dark = new Clutter.BrightnessContrastEffect();
            this._dark.set_brightness(-0.42);
            this._dark.set_contrast(-0.15);
            this.actor.add_effect(this._dark);
        } else if (!on && this._dark) {
            this.actor.remove_effect(this._dark);
            this._dark = null;
        }
    }

    _pickWaypoint(t) {
        const w = this.world, sf = w.sf;
        let p;
        if (t) {
            // keep a fighting distance from the target, from a random angle
            const from = Math.atan2(this.p[2] - t.p[2], this.p[0] - t.p[0]) + rand(-0.9, 0.9);
            const R = rand(260, 480) * sf;
            p = add(t.p, dirA(from), R);
        } else {
            p = [rand(-0.7, 0.7) * w.W / 2, 0, -rand(T_DZ_MIN, T_DZ_MAX) * sf];
        }
        const dz = clamp(-p[2], T_DZ_MIN * sf, T_DZ_MAX * sf);
        const hw = this.bounds(dz) * 0.92;
        this.wp = [clamp(p[0], -hw, hw), 0, -dz];
        this.wpT = randi(140, 260);
    }

    think() {
        const w = this.world, sf = w.sf;
        const enemies = w.tanks.filter(o => o.alive && o.team !== this.team);
        let t = null, bd = Infinity;
        for (const e of enemies) {
            const d = len(sub(e.p, this.p)) * (e === this.target ? 0.75 : 1);
            if (d < bd) {
                bd = d;
                t = e;
            }
        }
        this.target = t;

        // --- drive
        if (--this.wpT <= 0 || len(sub(this.wp, this.p)) < 30 * sf)
            this._pickWaypoint(t);
        let to = sub(this.wp, this.p);
        // keep clear of other tanks and wrecks
        for (const o of w.tanks) {
            if (o === this || o.state === 'gone')
                continue;
            const away = sub(this.p, o.p);
            const d = len(away);
            if (d < 120 * sf && d > 0)
                to = add(to, norm(away), 140 * sf * (1 - d / (120 * sf)) * 2);
        }
        const dist = len(to);
        let speed = 0;
        if (dist > 25 * sf) {
            const want = Math.atan2(to[2], to[0]);
            const err = wrapA(want - this.a);
            this.a = wrapA(this.a + clamp(err, -T_TURN, T_TURN) * this.skill);
            speed = T_SPEED * sf * this.skill * Math.max(0, Math.cos(err)) ** 2 * Math.min(1, dist / (90 * sf));
        }
        this.v += (speed - this.v) * 0.06;

        // --- turret & gun
        if (this.reload > 0)
            this.reload--;
        let aimErr = Infinity, tdist = Infinity;
        if (t) {
            tdist = len(sub(t.p, this.p));
            const lead = add(t.p, t.vel, tdist / (SHELL_SPEED * sf));
            const want = Math.atan2(lead[2] - this.p[2], lead[0] - this.p[0]);
            aimErr = wrapA(want - this.ta);
            this.ta = wrapA(this.ta + clamp(aimErr, -T_TURRET, T_TURRET) * this.skill);
        } else {
            this.ta = wrapA(this.ta + clamp(wrapA(this.a - this.ta), -T_TURRET, T_TURRET) * 0.5);
        }
        const onScreen = Math.abs(this.p[0]) < this.bounds(-this.p[2]) + 40 * sf;
        if (t && this.reload === 0 && Math.abs(aimErr) < 0.035 && tdist < 1300 * sf && onScreen) {
            w.fireShell(this, t);
            this.reload = randi(80, 150);
            this.kick = 1;
        }
    }

    muzzle() {
        const sf = this.world.sf;
        return add(add(this.p, dirA(this.ta), 0.63 * TBODY * sf), UP, 0.255 * TBODY * sf);
    }

    tick() {
        const w = this.world, sf = w.sf;
        if (this.state === 'gone') {
            if (--this.respawnT <= 0)
                this.spawn();
            return;
        }
        this.age++;
        this.kick *= 0.82;
        if (this.state === 'fight') {
            this.think();
            this.p = add(this.p, dirA(this.a), this.v);
            if (this.v > 0.35 * sf && this.age % 5 === 0) {
                const F = dirA(this.a), Z = [-F[2], 0, F[0]];
                const sd = Math.random() < 0.5 ? 1 : -1;
                w.fx.puff(add(add(this.p, F, -0.45 * TBODY * sf), Z, sd * 0.22 * TBODY * sf), 'dust',
                    0.7, randi(30, 45), 0.12);
            }
            if (this.hp < T_HP && this.age % 4 === 0)
                w.fx.puff(this.centre, 'dark', 0.8, 40, 0.5);
            return;
        }
        // 'wreck': burning, the turret may be flying
        this.wreckT--;
        if (this.tVel) {
            this.tVel[1] -= GRAV * sf;
            this.tOff = add(this.tOff, this.tVel);
            this.tSpinA += this.tSpin;
            if (this.age % 2 === 0)
                w.fx.puff(add(this.p, this.tOff, 1), 'dark', 0.6, 30, 0.2);
            if (this.tOff[1] <= 0) {
                this.tOff[1] = 0;
                this.tVel = null;
                w.fx.puff(add(this.p, this.tOff), 'dust', 1.2, 40, 0.2);
            }
        }
        if (this.wreckT < 40)
            this.actor.opacity = Math.round(255 * Math.max(0, this.wreckT) / 40);
        if (this.wreckT <= 0) {
            this.state = 'gone';
            this.actor.hide();
            this.respawnT = randi(60, 160);
        }
    }

    hit(by, dmg = 1) {
        if (!this.alive)
            return;
        this.hp -= dmg;
        if (this.hp <= 0)
            this.world.killTank(this, by);
    }

    _az(dirAngle) {
        // horizontal direction to the camera in the tank's frame
        const w = this.world;
        const cx = -this.p[0], cz = w.focal - this.p[2];
        const F = dirA(dirAngle);
        return Math.atan2(F[0] * cz - F[2] * cx, F[0] * cx + F[2] * cz);
    }

    render() {
        if (this.state === 'gone')
            return;
        const w = this.world, sf = w.sf;
        this.depth = -this.p[2];
        const [sx, sy, s] = w.proj(add(this.p, UP, TYOFF * TBODY * sf * Math.cos(TEL)));
        const c = this._cells;
        const ah = this._az(this.a);
        const hc = clamp(Math.round(Math.abs(ah) / AZ_STEP), 0, AZ_N - 1);
        const hf = ah < 0 ? -1 : 1;
        if (c[0] !== hc) {
            this.hullAtlas.set_position(-hc * TCELL * sf, 0);
            c[0] = hc;
        }
        if (c[1] !== hf) {
            this.hullFlip.scale_x = hf;
            c[1] = hf;
        }
        const at = this._az(this.ta);
        const tc = clamp(Math.round(Math.abs(at) / AZ_STEP), 0, AZ_N - 1);
        const tf = at < 0 ? -1 : 1;
        if (c[2] !== tc) {
            this.turAtlas.set_position(-tc * TCELL * sf, -TCELL * sf);
            c[2] = tc;
        }
        if (c[3] !== tf) {
            this.turFlip.scale_x = tf;
            c[3] = tf;
        }
        // recoil: the turret jerks back along the gun for a moment
        const T = dirA(this.ta);
        const kx = -T[0] * this.kick * 5 * sf;
        this.turFrame.set_position(Math.round(this.tOff[0] + kx), Math.round(-this.tOff[1]));
        this.turFrame.rotation_angle_z = this.tSpinA;
        this.actor.set_position(Math.round(sx - this.size / 2), Math.round(sy - this.size / 2));
        this.actor.set_scale(s, s);
    }

    destroy() {
        this.actor.destroy();
    }
}

// ---------------------------------------------------------------- pilots

class Pilot {
    constructor(world, jet) {
        this.world = world;
        const sf = world.sf;
        this.seat = sprite(world.dir, 'seat', SEAT, SEAT);
        this.seat.set_pivot_point(0.5, 0.5);
        this.chute = sprite(world.dir, `chute_${jet.team}`, CHUTE_W, CHUTE_H);
        this.chute.set_pivot_point(0.5, 0.86);
        this.chute.hide();
        this.actor = new St.Widget({reactive: false});
        this.actor.add_child(this.seat);
        this.actor.add_child(this.chute);
        world.mid.add_child(this.actor);
        // blasted out along the jet's "up", but always mostly upwards
        const dir = norm(add(jet.U, UP, jet.U[1] < 0 ? 1.6 : 0.6));
        this.p = add(jet.p, jet.F, 0.18 * BODY * sf);
        this.v = add(mul(jet.vel, 0.45), dir, 4 * sf);
        this.dir = dir;
        this.spinA = 0;
        this.spin = rand(-14, 14);
        this.t = 0;
        this.phase = 'seat';
        this.wind = rand(-0.4, 0.4) * sf;
        this.swayP = rand(0, 6);
        this.done = false;
        // the canopy glass goes first
        world.fx.bit(this.p, add(this.v, [rand(-2, 2), 2, rand(-2, 2)], sf), 'shard');
    }

    get depth() {
        return -this.p[2];
    }

    tick() {
        const w = this.world, sf = w.sf;
        this.t++;
        if (this.phase === 'seat') {
            if (this.t < 9) {
                // seat rocket
                this.v = add(this.v, this.dir, 1.3 * sf);
                w.fx.puff(this.p, 'fire', 0.5, 6, 0);
                w.fx.puff(this.p, 'smoke', 0.6, 26, 0.2);
            }
            this.v[1] -= GRAV * sf;
            this.v = mul(this.v, 0.97);
            this.spinA += this.spin;
            if (this.t > 26) {
                this.phase = 'chute';
                this.t = 0;
                this.seat.hide();
                this.chute.show();
                // the empty seat tumbles down on its own
                w.fx.bit(this.p, add(this.v, [rand(-1, 1), -1, 0], sf), 'debris', 1.8);
            }
        } else if (this.phase === 'chute') {
            this.v[1] += (-1.15 * sf - this.v[1]) * 0.06;
            this.v[0] += (this.wind - this.v[0]) * 0.03;
            this.v[2] *= 0.95;
            if (this.p[1] <= 0) {
                this.p[1] = 0;
                this.phase = 'landed';
                this.t = 0;
                this.fall = this.wind >= 0 ? 1 : -1;
            }
        } else if (this.t > 60) {
            this.done = true;
            return;
        }
        if (this.phase !== 'landed')
            this.p = add(this.p, this.v);
    }

    render() {
        const w = this.world, sf = w.sf;
        const [sx, sy, s] = w.proj(this.p);
        if (this.phase === 'seat') {
            const sz = SEAT * sf;
            this.seat.set_position(Math.round(sx - sz / 2), Math.round(sy - sz / 2));
            this.seat.set_scale(s, s);
            this.seat.rotation_angle_z = this.spinA;
            return;
        }
        const W = CHUTE_W * sf, H = CHUTE_H * sf;
        this.chute.set_position(Math.round(sx - W / 2), Math.round(sy - H * 0.86));
        if (this.phase === 'chute') {
            const k = Math.min(1, this.t / 14);
            const e = 1 - (1 - k) ** 3;
            this.chute.set_scale(s * (0.15 + 0.85 * e), s * (0.45 + 0.55 * e));
            this.chute.rotation_angle_z = Math.sin(this.t * 0.06 + this.swayP) * 9 * e - this.v[0] / sf * 4;
        } else {
            // landed: the canopy collapses sideways and fades out
            const k = Math.min(1, this.t / 30);
            this.chute.set_scale(s * (1 - 0.3 * k), s * (1 - 0.6 * k));
            this.chute.rotation_angle_z = this.fall * 80 * k;
            this.chute.opacity = Math.round(255 * (1 - Math.max(0, (this.t - 25) / 35)));
        }
    }

    destroy() {
        this.actor.destroy();
    }
}

// --------------------------------------------------------------- effects

class Effects {
    constructor(world) {
        this.world = world;
        this._puffs = {smoke: [], dark: [], fire: [], dust: []};
        this._sparks = [];
        this._booms = [];
        this._bits = [];
        this._sites = [];
    }

    _get(pool, make, cap) {
        let it = pool.find(p => p.life <= 0);
        if (!it) {
            if (pool.length >= cap)
                return null;
            it = make();
            pool.push(it);
        }
        return it;
    }

    _simple(name, size, parent) {
        const actor = sprite(this.world.dir, name, size, size);
        actor.set_pivot_point(0.5, 0.5);
        actor.hide();
        parent.add_child(actor);
        return {actor, life: 0, age: 0, size: size * this.world.sf};
    }

    puff(p, kind, scale, life, rise = 0.3) {
        const it = this._get(this._puffs[kind], () => this._simple(`puff_${kind}`, PUFF, this.world.back),
            kind === 'fire' ? 60 : 170);
        if (!it)
            return;
        const j = 3 * this.world.sf;
        Object.assign(it, {
            p: [p[0] + rand(-j, j), p[1] + rand(-j, j), p[2] + rand(-j, j)],
            life, max: life, age: 0, s: scale, rise: rise * this.world.sf,
        });
        it.actor.rotation_angle_z = rand(0, 360);
        it.actor.show();
    }

    spark(p) {
        const it = this._get(this._sparks, () => this._simple('spark', SPARK, this.world.front), 40);
        if (!it)
            return;
        Object.assign(it, {p, life: 5, max: 5});
        it.actor.rotation_angle_z = rand(0, 90);
        it.actor.show();
    }

    // small tumbling piece: debris, canopy glass, the empty seat
    bit(p, v, name = 'debris', scale = 1) {
        const it = this._get(this._bits, () => {
            const sf = this.world.sf;
            const actor = new St.Widget({reactive: false, width: BIT * sf, height: BIT * sf, visible: false});
            actor.set_pivot_point(0.5, 0.5);
            const kids = {};
            for (const n of ['debris', 'shard']) {
                kids[n] = sprite(this.world.dir, n, BIT, BIT);
                actor.add_child(kids[n]);
            }
            this.world.back.add_child(actor);
            return {actor, kids, life: 0};
        }, 60);
        if (!it)
            return;
        for (const n in it.kids)
            it.kids[n].visible = n === name;
        Object.assign(it, {
            p: [...p], v: [...v], life: 200, a: rand(0, 360), spin: rand(-25, 25), s: scale,
            trail: name === 'debris' && scale < 1.5 && Math.random() < 0.35,
        });
        it.actor.show();
    }

    boom(p, scale, v = [0, 0, 0], ground = false) {
        const it = this._get(this._booms, () => {
            const sf = this.world.sf;
            const actor = new St.Widget({reactive: false, width: BOOM * sf, height: BOOM * sf, visible: false});
            const frames = [];
            for (let i = 0; i < BOOM_FRAMES; i++) {
                const f = sprite(this.world.dir, `boom_${i}`, BOOM, BOOM);
                f.visible = false;
                actor.add_child(f);
                frames.push(f);
            }
            this.world.mid.add_child(actor);
            return {actor, frames, life: 0, shown: -1};
        }, 16);
        if (!it)
            return;
        Object.assign(it, {p: [...p], v: mul(v, 0.25), life: BOOM_FRAMES * BOOM_TICKS, age: 0, s: scale, ground});
        it.actor.set_pivot_point(0.5, ground ? 0.78 : 0.5);
        it.actor.show();
    }

    // a shell hitting the dirt
    dirt(p) {
        const sf = this.world.sf;
        this.boom(p, 0.35, [0, 0, 0], true);
        for (let k = 0; k < 4; k++)
            this.puff(add(p, [rand(-12, 12) * sf, rand(0, 10) * sf, 0]), 'dust', 1.4, randi(40, 60), 0.35);
        for (let k = 0; k < 4; k++)
            this.bit(add(p, [0, 4 * sf, 0]), [rand(-2.5, 2.5) * sf, rand(3, 6) * sf, rand(-2, 2) * sf], 'debris', 0.6);
    }

    groundBoom(p, v) {
        const sf = this.world.sf;
        this.boom(p, 2.0, [0, 0, 0], true);
        this.boom(add(p, [rand(-30, 30) * sf, 25 * sf, 0]), 1.3, [0, 0.8 * sf, 0], true);
        for (let k = 0; k < 12; k++) {
            this.bit(add(p, [0, 10 * sf, 0]),
                [rand(-5, 5) * sf + v[0] * 0.2, rand(4, 11) * sf, rand(-4, 4) * sf], 'debris', rand(0.7, 1.3));
        }
        for (let k = 0; k < 8; k++)
            this.puff(add(p, [rand(-40, 40) * sf, rand(0, 40) * sf, 0]), 'dark', 2.2, randi(50, 80), 0.8);
        // burning wreck: a column of smoke for a few seconds
        this._sites.push({p: [...p], life: 110, max: 110});
    }

    // a burning tank wreck
    wreckFire(p, life) {
        this._sites.push({p: [...p], life, max: life});
    }

    tick() {
        const w = this.world, sf = w.sf;
        for (const s of this._sites) {
            s.life--;
            if (s.life % 2 === 0)
                this.puff(add(s.p, [rand(-14, 14) * sf, 4 * sf, 0]), 'dark', 2.2 * s.life / s.max + 0.9, randi(60, 90), 1.1);
            if (s.life % 4 === 0 && s.life > 30)
                this.puff(add(s.p, [rand(-10, 10) * sf, 6 * sf, 0]), 'fire', 0.9, 10, 0.6);
        }
        this._sites = this._sites.filter(s => s.life > 0);

        for (const kind in this._puffs) {
            for (const it of this._puffs[kind]) {
                if (it.life <= 0)
                    continue;
                it.age++;
                if (--it.life <= 0) {
                    it.actor.hide();
                    continue;
                }
                const k = it.age / it.max;
                it.p[1] += it.rise;
                const [sx, sy, s] = w.proj(it.p);
                it.actor.set_position(Math.round(sx - it.size / 2), Math.round(sy - it.size / 2));
                const g = it.s * s * (kind === 'fire' ? 1 - 0.5 * k : 0.5 + 1.3 * k);
                it.actor.set_scale(g, g);
                it.actor.opacity = Math.round((kind === 'fire' ? 255 : 220) * (1 - k));
            }
        }
        for (const it of this._sparks) {
            if (it.life <= 0)
                continue;
            if (--it.life <= 0) {
                it.actor.hide();
                continue;
            }
            const [sx, sy, s] = w.proj(it.p);
            it.actor.set_position(Math.round(sx - it.size / 2), Math.round(sy - it.size / 2));
            it.actor.set_scale(s, s);
            it.actor.opacity = Math.round(255 * it.life / it.max);
        }
        for (const it of this._bits) {
            if (it.life <= 0)
                continue;
            it.v[1] -= GRAV * sf;
            it.p = add(it.p, it.v);
            it.a += it.spin;
            if (it.trail)
                this.puff(it.p, 'dark', 0.3, 12, 0.1);
            if (--it.life <= 0 || it.p[1] < 0) {
                it.life = 0;
                it.actor.hide();
                continue;
            }
            const [sx, sy, s] = w.proj(it.p);
            const sz = BIT * sf;
            it.actor.set_position(Math.round(sx - sz / 2), Math.round(sy - sz / 2));
            it.actor.set_scale(s * it.s, s * it.s);
            it.actor.rotation_angle_z = it.a;
        }
        for (const it of this._booms) {
            if (it.life <= 0)
                continue;
            it.age++;
            it.p = add(it.p, it.v);
            if (--it.life <= 0) {
                it.actor.hide();
                if (it.shown >= 0)
                    it.frames[it.shown].hide();
                it.shown = -1;
                continue;
            }
            const f = Math.min(BOOM_FRAMES - 1, Math.floor(it.age / BOOM_TICKS));
            if (f !== it.shown) {
                if (it.shown >= 0)
                    it.frames[it.shown].hide();
                it.frames[f].show();
                it.shown = f;
            }
            const [sx, sy, s] = w.proj(it.p);
            const sz = BOOM * sf;
            it.actor.set_position(Math.round(sx - sz / 2), Math.round(sy - sz * (it.ground ? 0.78 : 0.5)));
            it.actor.set_scale(s * it.s, s * it.s);
        }
    }

    // fireballs take part in depth sorting with the jets
    sortables() {
        return this._booms.filter(b => b.life > 0).map(b => ({actor: b.actor, depth: -b.p[2] - 1}));
    }

    clear() {
        for (const kind in this._puffs) {
            for (const it of this._puffs[kind]) {
                it.life = 0;
                it.actor.hide();
            }
        }
        for (const it of [...this._sparks, ...this._booms, ...this._bits]) {
            it.life = 0;
            it.actor.hide();
        }
        this._sites = [];
    }
}

// ----------------------------------------------------------------- world

class World {
    constructor(dir, perTeam, tanksPerTeam, onScore) {
        this.dir = dir;
        this.sf = St.ThemeContext.get_for_stage(global.stage).scale_factor;
        this.focal = FOCAL * this.sf;
        this.camH = CAM_H * this.sf;
        this.onScore = onScore;
        this.layer = new St.Widget({reactive: false});
        // back: smoke & debris, mid: depth-sorted jets/pilots/fireballs, front: bullets & sparks
        this.back = new St.Widget({reactive: false});
        this.mid = new St.Widget({reactive: false});
        this.front = new St.Widget({reactive: false});
        this.layer.add_child(this.back);
        this.layer.add_child(this.mid);
        this.layer.add_child(this.front);
        this.layer.connect('destroy', () => {
            this.dead = true;
        });
        this.dead = false;
        this.score = {wood: 0, desert: 0};
        this.tankScore = {wood: 0, desert: 0};
        this.fx = new Effects(this);
        this.tanks = [];
        this.shells = [];
        this.bullets = [];
        this.jets = [];
        this.pilots = [];
        this._order = [];
        this.updateBounds();
        this.setPerTeam(perTeam);
        this.setTanks(tanksPerTeam);
    }

    updateBounds() {
        const lm = Main.layoutManager;
        const was = lm.monitors.map((_m, i) => lm.getWorkAreaForMonitor(i));
        const x0 = Math.min(...was.map(r => r.x));
        const y0 = Math.min(...was.map(r => r.y));
        const x1 = Math.max(...was.map(r => r.x + r.width));
        const y1 = Math.max(...was.map(r => r.y + r.height));
        this.cx = (x0 + x1) / 2;
        this.gy = y1;
        this.W = x1 - x0;
        this.H = y1 - y0;
    }

    proj(p) {
        const s = this.focal / (this.focal - p[2]);
        return [this.cx + p[0] * s, this.gy - this.camH * (1 - s) - p[1] * s, s];
    }

    setPerTeam(n) {
        this.jets.forEach(j => j.destroy());
        this.jets = [];
        this.pilots.forEach(p => p.destroy());
        this.pilots = [];
        this.bullets.forEach(b => {
            b.life = 0;
            b.actor.hide();
        });
        this.fx.clear();
        this._order = [];
        for (const team of TEAMS) {
            for (let i = 0; i < n; i++) {
                const j = new Jet(this, team);
                j.spawn(team === 'wood' ? 0 : 1); // teams start on opposite sides
                this.jets.push(j);
            }
        }
    }

    setTanks(n) {
        this.tanks.forEach(t => t.destroy());
        this.tanks = [];
        this.shells.forEach(b => {
            b.life = 0;
            b.actor.hide();
        });
        this._order = [];
        for (const team of TEAMS) {
            for (let i = 0; i < n; i++) {
                const t = new Tank(this, team);
                t.spawn();
                // the first wave starts on screen already
                t.p[0] = (team === 'wood' ? -1 : 1) * rand(0.45, 0.9) * t.bounds(-t.p[2]);
                this.tanks.push(t);
            }
        }
    }

    reset() {
        this.score = {wood: 0, desert: 0};
        this.tankScore = {wood: 0, desert: 0};
        this.onScore?.(this.score, this.tankScore);
        this.setPerTeam(this.jets.length / 2);
        this.setTanks(this.tanks.length / 2);
    }

    fireShell(t, target) {
        const sf = this.sf;
        let b = this.shells.find(x => x.life <= 0);
        if (!b) {
            if (this.shells.length >= 40)
                return;
            const actor = new St.Widget({
                reactive: false, visible: false,
                style: 'background-color: #fff3b0; border-radius: 2px; box-shadow: 0 0 4px #ff9a30;',
            });
            actor.set_size(16 * sf, 4 * sf);
            actor.set_pivot_point(0.5, 0.5);
            this.front.add_child(actor);
            b = {actor};
            this.shells.push(b);
        }
        const m = t.muzzle();
        const tc = target.centre;
        const dist = Math.hypot(tc[0] - m[0], tc[2] - m[2]);
        const vh = SHELL_SPEED * sf;
        const time = dist / vh * rand(0.94, 1.06);
        const ang = t.ta + rand(-0.03, 0.03) * (0.6 + dist / (700 * sf));
        const g = SHELL_G * sf;
        const vy = (tc[1] - m[1]) / time + 0.5 * g * time;
        Object.assign(b, {p: m, v: add(mul(dirA(ang), vh), UP, vy), life: SHELL_LIFE, owner: t});
        b.actor.show();
        // muzzle blast
        const F = dirA(t.ta);
        this.fx.puff(add(m, F, 6 * sf), 'fire', 1.0, 6, 0);
        this.fx.puff(add(m, F, 14 * sf), 'fire', 0.7, 5, 0);
        for (let k = 0; k < 4; k++)
            this.fx.puff(add(m, F, rand(4, 26) * sf), 'smoke', rand(0.6, 1.1), randi(25, 40), 0.25);
        this.fx.puff(add(t.p, F, -10 * sf), 'dust', 1.4, 40, 0.2);
    }

    killTank(t, by) {
        const sf = this.sf;
        t.state = 'wreck';
        t.v = 0;
        t.wreckT = randi(330, 420);
        t._setDark(true);
        const c = t.centre;
        this.fx.boom(add(c, UP, 6 * sf), 1.5, [0, 0, 0], true);
        this.fx.boom(add(c, [rand(-20, 20) * sf, 30 * sf, 0]), 0.9, [0, 0.8 * sf, 0]);
        for (let k = 0; k < 8; k++)
            this.fx.bit(c, [rand(-5, 5) * sf, rand(4, 10) * sf, rand(-4, 4) * sf], 'debris', rand(0.7, 1.4));
        for (let k = 0; k < 5; k++)
            this.fx.puff(add(c, [rand(-30, 30) * sf, rand(0, 30) * sf, 0]), 'dark', 2.0, randi(50, 80), 0.8);
        this.fx.wreckFire(c, t.wreckT - 40);
        // ammo cook-off: the turret is thrown into the air
        if (Math.random() < 0.6) {
            t.tVel = [rand(-2.5, 2.5) * sf, rand(7, 11) * sf, 0];
            t.tSpin = rand(-14, 14);
        }
        if (by && by.team !== t.team) {
            this.tankScore[by.team]++;
            this.onScore?.(this.score, this.tankScore);
        }
    }


    fire(j) {
        const sf = this.sf;
        let b = this.bullets.find(x => x.life <= 0);
        if (!b) {
            if (this.bullets.length >= 140)
                return;
            const actor = new St.Widget({reactive: false, visible: false});
            actor.set_size(14 * sf, 3 * sf);
            actor.set_pivot_point(0.5, 0.5);
            this.front.add_child(actor);
            b = {actor, team: null};
            this.bullets.push(b);
        }
        const dir = norm(add(j.F, [rand(-1, 1), rand(-1, 1), rand(-1, 1)], 0.035));
        Object.assign(b, {
            p: j.nose(),
            v: add(mul(dir, BULLET_SPEED * sf), j.vel, 0.6),
            life: BULLET_LIFE,
            owner: j,
        });
        if (b.team !== j.team) {
            b.actor.style = `background-color: ${TRACER[j.team]}; border-radius: 2px;`;
            b.team = j.team;
        }
        b.actor.show();
    }

    kill(j, by) {
        const sf = this.sf;
        j.state = 'down';
        j.dv = mul(j.F, j.v);
        j.spin = rand(0.08, 0.22) * (Math.random() < 0.5 ? -1 : 1);
        j.ejectT = Math.random() < 0.92 ? randi(6, 16) : -1;
        this.fx.boom(j.p, 0.55, j.dv);
        for (let k = 0; k < 4; k++)
            this.fx.bit(j.p, add(j.dv, [rand(-4, 4), rand(-1, 5), rand(-4, 4)], sf * 0.8), 'debris', 0.8);
        if (by && by.team !== j.team) {
            this.score[by.team]++;
            this.onScore?.(this.score, this.tankScore);
        }
    }

    eject(j) {
        if (this.pilots.length < 16)
            this.pilots.push(new Pilot(this, j));
    }

    crash(j) {
        this.fx.groundBoom([j.p[0], 0, j.p[2]], j.dv);
        // a jet falling onto a tank takes it out
        for (const t of this.tanks) {
            const d = Math.hypot(t.p[0] - j.p[0], t.p[2] - j.p[2]);
            if (t.alive && d < 110 * this.sf)
                t.hit(null, d < 60 * this.sf ? T_HP : 2);
        }
        j.state = 'dead';
        j.actor.hide();
        j.respawnT = randi(70, 130);
    }

    tick() {
        for (const j of this.jets)
            j.tick();

        const sf = this.sf;
        const hr = HIT_R * sf;
        for (const b of this.bullets) {
            if (b.life <= 0)
                continue;
            b.p = add(b.p, b.v);
            let gone = --b.life <= 0 || b.p[1] < 0;
            if (!gone) {
                for (const j of this.jets) {
                    if (!j.alive || j.team === b.owner.team)
                        continue;
                    if (len(sub(j.p, b.p)) < hr) {
                        this.fx.spark(b.p);
                        j.hit(b.owner);
                        gone = true;
                        break;
                    }
                }
            }
            if (gone) {
                b.life = 0;
                b.actor.hide();
                continue;
            }
            const [sx, sy, s] = this.proj(b.p);
            const svx = b.v[0], svy = -b.v[1];
            const k = Math.max(0.25, Math.hypot(svx, svy) / (BULLET_SPEED * sf));
            b.actor.set_position(Math.round(sx - 7 * sf), Math.round(sy - 1.5 * sf));
            b.actor.set_scale(s * k, s);
            b.actor.rotation_angle_z = Math.atan2(svy, svx) * 180 / Math.PI;
        }

        for (const t of this.tanks)
            t.tick();
        this._tickShells();

        for (const p of this.pilots)
            p.tick();
        this.pilots = this.pilots.filter(p => {
            if (p.done)
                p.destroy();
            return !p.done;
        });

        this.fx.tick();
        for (const j of this.jets)
            j.render();
        for (const t of this.tanks)
            t.render();
        for (const p of this.pilots)
            p.render();
        this._sort();
    }

    _tickShells() {
        const sf = this.sf;
        const hr = 0.36 * TBODY * sf;
        const g = SHELL_G * sf;
        for (const b of this.shells) {
            if (b.life <= 0)
                continue;
            b.v[1] -= g;
            b.p = add(b.p, b.v);
            let gone = --b.life <= 0;
            for (const t of this.tanks) {
                if (gone)
                    break;
                if (!t.alive || t.team === b.owner.team)
                    continue;
                const c = t.centre;
                if (Math.hypot(c[0] - b.p[0], c[2] - b.p[2]) < hr && b.p[1] < 0.42 * TBODY * sf) {
                    this.fx.spark(b.p);
                    this.fx.spark(add(b.p, [4 * sf, 3 * sf, 0]));
                    this.fx.boom(b.p, 0.45, [0, 0, 0]);
                    this.fx.puff(b.p, 'dark', 1.0, 40, 0.4);
                    t.hit(b.owner);
                    gone = true;
                }
            }
            if (!gone && b.p[1] <= 0) {
                this.fx.dirt([b.p[0], 0, b.p[2]]);
                gone = true;
            }
            if (gone) {
                b.life = 0;
                b.actor.hide();
                continue;
            }
            const [sx, sy, s] = this.proj(b.p);
            const [nx, ny] = this.proj(add(b.p, b.v));
            const svx = nx - sx, svy = ny - sy;
            const k = clamp(Math.hypot(svx, svy) / (SHELL_SPEED * sf), 0.3, 1);
            b.actor.set_position(Math.round(sx - 8 * sf), Math.round(sy - 2 * sf));
            b.actor.set_scale(s * k, s);
            b.actor.rotation_angle_z = Math.atan2(svy, svx) * 180 / Math.PI;
        }
    }

    // far things first
    _sort() {
        const items = [];
        for (const j of this.jets) {
            if (j.state !== 'dead')
                items.push({actor: j.actor, depth: j.depth});
        }
        for (const t of this.tanks) {
            if (t.state !== 'gone')
                items.push({actor: t.actor, depth: t.depth});
        }
        for (const p of this.pilots)
            items.push({actor: p.actor, depth: p.depth});
        items.push(...this.fx.sortables());
        items.sort((a, b) => b.depth - a.depth);
        if (items.length === this._order.length && items.every((it, i) => it.actor === this._order[i]))
            return;
        let prev = null;
        for (const it of items) {
            if (prev)
                this.mid.set_child_above_sibling(it.actor, prev);
            else
                this.mid.set_child_below_sibling(it.actor, null);
            prev = it.actor;
        }
        this._order = items.map(it => it.actor);
    }

    destroy() {
        if (!this.dead)
            this.layer.destroy();
    }
}

// ------------------------------------------------------------- extension

export default class DogfightExtension extends Extension {
    enable() {
        this._settingsPath = GLib.build_filenamev([GLib.get_user_config_dir(), 'dogfight.json']);
        this._settings = {...DEFAULTS, ...this._loadSettings()};
        this._settings.perTeam = clamp(Math.round(this._settings.perTeam) || 2, 1, 4);
        this._settings.tanksPerTeam = clamp(Math.round(this._settings.tanksPerTeam ?? 2), 0, 4);

        this._world = new World(this.path, this._settings.perTeam, this._settings.tanksPerTeam,
            (s, ts) => this._updateScore(s, ts));
        this._placeActor();
        this._buildIndicator();

        this._overviewIds = [
            Main.overview.connect('showing', () => this._updateVisibility()),
            Main.overview.connect('hidden', () => this._updateVisibility()),
        ];
        this._fsId = global.display.connect('in-fullscreen-changed', () => this._updateVisibility());
        this._monId = Main.layoutManager.connect('monitors-changed', () => {
            this._world.updateBounds();
            this._updateVisibility();
        });
        this._waId = global.display.connect('workareas-changed', () => this._world.updateBounds());

        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, TICK_MS, () => {
            if (this._world.dead)
                return GLib.SOURCE_REMOVE;
            if (this._world.layer.visible) {
                try {
                    this._world.tick();
                } catch (e) {
                    console.error(`dogfight: ${e.message}\n${e.stack}`);
                    this._timer = 0;
                    return GLib.SOURCE_REMOVE;
                }
            }
            return GLib.SOURCE_CONTINUE;
        });
        this._updateVisibility();
    }

    disable() {
        if (this._timer) {
            GLib.source_remove(this._timer);
            this._timer = 0;
        }
        this._overviewIds?.forEach(id => Main.overview.disconnect(id));
        this._overviewIds = null;
        if (this._fsId)
            global.display.disconnect(this._fsId);
        if (this._waId)
            global.display.disconnect(this._waId);
        if (this._monId)
            Main.layoutManager.disconnect(this._monId);
        this._fsId = this._waId = this._monId = 0;
        this._indicator?.destroy();
        this._indicator = null;
        this._world?.destroy();
        this._world = null;
    }

    // ---------------------------------------------------------- helpers

    _loadSettings() {
        try {
            const [ok, bytes] = GLib.file_get_contents(this._settingsPath);
            if (ok)
                return JSON.parse(new TextDecoder().decode(bytes));
        } catch (e) {}
        return {};
    }

    _saveSettings() {
        try {
            GLib.file_set_contents(this._settingsPath, JSON.stringify(this._settings, null, 2));
        } catch (e) {
            console.warn(`dogfight: cannot save settings: ${e.message}`);
        }
    }

    _placeActor() {
        const actor = this._world.layer;
        actor.get_parent()?.remove_child(actor);
        if (this._settings.aboveWindows) {
            // Above windows, below the top panel / popups.
            Main.layoutManager.uiGroup.insert_child_below(actor, Main.layoutManager.panelBox);
        } else {
            // On the desktop: right above the wallpaper, below all windows.
            global.window_group.insert_child_above(actor, Main.layoutManager._backgroundGroup);
        }
    }

    _updateVisibility() {
        if (!this._world)
            return;
        const fullscreen = this._settings.aboveWindows &&
            Main.layoutManager.monitors.some(m => m.inFullscreen);
        this._world.layer.visible = this._settings.visible && !Main.overview.visible && !fullscreen;
    }

    _updateScore(s, ts) {
        if (this._scoreItem)
            this._scoreItem.label.text = `Самолёты: ${TEAM_NAMES.wood} ${s.wood} : ${s.desert} ${TEAM_NAMES.desert}`;
        if (this._tankScoreItem)
            this._tankScoreItem.label.text = `Танки: ${TEAM_NAMES.wood} ${ts.wood} : ${ts.desert} ${TEAM_NAMES.desert}`;
    }

    _buildIndicator() {
        this._indicator = new PanelMenu.Button(0.0, 'Dogfight', false);
        this._indicator.add_child(new St.Icon({
            gicon: Gio.FileIcon.new(Gio.File.new_for_path(GLib.build_filenamev([this.path, 'icon.png']))),
            style_class: 'system-status-icon',
        }));
        const menu = this._indicator.menu;

        this._scoreItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        menu.addMenuItem(this._scoreItem);
        this._tankScoreItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        menu.addMenuItem(this._tankScoreItem);
        this._updateScore(this._world.score, this._world.tankScore);
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const show = new PopupMenu.PopupSwitchMenuItem('Показывать бой', this._settings.visible);
        show.connect('toggled', (_i, v) => {
            this._settings.visible = v;
            this._saveSettings();
            this._updateVisibility();
        });
        menu.addMenuItem(show);

        const above = new PopupMenu.PopupSwitchMenuItem('Поверх окон', this._settings.aboveWindows);
        above.connect('toggled', (_i, v) => {
            this._settings.aboveWindows = v;
            this._saveSettings();
            this._placeActor();
            this._updateVisibility();
        });
        menu.addMenuItem(above);

        const sub = new PopupMenu.PopupSubMenuMenuItem('Самолётов в команде');
        const items = [];
        for (let n = 1; n <= 4; n++) {
            const it = sub.menu.addAction(`${n} × ${n}`, () => {
                this._settings.perTeam = n;
                this._saveSettings();
                this._world.setPerTeam(n);
                items.forEach((x, k) => x.setOrnament(k + 1 === n ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE));
            });
            it.setOrnament(n === this._settings.perTeam ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
            items.push(it);
        }
        menu.addMenuItem(sub);

        const tsub = new PopupMenu.PopupSubMenuMenuItem('Танков в команде');
        const titems = [];
        for (let n = 0; n <= 4; n++) {
            const it = tsub.menu.addAction(n === 0 ? 'без танков' : `${n} × ${n}`, () => {
                this._settings.tanksPerTeam = n;
                this._saveSettings();
                this._world.setTanks(n);
                titems.forEach((x, k) => x.setOrnament(k === n ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE));
            });
            it.setOrnament(n === this._settings.tanksPerTeam ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
            titems.push(it);
        }
        menu.addMenuItem(tsub);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        menu.addAction('Новый бой', () => this._world.reset());

        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }
}
