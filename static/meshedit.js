// The face mesh edit formulas, ported 1:1 from stages/meshedit.py (keep both in step: tests/test_mesh_edit.py runs this
// file under node against tests/fixtures/mesh-edit-cases.json, the same fixture the Python side is tested with).
// Pure: no DOM, no network. Points are [x, y] normalized to the frame; work happens in pixel-aspect space (x · aspect, y).
//   normalize(mesh) → {off: [[a, b]], keys: Map(frame → {dx, dy, scale, rot}), expr: Map(frame → {name: value})}
//   transformAt(keys, frame) → the key, the eased blend e(t) = t²(3 − 2t) between the two keys around it, or null outside
//   editPoints(points, expr, key, aspect) → edited points (expressions from the unedited points, then the transform)
//   editFrame(frame, index, norm, aspect) → {faces, status, edited} for one face-landmarks.json frame
export const EXPR = ['jaw', 'smile', 'pucker', 'blink_l', 'blink_r', 'brow'];
export const RANGES = { jaw: [0, 1], smile: [-1, 1], pucker: [0, 1], blink_l: [0, 1], blink_r: [0, 1], brow: [-1, 1] };
const TKEYS = ['dx', 'dy', 'scale', 'rot'];
export const IDENTITY = { dx: 0, dy: 0, scale: 1, rot: 0 };
const SCALE = [0.2, 5], SHIFT = 2, ROT = 180;
const JAW_OPEN = 0.10, SMILE_OUT = 0.06, SMILE_UP = 0.04, SMILE_RADIUS = 0.18, PUCKER_IN = 0.4, PUCKER_ROUND = 0.15, BROW_UP = 0.06;
const FOREHEAD = 10, CHIN = 152, CORNERS = [61, 291], LIP_TOP = 13, LIP_BOTTOM = 14;
const UPPER_LIP = new Set([61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]);
const LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 185, 40, 39, 37, 0, 267, 269, 270, 409, 78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 191, 80, 81, 82, 13, 312, 311, 310, 415];
const EYELIDS = { blink_r: [[246, 7], [161, 163], [160, 144], [159, 145], [158, 153], [157, 154], [173, 155]], blink_l: [[466, 249], [388, 390], [387, 373], [386, 374], [385, 380], [384, 381], [398, 382]] };
const BROWS = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107, 276, 283, 282, 295, 285, 300, 293, 334, 296, 336];
export const MESH = 468;
const MAX_INDEX = 409;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const num = (v, d = 0) => { const n = Number(v); return v === null || v === '' || v === undefined || typeof v === 'boolean' || !Number.isFinite(n) ? d : n; };
const int = v => (typeof v === 'number' ? (Number.isInteger(v) ? v : null) : typeof v === 'string' && /^-?\d+$/.test(v.trim()) ? Number(v.trim()) : null);   // as_int() in Python

export function mergeRanges(ranges) {
  const out = [];
  for (const [a, b] of [...ranges].sort((p, q) => p[0] - q[0] || p[1] - q[1])) { if (out.length && a <= out[out.length - 1][1] + 1) out[out.length - 1][1] = Math.max(out[out.length - 1][1], b); else out.push([a, b]); }
  return out;
}
/** Remove frames a…b from inclusive ranges (Mesh on, Reset). */
export function subtractRange(ranges, a, b) {
  const out = [];
  for (const [x, y] of ranges) { if (y < a || x > b) out.push([x, y]); else { if (x < a) out.push([x, a - 1]); if (y > b) out.push([b + 1, y]); } }
  return out;
}

export function normalize(mesh) {
  mesh = mesh && typeof mesh === 'object' ? mesh : {};
  const ranges = [];
  for (const r of Array.isArray(mesh.off) ? mesh.off : []) {
    if (!Array.isArray(r) || r.length !== 2) continue;
    const a = int(r[0]), b = int(r[1]); if (a == null || b == null) continue;
    ranges.push([Math.max(0, Math.min(a, b)), Math.max(a, b)]);
  }
  const keys = new Map(), expr = new Map();
  for (const [f0, k] of Object.entries(mesh.keys && typeof mesh.keys === 'object' && !Array.isArray(mesh.keys) ? mesh.keys : {})) {
    const f = int(f0); if (f == null || f < 0 || !k || typeof k !== 'object') continue;
    keys.set(f, { dx: clamp(num(k.dx), -SHIFT, SHIFT), dy: clamp(num(k.dy), -SHIFT, SHIFT), scale: clamp(num(k.scale, 1), ...SCALE), rot: clamp(num(k.rot), -ROT, ROT) });
  }
  for (const [f0, e] of Object.entries(mesh.expr && typeof mesh.expr === 'object' && !Array.isArray(mesh.expr) ? mesh.expr : {})) {
    const f = int(f0); if (f == null || f < 0 || !e || typeof e !== 'object') continue;
    const values = {}; for (const n of EXPR) if (num(e[n])) values[n] = clamp(num(e[n]), ...RANGES[n]);
    if (Object.keys(values).length) expr.set(f, values);
  }
  return { off: mergeRanges(ranges), keys, expr };
}
export const offSet = ranges => { const s = new Set(); for (const [a, b] of ranges) for (let f = a; f <= b; f++) s.add(f); return s; };
export const sortedKeys = keys => [...keys.keys()].sort((a, b) => a - b);

export function transformAt(keys, frame) {
  if (!keys || !keys.size) return null;
  if (keys.has(frame)) return { ...keys.get(frame) };
  const ks = sortedKeys(keys);
  if (frame < ks[0] || frame > ks[ks.length - 1]) return null;
  let i = 0; while (ks[i] < frame) i++;
  const a = ks[i - 1], b = ks[i], t = (frame - a) / (b - a), e = t * t * (3 - 2 * t), A = keys.get(a), B = keys.get(b), out = {};
  for (const k of TKEYS) out[k] = A[k] + (B[k] - A[k]) * e;
  return out;
}
export const isIdentity = key => !key || TKEYS.every(k => (key[k] ?? IDENTITY[k]) === IDENTITY[k]);

export function exprRuns(expr) {   // consecutive frames with the same values count as one edit
  const runs = []; let last = null;
  for (const f of [...expr.keys()].sort((a, b) => a - b)) {
    const v = expr.get(f), sig = JSON.stringify(Object.keys(v).sort().map(k => [k, v[k]]));
    if (runs.length && last && last[0] === f - 1 && last[1] === sig) runs[runs.length - 1][1] = f; else runs.push([f, f]);
    last = [f, sig];
  }
  return runs;
}

export function editPoints(points, expr, key, aspect = 1) {
  if (!expr && isIdentity(key)) return points.map(([x, y]) => [x, y]);
  const A = Number(aspect) || 1, P = points.map(([x, y]) => [x * A, y]), n = P.length, out = P.map(p => [p[0], p[1]]), touched = new Set();
  if (expr && n > MAX_INDEX) {
    const f = P[FOREHEAD], c = P[CHIN], dx = c[0] - f[0], dy = c[1] - f[1], H = Math.hypot(dx, dy) || 1e-9, d = [dx / H, dy / H], r = [d[1], -d[0]];
    const mids = [CORNERS[0], CORNERS[1], LIP_TOP, LIP_BOTTOM]; let mx = 0, my = 0; for (const i of mids) mx += P[i][0]; for (const i of mids) my += P[i][1]; const m = [mx / 4, my / 4];
    const dot = (p, u) => (p[0] - m[0]) * u[0] + (p[1] - m[1]) * u[1];
    const move = (i, ox, oy) => { out[i][0] += ox; out[i][1] += oy; touched.add(i); };
    const lim = Math.min(n, MESH);
    const jaw = expr.jaw || 0;
    if (jaw) {
      const vc = (dot(P[CORNERS[0]], d) + dot(P[CORNERS[1]], d)) / 2; let span = dot(P[LIP_BOTTOM], d) - vc; if (span <= 0.02 * H) span = 0.02 * H;
      const M = Math.abs(dot(P[CORNERS[1]], r) - dot(P[CORNERS[0]], r)) / 2 || 1e-9;
      for (let i = 0; i < lim; i++) {
        if (UPPER_LIP.has(i)) continue;
        const wv = clamp((dot(P[i], d) - vc) / span, 0, 1); if (!wv) continue;
        const w = wv * clamp(2 - Math.abs(dot(P[i], r)) / M, 0, 1);
        if (w) move(i, jaw * JAW_OPEN * H * w * d[0], jaw * JAW_OPEN * H * w * d[1]);
      }
    }
    const smile = expr.smile || 0;
    if (smile) {
      const R = SMILE_RADIUS * H;
      for (let i = 0; i < lim; i++) {
        const d0 = Math.hypot(P[i][0] - P[CORNERS[0]][0], P[i][1] - P[CORNERS[0]][1]), d1 = Math.hypot(P[i][0] - P[CORNERS[1]][0], P[i][1] - P[CORNERS[1]][1]);
        const k = d1 < d0 ? CORNERS[1] : CORNERS[0], dist = d1 < d0 ? d1 : d0;   // ties go to 61, like Python's min()
        if (dist >= R) continue;
        const w = (1 - dist / R) ** 2, side = dot(P[k], r) >= 0 ? 1 : -1;
        move(i, smile * H * w * (SMILE_OUT * side * r[0] - SMILE_UP * d[0]), smile * H * w * (SMILE_OUT * side * r[1] - SMILE_UP * d[1]));
      }
    }
    const pucker = expr.pucker || 0;
    if (pucker) for (const i of LIPS) { const a = dot(P[i], r), b = dot(P[i], d); move(i, pucker * (-PUCKER_IN * a * r[0] + PUCKER_ROUND * b * d[0]), pucker * (-PUCKER_IN * a * r[1] + PUCKER_ROUND * b * d[1])); }
    for (const name of ['blink_r', 'blink_l']) { const blink = expr[name] || 0; if (blink) for (const [u, l] of EYELIDS[name]) move(u, blink * (P[l][0] - P[u][0]), blink * (P[l][1] - P[u][1])); }
    const brow = expr.brow || 0;
    if (brow) for (const i of BROWS) move(i, -brow * BROW_UP * H * d[0], -brow * BROW_UP * H * d[1]);
  }
  if (key && !isIdentity(key)) {
    const lim = Math.min(n, MESH); let cx = 0, cy = 0; for (let i = 0; i < lim; i++) cx += P[i][0]; for (let i = 0; i < lim; i++) cy += P[i][1]; cx /= lim; cy /= lim;
    const s = key.scale ?? 1, a = (key.rot ?? 0) * Math.PI / 180, cs = Math.cos(a) * s, sn = Math.sin(a) * s, tx = (key.dx ?? 0) * A, ty = key.dy ?? 0;
    return out.map(([x, y]) => [(cx + cs * (x - cx) - sn * (y - cy) + tx) / A, cy + sn * (x - cx) + cs * (y - cy) + ty]);
  }
  return out.map((p, i) => (touched.has(i) ? [p[0] / A, p[1]] : [points[i][0], points[i][1]]));   // untouched points keep their exact values
}

/** The centroid of the unedited mesh points (what the transform turns about), normalized. */
export function centroid(points) {
  const lim = Math.min(points.length, MESH); let cx = 0, cy = 0;
  for (let i = 0; i < lim; i++) cx += points[i][0]; for (let i = 0; i < lim; i++) cy += points[i][1];
  return [cx / lim, cy / lim];
}

/** One frame of face-landmarks.json edited by a normalized layer: {faces, status, edited}. */
export function editFrame(frame, index, norm, aspect, off = offSet(norm.off)) {
  if (off.has(index)) return { faces: [], status: 'off', edited: 'off' };
  const faces = frame && Array.isArray(frame.faces) ? frame.faces : [], key = transformAt(norm.keys, index), e = norm.expr.get(index);
  if (!faces.length || !faces[0] || (isIdentity(key) && !e)) return { faces, status: frame ? frame.status : 'missing', edited: false };
  const pts = editPoints(faces[0].map(p => [p.x, p.y]), e, key, aspect);
  return { faces: [pts.map(([x, y]) => ({ x, y })), ...faces.slice(1)], status: frame.status, edited: true };
}
