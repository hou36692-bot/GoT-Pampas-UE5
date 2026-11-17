"""Grass kind map and grass height map for L_Pampas (inputs of the GPU grass, same grid as heightmap_1009.png).

Output: Extracted/_converted/pampas_v2_terrain/
  grass_kind_1009.png    8-bit, value = grass kind index into the captured kind table (0 = no grass)
  grass_height_1009.png  8-bit, grass height 0..1 (kind: h = saturate(v * kind[120] + kind[124]) * kind[116])
  grass_samples.json     heightmap values at a few points (to verify the Landscape still matches the PNG)

[截帧] the original uses a 513^2 kind map and a BC4 grass height map per area; the values here are authored for our
terrain [推断]: kind 1 (wind 0.65, Voronoi clusters, the dominant kind of the captured frame) everywhere grass grows,
kind 2 (stiff, wind 0.1, no cluster height) in patches; no grass on steep slopes (rock) and near the sea.
usage: python -I build_grass_maps.py
"""
import json
import struct
import zlib
from pathlib import Path

import numpy as np

ROOT = Path('D:/HOU/Ghost of Tsushima')
OUT = ROOT / 'Extracted/_converted/pampas_v2_terrain'
N = 1009
SCALE_Z = 50.0


def read_png16(path):
    data = Path(path).read_bytes()
    pos, idat, w, h = 8, b'', 0, 0
    while pos < len(data):
        n = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
            assert depth == 16 and ctype == 0, (depth, ctype)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 2
    out = np.zeros((h, stride), np.int32)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)], np.uint8).astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:   # sub / average / paeth: sequential decode
            cur = np.zeros(stride, np.int32)
            for x in range(stride):
                a = cur[x - 2] if x >= 2 else 0
                b = prev[x]
                c = prev[x - 2] if x >= 2 else 0
                if f == 1:
                    p = a
                elif f == 3:
                    p = (a + b) // 2
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (line[x] + p) & 255
        out[y] = cur
        prev = cur
    return (out[:, 0::2] * 256 + out[:, 1::2]).astype(np.float64)


def write_png8(path, data):
    h, w = data.shape
    raw = b''.join(b'\x00' + data[y].astype(np.uint8).tobytes() for y in range(h))
    chunk = lambda k, b: struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def value_noise(x, y, cell, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((int(1100 / cell) + 4, int(1100 / cell) + 4))
    fx, fy = (x + 550) / cell, (y + 550) / cell
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - ix, fy - iy
    sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a, b = g[ix, iy], g[ix + 1, iy]
    c, d = g[ix, iy + 1], g[ix + 1, iy + 1]
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy


def fbm(x, y, cell, octaves, seed):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * value_noise(x, y, cell / 2 ** o, seed + o)
        norm += amp
        amp *= 0.5
    return total / norm


def main():
    v = read_png16(OUT / 'heightmap_1009.png')
    h = (v - 32768) / 128 * SCALE_Z / 100          # metres
    coords = np.arange(N) - (N - 1) / 2
    x, y = np.meshgrid(coords, coords)             # row = Y, column = X (same as the heightmap)
    gy, gx = np.gradient(h)                         # 1 m spacing
    slope = np.sqrt(gx * gx + gy * gy)
    patches = fbm(x, y, 70, 3, 101)
    kind = np.where(patches > 0.62, 2, 1)
    kind = np.where((slope > 0.75) | (h < -31.0), 0, kind)
    tall = 0.35 + 0.45 * fbm(x, y, 40, 3, 202) + 0.25 * (fbm(x, y, 9, 2, 303) - 0.5)
    tall *= np.clip(1.4 - slope, 0.4, 1.0)
    write_png8(OUT / 'grass_kind_1009.png', kind)
    write_png8(OUT / 'grass_height_1009.png', np.clip(np.round(tall * 255), 0, 255))
    pts = [(-60, -40), (0, 0), (100, 50), (-150, 120), (160, 140), (-200, -180), (250, -60)]
    samples = []
    for px, py in pts:
        col, row = int(px + (N - 1) / 2), int(py + (N - 1) / 2)
        samples.append(dict(x_cm=px * 100, y_cm=py * 100, value=int(v[row, col]), z_cm=round(float(h[row, col] * 100), 2)))
    (OUT / 'grass_samples.json').write_text(json.dumps(samples, indent=1), 'utf-8')
    stats = dict(kind_share={k: round(float((kind == k).mean()), 3) for k in (0, 1, 2)},
                 tall=[round(float(tall.min()), 2), round(float(tall.mean()), 2), round(float(tall.max()), 2)])
    print(json.dumps(stats), json.dumps(samples))


if __name__ == '__main__':
    main()
