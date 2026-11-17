"""用原版芒草图集（pampas_d，512×2048）的卡片制作 L_Pampas 的芒草丛与草丛，含显式 4 级 LOD。

在 Blender 中运行：blender -b --python-exit-code 1 -P build_pampas_v2_assets.py
图集区域（像素，y 向下）：叶丛 x0-512 y22-1310（叶根在上）；茎+扇形穗 x51-335 y900-2030（穗在下）；窄穗 x347-459 y1593-2035。
网格中 UV 的 v 取“图像自上而下的比例”，make_mesh 负责翻转。单一材质槽。
顶点色：R=1 穗/茎、0 叶；G=单株随机值；B=高度比例 0..1（风权重）；A=1。
芒草倾向沿局部 +X（实例化时只做 ±30° 偏航抖动，保持整片朝一个方向倒伏）。
"""
import json
import math
from pathlib import Path
import random
import sys
import bpy

ROOT = Path('D:/HOU/Ghost of Tsushima')
sys.path.insert(0, str(ROOT / 'Tools'))
from build_m1_geometry import part, vertex
from blender_asset_preview import make_mesh, verify_fbx

OUTPUT = ROOT / 'Extracted/_converted/pampas_v2_assets_r4'
W, H = 512.0, 2048.0
LEAF_UV = (0 / W, 22 / H, 512 / W, 1310 / H)
STALK_UV = (51 / W, 900 / H, 335 / W, 2030 / H)
NARROW_UV = (347 / W, 1593 / H, 459 / W, 2035 / H)
STEM_UV = (300 / W, 640 / H, 345 / W, 900 / H)
PLUME_UV = (51 / W, 1500 / H, 292 / W, 2025 / H)      # 扇形穗本体（上端连茎）
PLUME_NARROW_UV = (347 / W, 1593 / H, 459 / W, 2035 / H)
PX_PER_M = 1360.0


def norm(v):
    l = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / l for c in v]


def card(mesh, curve, side, width, uv, cols, color, max_h, cup=0.0, up_bias=0.65):
    """沿中心线 curve（点列，自 uv 的 v0 到 v1）铺一张卡片；side 为横向单位向量；cols 为横向顶点数。"""
    base = len(mesh['positions'])
    u0, v0, u1, v1 = uv
    rows = len(curve)
    for j, c in enumerate(curve):
        t = j / (rows - 1)
        nxt = curve[min(j + 1, rows - 1)]
        prv = curve[max(j - 1, 0)]
        tangent = norm([nxt[k] - prv[k] for k in range(3)])
        face = norm([side[1] * tangent[2] - side[2] * tangent[1], side[2] * tangent[0] - side[0] * tangent[2],
                     side[0] * tangent[1] - side[1] * tangent[0]])
        for i in range(cols):
            s = i / (cols - 1) - 0.5
            bulge = cup * (1 - (2 * s) ** 2)
            p = [c[k] + side[k] * s * width + face[k] * bulge for k in range(3)]
            n = norm([face[k] * (1 - up_bias) + (0, 0, 1)[k] * up_bias + side[k] * s * 0.4 for k in range(3)])
            vertex(mesh, p, n, (u0 + (u1 - u0) * (i / (cols - 1)), v0 + (v1 - v0) * t),
                   (color[0], color[1], min(1.0, max(0.0, p[2] / max_h)), 1.0))
    for j in range(rows - 1):
        for i in range(cols - 1):
            a = base + j * cols + i
            b = a + cols
            mesh['indices'].extend([a, b, b + 1, a, b + 1, a + 1])


def leaves(mesh, rng, count, height, spread, segs, cols, max_h):
    for k in range(count):
        ang = k * math.tau / count + rng.uniform(-0.35, 0.35)
        radial = (math.cos(ang), math.sin(ang), 0.0)
        side = (-radial[1], radial[0], 0.0)
        h = height * rng.uniform(0.8, 1.1)
        out = spread * rng.uniform(0.7, 1.2)
        droop = h * rng.uniform(0.15, 0.3)
        curve = [[radial[0] * out * t ** 1.4, radial[1] * out * t ** 1.4, h * t - droop * t * t] for t in [j / segs for j in range(segs + 1)]]
        width = (LEAF_UV[2] - LEAF_UV[0]) * W / PX_PER_M * h / ((LEAF_UV[3] - LEAF_UV[1]) * H / PX_PER_M)
        card(mesh, curve, side, width, LEAF_UV, cols, (0.0, rng.random()), max_h, cup=0.03, up_bias=0.3)


def stalks(mesh, rng, count, segs, cards, max_h, narrow_share=0.0):
    for k in range(count):
        g = rng.random()
        ang = rng.uniform(0, math.tau)
        root = (math.cos(ang) * rng.uniform(0.03, 0.16), math.sin(ang) * rng.uniform(0.03, 0.16))
        scale = rng.uniform(0.9, 1.25)
        base_h = rng.uniform(0.45, 0.7) * scale
        lean = rng.uniform(0.25, 0.5) * scale
        sway = rng.uniform(-0.12, 0.12)
        narrow = rng.random() < narrow_share
        uv = PLUME_NARROW_UV if narrow else PLUME_UV
        length = rng.uniform(0.5, 0.62) * scale
        width = (0.10 if narrow else 0.17) * scale
        stem_h = base_h + 0.35 * scale
        stem_curve = [[root[0] + 0.25 * lean * t * t, root[1], stem_h * t] for t in (0, 0.35, 0.7, 1)]
        card(mesh, stem_curve, (0, 1, 0), 0.025 * scale, STEM_UV, 2, (1.0, g), max_h)
        top = stem_curve[-1]
        droop = rng.uniform(0.25, 0.45)
        curve = [[top[0] + (0.25 * lean + length * 0.85) * t, top[1] + sway * t,
                  top[2] + length * 0.35 * t - length * droop * t * t]
                 for t in [j / segs for j in range(segs + 1)]]
        for c in range(cards):
            spread = (c - (cards - 1) / 2) * math.radians(38) + rng.uniform(-0.15, 0.15)
            a = math.pi / 2 + spread
            side = (math.cos(a) * 0.5, math.sin(a), math.sin(spread) * 0.25)
            card(mesh, curve, norm(side), width * (1.0 - 0.12 * abs(c - (cards - 1) / 2)), uv, 3, (1.0, g), max_h,
                 cup=0.03 * scale, up_bias=0.25)


VARIANTS = {
    'SM_Pampas_A': dict(kind='pampas', stalks=5, leaves=6, leaf_h=0.95, spread=0.32, seed=11, narrow=0.2),
    'SM_Pampas_B': dict(kind='pampas', stalks=7, leaves=7, leaf_h=1.05, spread=0.38, seed=23, narrow=0.15),
    'SM_Pampas_C': dict(kind='pampas', stalks=3, leaves=5, leaf_h=0.85, spread=0.28, seed=37, narrow=0.6),
    'SM_Grass_A': dict(kind='grass', leaves=9, leaf_h=0.90, spread=0.45, seed=41),
    'SM_Grass_B': dict(kind='grass', leaves=7, leaf_h=0.70, spread=0.38, seed=53),
    'SM_GrassBlades_A': dict(kind='blades', blades=24, h=(0.55, 1.10), radius=0.30, dry=0.22, seed=61),
    'SM_GrassBlades_B': dict(kind='blades', blades=20, h=(0.40, 0.80), radius=0.26, dry=0.30, seed=67),
}
# 草叶丛 LOD：(叶片保留比例, 每片分段数)；分段 7 对应原版近处 15 顶点、分段 3 对应远处 7 顶点
BLADE_LODS = [(1.0, 7), (0.7, 4), (0.45, 2), (0.25, 1)]


def bezier(p0, p1, p2, p3, t):
    u = 1 - t
    pos = [u ** 3 * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t ** 3 * p3[k] for k in range(3)]
    der = [3 * u * u * (p1[k] - p0[k]) + 6 * u * t * (p2[k] - p1[k]) + 3 * t * t * (p3[k] - p2[k]) for k in range(3)]
    return pos, der


def blades(mesh, spec, lod):
    """几何草叶（参照原版 GPU 草：三次贝塞尔中线、宽度渐细、宽度方向法线外倾做圆润感）。
    UV0：u 横向 0..1，v 沿叶长 0（根）..1（尖）。UV1：x 单片叶随机值，y 枯叶标记 0/1。整丛沿局部 +X 倒伏。"""
    rng = random.Random(spec['seed'])
    keep, segs = BLADE_LODS[lod]
    items = []
    for i in range(spec['blades']):
        r, a = spec['radius'] * math.sqrt(rng.random()), rng.uniform(0, math.tau)
        items.append(dict(root=(r * math.cos(a), r * math.sin(a)), h=rng.uniform(*spec['h']), yaw=rng.uniform(-0.6, 0.6),
                          bend=rng.uniform(0.55, 1.05), width=rng.uniform(0.028, 0.050), rnd=rng.random(),
                          dry=1.0 if rng.random() < spec['dry'] else 0.0, twist=rng.uniform(-0.5, 0.5)))
    items.sort(key=lambda b: -b['h'])
    items = items[:max(2, round(len(items) * keep))]
    for b in items:
        d = (math.cos(b['yaw']), math.sin(b['yaw']), 0.0)
        h, k = b['h'], b['bend']
        p0 = (b['root'][0], b['root'][1], 0.0)
        p1 = (p0[0] + d[0] * h * 0.05, p0[1] + d[1] * h * 0.05, h * 0.45)
        p2 = (p0[0] + d[0] * h * k * 0.55, p0[1] + d[1] * h * k * 0.55, h * (0.95 - 0.15 * k))
        p3 = (p0[0] + d[0] * h * k, p0[1] + d[1] * h * k, h * (1.0 - 0.55 * k * k))
        base = len(mesh['positions'])
        for j in range(segs + 1):
            t = j / segs
            pos, der = bezier(p0, p1, p2, p3, t)
            tangent = norm(der)
            side = norm([-d[1] * math.cos(b['twist'] * t) , d[0] * math.cos(b['twist'] * t), math.sin(b['twist'] * t) * 0.3])
            face = norm([tangent[1] * side[2] - tangent[2] * side[1], tangent[2] * side[0] - tangent[0] * side[2],
                         tangent[0] * side[1] - tangent[1] * side[0]])
            if face[2] < 0:
                face = [-c for c in face]
            half = 0.5 * b['width'] * (1 - t ** 1.6) + 0.0015
            for e in (-1, 1):
                p = [pos[c] + side[c] * half * e for c in range(3)]
                n = norm([face[c] + side[c] * 0.55 * e for c in range(3)])
                vertex(mesh, p, n, ((e + 1) / 2, t), (0.0, b['rnd'], t, 1.0))
                mesh['uvs'][1].append([b['rnd'], b['dry']])
        for j in range(segs):
            a0 = base + j * 2
            mesh['indices'].extend([a0, a0 + 2, a0 + 3, a0, a0 + 3, a0 + 1])
# (叶卡数比例, 叶分段, 叶列, 茎卡数, 茎分段, 茎数量比例)
LODS = [(1.0, 5, 3, 3, 5, 1.0), (0.7, 3, 2, 2, 3, 1.0), (0.5, 2, 2, 1, 2, 0.7), (0.34, 1, 2, 1, 1, 0.5)]


def build(name, spec, lod):
    if spec['kind'] == 'blades':
        mesh = part('GrassBlade')
        mesh['uvs'].append([])
        blades(mesh, spec, lod)
        return mesh
    mesh = part('PampasAtlas')
    rng = random.Random(spec['seed'])
    lf, lseg, lcol, scards, sseg, sfrac = LODS[lod]
    max_h = 1.9
    leaves(mesh, rng, max(2, round(spec['leaves'] * lf)), spec['leaf_h'], spec['spread'], lseg, lcol, max_h)
    if spec['kind'] == 'pampas':
        stalks(mesh, random.Random(spec['seed'] + 1), max(1, round(spec['stalks'] * sfrac)), sseg, scards, max_h, spec.get('narrow', 0))
    return mesh


def main():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name, spec in VARIANTS.items():
        entry = dict(name=name, kind=spec['kind'], lods=[])
        for lod in range(len(BLADE_LODS) if spec['kind'] == 'blades' else len(LODS)):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            mesh = build(name, spec, lod)
            assert len(mesh['positions']) == len(mesh['uvs'][0]) == len(mesh['normals']) == len(mesh['colors'][0])
            obj = make_mesh(mesh, [], 0)
            obj.data.materials[0].name = 'GrassBlade' if spec['kind'] == 'blades' else 'PampasAtlas'
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            path = OUTPUT / f'{name}_LOD{lod}.fbx'
            bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, object_types={'MESH'}, axis_forward='Y', axis_up='Z',
                                     use_mesh_modifiers=False, bake_anim=False, mesh_smooth_type='FACE')
            if lod == 0:
                bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / f'{name}.blend'))
            entry['lods'].append(dict(fbx=str(path), triangles=len(mesh['indices']) // 3, passed=verify_fbx(path, [obj])['passed']))
        manifest.append(entry)
        print(name, [l['triangles'] for l in entry['lods']])
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, indent=2), 'utf-8')
    print('PAMPAS_V2_ASSETS_SUCCESS')


if __name__ == '__main__':
    main()
