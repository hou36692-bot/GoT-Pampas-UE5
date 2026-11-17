"""生成 L_Pampas 的 16 位 Landscape 高度图（依据三帧截帧目测的地形布局，视觉近似）。

输出：Extracted/_converted/pampas_v2_terrain/
  heightmap_1009.png  16 位灰度，1009×1009，每像素 1 m（UE：Scale X/Y = 100）
  heightmap_preview.png  8 位预览（含等高线）
  terrain.json  参数、Z 缩放、高度范围、主要地物坐标
UE 高度换算：height_cm = (value - 32768) / 128 * ScaleZ。取 ScaleZ = 50 → ±256 m 量程中实际用 ±128 m，精度 0.39 cm。

布局（单位 m，X 东，Y 北，原点为场中心）：
  中心：起伏草原台地，基准 10 m，大草浪（波长约 120 m、振幅约 5 m）叠加小起伏。
  东北 (160, 140)：岩石露头小丘（第 1、2 帧），高约 14 m，岩石网格后续摆放。
  南侧 y < -220：上升到树林山脊（第 3 帧），山脊高约 35 m。
  东侧 x > 380：下降为海崖，海平面 -35 m（第 2 帧海平线）。
  西、北边缘：缓丘抬升，遮挡边界。
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
SEA = -35.0


def value_noise(x, y, cell, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((int(1100 / cell) + 4, int(1100 / cell) + 4))
    fx, fy = (x + 550) / cell, (y + 550) / cell
    ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
    tx, ty = fx - ix, fy - iy
    sx, sy = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
    a, b = g[ix, iy], g[ix + 1, iy]
    c, d = g[ix, iy + 1], g[ix + 1, iy + 1]
    return (a * (1 - sx) + b * sx) * (1 - sy) + (c * (1 - sx) + d * sx) * sy - 0.5


def fbm(x, y, cell, octaves, seed):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * value_noise(x, y, cell / 2 ** o, seed + o)
        norm += amp
        amp *= 0.5
    return total / norm


def smoothstep(a, b, v):
    t = np.clip((v - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def height(x, y):
    h = 10.0 + 10.0 * fbm(x, y, 240, 2, 11)                      # 大尺度起伏
    h += 4.5 * np.sin(x / 70 + 0.6) * np.cos(y / 95 - 0.4)          # 草浪
    h += 2.0 * fbm(x, y, 45, 3, 23)                                  # 小起伏
    h += 14.0 * np.exp(-((x - 160) ** 2 + (y - 140) ** 2) / (2 * 55 ** 2))   # 岩石露头小丘
    ridge = smoothstep(-220, -380, y) * (28 + 8 * fbm(x, y, 120, 3, 37))     # 南侧树林山脊
    h += ridge
    edge = smoothstep(330, 480, np.maximum(-x, y))                    # 西、北边缘缓丘
    h += edge * (18 + 6 * fbm(x, y, 90, 2, 41))
    coast = 400 + 25 * fbm(x, y, 150, 3, 53) * 2                      # 东侧海岸线（带噪声）
    cliff = smoothstep(coast - 15, coast + 35, x)
    h = h * (1 - cliff) + (SEA - 4 + 3 * fbm(x, y, 30, 2, 61)) * cliff
    return h


def write_png16(path, data):
    h, w = data.shape
    raw = b''.join(b'\x00' + data[y].astype('>u2').tobytes() for y in range(h))
    chunk = lambda k, b: struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 16, 0, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def write_png8(path, data):
    h, w = data.shape
    raw = b''.join(b'\x00' + data[y].astype(np.uint8).tobytes() for y in range(h))
    chunk = lambda k, b: struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    coords = np.arange(N) - (N - 1) / 2            # 米，像素中心
    # 图像行 = UE 的 Y（PNG 第 0 行对应 Landscape 的最小 Y），列 = X
    x, y = np.meshgrid(coords, coords)
    h = height(x, y)
    value = np.clip(np.round(h * 100 / SCALE_Z * 128 + 32768), 0, 65535).astype(np.uint16)
    write_png16(OUT / 'heightmap_1009.png', value)
    norm = (h - h.min()) / (h.max() - h.min()) * 255
    contour = (np.mod(h, 5) < 0.25)
    preview = np.where(contour, 0, norm)
    write_png8(OUT / 'heightmap_preview.png', preview)
    play = h[(np.abs(x) <= 250) & (np.abs(y) <= 250)]
    info = dict(resolution=N, meters_per_pixel=1.0, ue_scale=[100, 100, SCALE_Z], sea_level_m=SEA,
                height_m=dict(min=round(float(h.min()), 2), max=round(float(h.max()), 2),
                              play_min=round(float(play.min()), 2), play_max=round(float(play.max()), 2)),
                features_m=dict(field_centre=[0, 0], rock_knoll=[160, 140], forest_ridge_y=-300, sea_cliff_x=400),
                spawn_m=[-60, -40, round(float(height(np.array(-60.0), np.array(-40.0))), 2)],
                note='PNG 行=+Y 方向递增（UE 导入后核对），列=+X')
    (OUT / 'terrain.json').write_text(json.dumps(info, indent=2, ensure_ascii=False), 'utf-8')
    print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    main()
