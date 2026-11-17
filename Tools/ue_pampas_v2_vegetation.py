"""L_Pampas 植被与环境：贴图/网格导入、芒草材质、地形远景、海面、边界、分区 PCG。

在完整编辑器中运行（Tools/run_ue_script.ps1），完成生成并保存后退出。可重复运行：资产按所有者标签覆盖，
Actor 按标签查找后复用；PCG 体积重新生成。
"""
import json
import time
import traceback
from pathlib import Path
import unreal

ROOT = Path('D:/HOU/Ghost of Tsushima')
MAP = '/Game/GoT/Maps/L_Pampas'
OWNER = 'Pampas_20261107'
REPORT = ROOT / 'Tools/state/pampas_v2_vegetation.json'
ASSET_DIR = ROOT / 'Extracted/_converted/pampas_v2_assets_r4'
TEX_DIR = ROOT / 'Extracted/_converted/pampas'
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
MESH_EDITOR = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
LIB = unreal.MaterialEditingLibrary
STATE = dict(report=dict(actions=[], warnings=[]), start=time.monotonic())

PLAY_HALF_CM = 28000      # 玩家边界
VEG_HALF_CM = 34000       # 近景植被范围
WIND_YAW = 200.0          # 芒草整体倒伏方向（度，局部 +X 指向）


def note(msg):
    STATE['report']['actions'].append(msg)
    unreal.log('PAMPAS_VEG ' + msg)


def warn(msg):
    STATE['report']['warnings'].append(msg)
    unreal.log_warning('PAMPAS_VEG ' + msg)


def tag(obj):
    unreal.EditorAssetLibrary.set_metadata_tag(obj, 'GoTOwner', OWNER)


def check_owner(path):
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        obj = unreal.load_asset(path)
        assert unreal.EditorAssetLibrary.get_metadata_tag(obj, 'GoTOwner') == OWNER, f'not ours: {path}'
        return obj
    return None


def owned(name, folder, cls, factory):
    obj = check_owner(f'{folder}/{name}')
    if obj:
        return obj
    obj = ASSETS.create_asset(name, folder, cls, factory)
    assert obj, name
    tag(obj)
    return obj


# ---------- 材质节点工具 ----------
def node(mat, cls, x=0, y=0, **props):
    n = LIB.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def link(a, out, b, pin):
    if LIB.connect_material_expressions(a, out, b, pin):
        return
    names = [str(n) for n in LIB.get_material_expression_input_names(b)]
    alt = next((n for n in names if n.lower().replace(' ', '').startswith(pin.lower().replace(' ', '')[:3])), names[0] if names else '')
    assert LIB.connect_material_expressions(a, out, b, alt), (a.get_name(), out, b.get_name(), pin, names)
    warn(f'pin {pin} -> {alt} on {b.get_class().get_name()}')


def const(mat, v, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant, x, y, r=v)


def vec(mat, rgb, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(*rgb, 1))


def op(mat, cls, a, b, x=0, y=0, out_a=''):
    n = node(mat, cls, x, y)
    link(a, out_a, n, 'A')
    link(b, '', n, 'B')
    return n


def lerp(mat, a, b, alpha, x=0, y=0, alpha_out=''):
    n = node(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
    link(a, '', n, 'A'); link(b, '', n, 'B'); link(alpha, alpha_out, n, 'Alpha')
    return n


def compile_check(mat):
    # 材质被重建后风未接入：清掉标记，之后需再跑 Tools/ue_wind_assets.py 接 MF_GoTWind
    unreal.EditorAssetLibrary.remove_metadata_tag(mat, 'GoTWindWired')
    unreal.EditorAssetLibrary.remove_metadata_tag(mat, 'GoTWindDebugWired')   # then rerun Tools/ue_wind_debug_material.py
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    if errors:
        STATE['report'].setdefault('compile_errors', {})[mat.get_name()] = errors
        warn(f'{mat.get_name()} compile errors: {errors[:4]}')


# ---------- 导入 ----------
def import_texture(png, name, srgb=True):
    path = f'/Game/GoT/Pampas/Textures/{name}'
    check_owner(path)
    task = unreal.AssetImportTask()
    for k, v in dict(filename=str(png), destination_path='/Game/GoT/Pampas/Textures', destination_name=name,
                     automated=True, save=True, replace_existing=True).items():
        task.set_editor_property(k, v)
    ASSETS.import_asset_tasks([task])
    tex = unreal.load_asset(path)
    assert tex, path
    tex.set_editor_property('srgb', srgb)
    tag(tex)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    return tex


def fbx_options():
    options = unreal.FbxImportUI()
    options.import_mesh = True; options.import_as_skeletal = False
    options.import_materials = False; options.import_textures = False
    options.automated_import_should_detect_type = False
    options.mesh_type_to_import = unreal.FBXImportType.FBXIT_STATIC_MESH
    data = options.static_mesh_import_data
    for k, v in dict(combine_meshes=True, auto_generate_collision=False, generate_lightmap_u_vs=False,
                     convert_scene=True, convert_scene_unit=True, remove_degenerates=False).items():
        data.set_editor_property(k, v)
    data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS
    data.vertex_color_import_option = unreal.VertexColorImportOption.REPLACE
    return options


def import_meshes(materials):
    manifest = json.loads((ASSET_DIR / 'manifest.json').read_text('utf-8'))
    meshes = {}
    for item in manifest:
        assert all(l['passed'] for l in item['lods']), item['name']
        path = f"/Game/GoT/Pampas/Meshes/{item['name']}"
        old = check_owner(path)
        if old:
            MESH_EDITOR.remove_lods(old)
        task = unreal.AssetImportTask()
        for k, v in dict(filename=item['lods'][0]['fbx'], destination_path='/Game/GoT/Pampas/Meshes', destination_name=item['name'],
                         automated=True, save=True, replace_existing=True, replace_existing_settings=True,
                         options=fbx_options(), factory=unreal.FbxFactory()).items():
            task.set_editor_property(k, v)
        ASSETS.import_asset_tasks([task])
        mesh = unreal.load_asset(path)
        assert mesh, path
        for lod in range(1, len(item['lods'])):
            assert MESH_EDITOR.import_lod(mesh, lod, item['lods'][lod]['fbx']) == lod, (path, lod)
        # 屏幕尺寸 ≈ 包围球半径/距离：芒草约 10/23/54 m、草叶约 14/28/57 m 切换（旧值 1.8–17 m 就切，跑图跳变明显）
        sizes = {'pampas': [1.0, 0.08, 0.035, 0.015], 'blades': [1.0, 0.06, 0.03, 0.015]}.get(item['kind'], [1.0, 0.25, 0.1, 0.04])
        MESH_EDITOR.set_lod_screen_sizes(mesh, sizes[:len(item['lods'])])
        mesh.set_material(0, materials['blades' if item['kind'] == 'blades' else 'foliage'])
        counts = [mesh.get_num_triangles(i) for i in range(len(item['lods']))]
        assert counts == [l['triangles'] for l in item['lods']], (path, counts)
        tag(mesh)
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        meshes[item['name']] = mesh
        note(f"mesh {item['name']} LOD tris {counts}")
    return meshes


# ---------- 材质 ----------
def foliage_material(atlas, ngt):
    """原版图集着色：叶片保持橄榄绿；穗/茎（顶点色 R=1）去饱和并提亮成截帧里的米白银色。"""
    mat = owned('M_PampasFoliage', '/Game/GoT/Pampas/Materials', unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(mat)
    mat.set_editor_property('two_sided', True)
    mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property('opacity_mask_clip_value', 0.4)
    tex = node(mat, unreal.MaterialExpressionTextureSample, -1400, 0, texture=atlas)
    # 穗/叶按图集 V 区分（v > 0.70 为穗）；顶点色在导入后不可靠，不再依赖。
    uv = node(mat, unreal.MaterialExpressionTextureCoordinate, -1600, 400)
    v = node(mat, unreal.MaterialExpressionComponentMask, -1450, 400, r=False, g=True, b=False, a=False)
    link(uv, '', v, '')
    is_plume = node(mat, unreal.MaterialExpressionSmoothStep, -1250, 400)
    link(const(mat, 0.69, -1450, 470), '', is_plume, 'Min'); link(const(mat, 0.73, -1450, 510), '', is_plume, 'Max')
    link(v, '', is_plume, 'Value')
    rand = node(mat, unreal.MaterialExpressionPerInstanceRandom, -1400, 600)
    vary = op(mat, unreal.MaterialExpressionMultiply, rand, const(mat, 0.3, -1200, 680), -1050, 620)
    vary = op(mat, unreal.MaterialExpressionAdd, vary, const(mat, 0.85, -1050, 720), -900, 640)
    leaf = op(mat, unreal.MaterialExpressionMultiply, tex, vec(mat, (1.15, 1.25, 1.10), -1200, -120), -900, -100, out_a='RGB')
    leaf = op(mat, unreal.MaterialExpressionMultiply, leaf, vary, -700, -80)
    lum = node(mat, unreal.MaterialExpressionDotProduct, -1100, 150)
    link(tex, 'RGB', lum, 'A'); link(vec(mat, (0.3, 0.59, 0.11), -1300, 220), '', lum, 'B')
    grey = op(mat, unreal.MaterialExpressionMultiply, lum, vec(mat, (1.0, 1.0, 1.03), -1100, 260), -900, 200)
    plume = node(mat, unreal.MaterialExpressionLinearInterpolate, -700, 150)
    link(tex, 'RGB', plume, 'A'); link(grey, '', plume, 'B'); link(const(mat, 0.6, -900, 300), '', plume, 'Alpha')
    boosted = op(mat, unreal.MaterialExpressionMultiply, plume, const(mat, 1.6, -700, 300), -500, 180)
    plume = node(mat, unreal.MaterialExpressionSaturate, -350, 180)
    link(boosted, '', plume, '')
    albedo = lerp(mat, leaf, plume, is_plume, -150, 50)
    # 原版 pampas_ngt：R/G 切线空间法线，B 光泽，A 透光
    ngt_s = node(mat, unreal.MaterialExpressionTextureSample, -1400, 900, texture=ngt,
                 sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    nxy = node(mat, unreal.MaterialExpressionComponentMask, -1200, 900, r=True, g=True, b=False, a=False)
    link(ngt_s, 'RGB', nxy, '')
    nxy = op(mat, unreal.MaterialExpressionMultiply, nxy, const(mat, 2.0, -1200, 960), -1050, 900)
    nxy = op(mat, unreal.MaterialExpressionSubtract, nxy, const(mat, 1.0, -1050, 960), -900, 900)
    nxy = op(mat, unreal.MaterialExpressionMultiply, nxy, const(mat, 0.8, -900, 960), -750, 900)
    nrm = node(mat, unreal.MaterialExpressionDeriveNormalZ, -600, 900)
    link(nxy, '', nrm, 'InXY')
    gloss = node(mat, unreal.MaterialExpressionComponentMask, -1200, 1050, r=False, g=False, b=True, a=False)
    link(ngt_s, 'RGB', gloss, '')
    rough = op(mat, unreal.MaterialExpressionSubtract, const(mat, 1.0, -1050, 1050), gloss, -900, 1050)
    rough = lerp(mat, rough, const(mat, 0.85, -900, 1120), is_plume, -750, 1050)
    trans = op(mat, unreal.MaterialExpressionMultiply, ngt_s, const(mat, 0.7, -1200, 1200), -1050, 1180, out_a='A')
    trans = op(mat, unreal.MaterialExpressionAdd, trans, const(mat, 0.45, -1050, 1250), -900, 1180)
    sss = lerp(mat, vec(mat, (0.10, 0.20, 0.03), -350, 560), vec(mat, (0.45, 0.44, 0.40), -350, 620), is_plume, -150, 580)
    sss = op(mat, unreal.MaterialExpressionMultiply, sss, trans, -50, 640)
    fuzz = op(mat, unreal.MaterialExpressionMultiply, is_plume, const(mat, 0.35, -350, 1300), -150, 1300)
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 150, 150)
    slab.set_editor_property('sub_surface_type', unreal.MaterialSubSurfaceType.MSS_TWO_SIDED_WRAP)
    link(albedo, '', slab, 'Diffuse Albedo')
    link(rough, '', slab, 'Roughness')
    link(vec(mat, (0.02, 0.02, 0.02), -150, 700), '', slab, 'F0')
    link(sss, '', slab, 'SSS MFP')
    link(nrm, '', slab, 'Normal')
    link(fuzz, '', slab, 'Fuzz Amount')
    link(vec(mat, (0.85, 0.86, 0.88), -150, 1380), '', slab, 'Fuzz Color')
    local = node(mat, unreal.MaterialExpressionLocalPosition, -800, 1450)
    lz = node(mat, unreal.MaterialExpressionComponentMask, -650, 1450, r=False, g=False, b=True, a=False)
    link(local, '', lz, '')
    lz = op(mat, unreal.MaterialExpressionDivide, lz, const(mat, 120, -650, 1520), -500, 1450)
    lz_sat = node(mat, unreal.MaterialExpressionSaturate, -350, 1450)
    link(lz, '', lz_sat, '')
    ao = lerp(mat, const(mat, 0.4, -350, 1520), const(mat, 1.0, -350, 1560), lz_sat, -200, 1480)
    assert LIB.connect_material_property(ao, '', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    fade = node(mat, unreal.MaterialExpressionPerInstanceFadeAmount, -400, 800)
    # 剔除淡出用抖动溶解（TSR 抹平），而不是把遮罩直接乘 fade（那样在 fade≈clip 时整片同时消失）
    dither = node(mat, unreal.MaterialExpressionMaterialFunctionCall, -300, 860)
    dither.set_material_function(unreal.load_asset('/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA'))
    link(fade, '', dither, 'Alpha Threshold')
    mask = op(mat, unreal.MaterialExpressionMultiply, tex, dither, -150, 800, out_a='A')
    mat.set_editor_property('dithered_lod_transition', True)
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    assert LIB.connect_material_property(mask, '', unreal.MaterialProperty.MP_OPACITY_MASK)
    LIB.layout_material_expressions(mat)
    compile_check(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    note('material M_PampasFoliage')
    return mat


def pampas_pbr_instance(mat):
    """重建后恢复芒草 PBR 参数（默认值 = 上面的常量），网格挂 MI_PampasFoliage，保留实例里已调的值。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location('got_pampas_pbr', ROOT / 'Tools/ue_expose_pampas_pbr.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inst = module.apply(mat)
    note('material MI_PampasFoliage (PBR params exposed on M_PampasFoliage)')
    return inst


def blade_material():
    """几何草叶。颜色取自原版 G-Buffer；其余按 GDC 2021 草地演讲（Docs/Research/02）：
    Voronoi 式簇取色、光泽沿叶长变化、叶脉、常数透光 + 根部 AO、掠射角撑宽、远处压高光。"""
    mat = owned('M_PampasGrassBlade', '/Game/GoT/Pampas/Materials', unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(mat)
    mat.set_editor_property('two_sided', True)
    mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_OPAQUE)
    uv0 = node(mat, unreal.MaterialExpressionTextureCoordinate, -2000, 0)
    along = node(mat, unreal.MaterialExpressionComponentMask, -1800, 0, r=False, g=True, b=False, a=False)
    link(uv0, '', along, '')
    across = node(mat, unreal.MaterialExpressionComponentMask, -1800, 80, r=True, g=False, b=False, a=False)
    link(uv0, '', across, '')
    uv1 = node(mat, unreal.MaterialExpressionTextureCoordinate, -2000, 300, coordinate_index=1)
    rnd = node(mat, unreal.MaterialExpressionComponentMask, -1800, 260, r=True, g=False, b=False, a=False)
    link(uv1, '', rnd, '')
    dry = node(mat, unreal.MaterialExpressionComponentMask, -1800, 340, r=False, g=True, b=False, a=False)
    link(uv1, '', dry, '')
    # 簇：世界坐标按约 1.5 m 网格取 cell 随机色，用低频噪声扰动坐标让边界不规则
    world = node(mat, unreal.MaterialExpressionWorldPosition, -2000, 600)
    warp = node(mat, unreal.MaterialExpressionNoise, -1800, 700, scale=0.004, levels=2, output_min=-60, output_max=60,
                noise_function=unreal.NoiseFunction.NOISEFUNCTION_GRADIENT_ALU)
    link(world, '', warp, 'Position')
    warped = op(mat, unreal.MaterialExpressionAdd, world, warp, -1600, 620)
    cellpos = op(mat, unreal.MaterialExpressionDivide, warped, const(mat, 150, -1600, 700), -1450, 620)
    cell = node(mat, unreal.MaterialExpressionVectorNoise, -1300, 620,
                noise_function=unreal.VectorNoiseFunction.VNF_CELLNOISE_ALU)
    link(cellpos, '', cell, 'Position')
    c_r = node(mat, unreal.MaterialExpressionComponentMask, -1100, 600, r=True, g=False, b=False, a=False)
    link(cell, '', c_r, '')
    palette = lerp(mat, vec(mat, (0.078, 0.090, 0.010), -1100, -200), vec(mat, (0.048, 0.088, 0.015), -1100, -130), c_r, -900, -160)
    clump = node(mat, unreal.MaterialExpressionPerInstanceRandom, -1300, 500)
    palette = op(mat, unreal.MaterialExpressionMultiply, palette,
                 lerp(mat, const(mat, 0.9, -1100, 450), const(mat, 1.1, -1100, 500), clump, -950, 470), -750, -120)
    grad = node(mat, unreal.MaterialExpressionPower, -1600, 30)
    link(along, '', grad, 'Base'); link(const(mat, 0.7, -1800, 150), '', grad, 'Exp')
    tone = lerp(mat, const(mat, 0.6, -1450, 100), const(mat, 1.12, -1450, 150), grad, -1300, 60)
    vary = lerp(mat, const(mat, 0.85, -1450, 380), const(mat, 1.15, -1450, 420), rnd, -1300, 380)
    # 叶脉：中线略亮
    offset = op(mat, unreal.MaterialExpressionSubtract, across, const(mat, 0.5, -1800, 160), -1600, 180)
    mid = node(mat, unreal.MaterialExpressionAbs, -1450, 180)
    link(offset, '', mid, '')
    vein = node(mat, unreal.MaterialExpressionSmoothStep, -1300, 200)
    link(const(mat, 0.12, -1450, 240), '', vein, 'Min'); link(const(mat, 0.0, -1450, 280), '', vein, 'Max'); link(mid, '', vein, 'Value')
    vein = lerp(mat, const(mat, 1.0, -1150, 240), const(mat, 1.18, -1150, 280), vein, -1000, 220)
    shade = op(mat, unreal.MaterialExpressionMultiply, tone, vary, -1150, 120)
    shade = op(mat, unreal.MaterialExpressionMultiply, shade, vein, -950, 120)
    green = op(mat, unreal.MaterialExpressionMultiply, palette, shade, -600, -60)
    # 枯叶：叶片自带标记，簇也会让一部分区域整体偏黄
    dry_mask = dry
    dry_c = op(mat, unreal.MaterialExpressionMultiply, vec(mat, (0.125, 0.110, 0.025), -900, 480), shade, -700, 480)
    albedo = lerp(mat, green, dry_c, dry_mask, -350, 200)
    # 光泽沿叶长：根粗糙、尖光滑；远处变粗糙以压高光闪烁
    depth = node(mat, unreal.MaterialExpressionPixelDepth, -900, 900)
    ratio = op(mat, unreal.MaterialExpressionDivide, depth, const(mat, 2500, -900, 960), -750, 900)
    far = node(mat, unreal.MaterialExpressionSaturate, -600, 900)
    link(ratio, '', far, '')
    rough = lerp(mat, const(mat, 0.78, -900, 780), const(mat, 0.42, -900, 830), grad, -700, 800)
    rough = lerp(mat, rough, const(mat, 0.85, -600, 980), far, -450, 850)
    ao = lerp(mat, const(mat, 0.35, -700, 1050), const(mat, 1.0, -700, 1100), grad, -500, 1050)
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 0, 200)
    slab.set_editor_property('sub_surface_type', unreal.MaterialSubSurfaceType.MSS_TWO_SIDED_WRAP)
    link(albedo, '', slab, 'Diffuse Albedo')
    link(rough, '', slab, 'Roughness')
    link(vec(mat, (0.04, 0.04, 0.04), -200, 450), '', slab, 'F0')
    link(vec(mat, (0.05, 0.10, 0.015), -200, 500), '', slab, 'SSS MFP')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    assert LIB.connect_material_property(ao, '', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    # 掠射角撑宽：叶片侧对镜头时沿叶宽方向（UV 的 U = 切线方向）外推，叶尖处减弱
    tangent = node(mat, unreal.MaterialExpressionVertexTangentWS, -1200, 1300)
    nws = node(mat, unreal.MaterialExpressionVertexNormalWS, -1200, 1400)
    cam_pos = node(mat, unreal.MaterialExpressionCameraPositionWS, -1500, 1480)
    vtx_pos = node(mat, unreal.MaterialExpressionWorldPosition, -1500, 1560)
    to_cam = op(mat, unreal.MaterialExpressionSubtract, cam_pos, vtx_pos, -1350, 1500)
    cam = node(mat, unreal.MaterialExpressionNormalize, -1200, 1480)
    link(to_cam, '', cam, '')
    dot = node(mat, unreal.MaterialExpressionDotProduct, -1050, 1420)
    link(nws, '', dot, 'A'); link(cam, '', dot, 'B')
    facing = node(mat, unreal.MaterialExpressionAbs, -900, 1420)
    link(dot, '', facing, '')
    edge = op(mat, unreal.MaterialExpressionSubtract, const(mat, 1.0, -900, 1500), facing, -750, 1450)
    edge = op(mat, unreal.MaterialExpressionMultiply, edge, edge, -600, 1450)
    side = op(mat, unreal.MaterialExpressionMultiply, across, const(mat, 2.0, -1050, 1250), -900, 1250)
    side = op(mat, unreal.MaterialExpressionSubtract, side, const(mat, 1.0, -900, 1320), -750, 1250)
    taper = op(mat, unreal.MaterialExpressionSubtract, const(mat, 1.0, -750, 1550), along, -600, 1550)
    amount = op(mat, unreal.MaterialExpressionMultiply, edge, taper, -450, 1480)
    amount = op(mat, unreal.MaterialExpressionMultiply, amount, side, -300, 1400)
    amount = op(mat, unreal.MaterialExpressionMultiply, amount, const(mat, 1.6, -450, 1600), -150, 1450)
    wpo = op(mat, unreal.MaterialExpressionMultiply, tangent, amount, 0, 1350)
    # 剔除过渡带内把草丛缩回根部（不改 Masked，保住 early-Z）
    local = node(mat, unreal.MaterialExpressionLocalPosition, -700, 1800)
    to_world = node(mat, unreal.MaterialExpressionTransform, -500, 1800,
                    transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL,
                    transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    link(local, '', to_world, '')
    gone = node(mat, unreal.MaterialExpressionOneMinus, -500, 1950)
    link(node(mat, unreal.MaterialExpressionPerInstanceFadeAmount, -700, 1950), '', gone, '')
    shrink = op(mat, unreal.MaterialExpressionMultiply, to_world, gone, -300, 1850)
    shrink = op(mat, unreal.MaterialExpressionMultiply, shrink, const(mat, -1.0, -300, 1950), -150, 1850)
    wpo = op(mat, unreal.MaterialExpressionAdd, wpo, shrink, 50, 1500)
    assert LIB.connect_material_property(wpo, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    LIB.layout_material_expressions(mat)
    compile_check(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    note('material M_PampasGrassBlade (clump colour, gloss along blade, vein, AO, grazing widen)')
    return mat


def terrain_material(far_a, far_b):
    """近处草地底色（被植被覆盖），远处（植被裁剪后）换成原版俯视芒草田贴图，两张不同尺度混合以打散平铺。"""
    mat = check_owner('/Game/GoT/Pampas/Materials/M_PampasTerrain')
    assert mat, 'run ue_pampas_v2_setup.py first'
    LIB.delete_all_material_expressions(mat)
    world = node(mat, unreal.MaterialExpressionWorldPosition, -2000, 0)
    xy = node(mat, unreal.MaterialExpressionComponentMask, -1800, 0, r=True, g=True, b=False, a=False)
    link(world, '', xy, '')
    uv_a = op(mat, unreal.MaterialExpressionDivide, xy, const(mat, 700, -1800, 80), -1600, 0)
    uv_b = op(mat, unreal.MaterialExpressionDivide, xy, const(mat, 1900, -1800, 160), -1600, 120)
    far1 = node(mat, unreal.MaterialExpressionTextureSample, -1400, 0, texture=far_a)
    link(uv_a, '', far1, 'UVs')
    far2 = node(mat, unreal.MaterialExpressionTextureSample, -1400, 250, texture=far_b)
    link(uv_b, '', far2, 'UVs')
    macro = node(mat, unreal.MaterialExpressionNoise, -1400, 500, scale=0.0004, levels=4, output_min=0, output_max=1,
                 noise_function=unreal.NoiseFunction.NOISEFUNCTION_GRADIENT_ALU)
    link(world, '', macro, 'Position')
    far = lerp(mat, far1, far2, macro, -1150, 100)
    # 2026-11-07：远景穗由芒草远层几何提供（画到 1 km），地表只露在穗之间 → 深绿底，贴图亮度只做明暗起伏。
    # 旧做法把米色贴图提亮当颜色（线性反照率约 0.6），90 m 外一整片发白。同 Tools/ue_pampas_far_field.py。
    far_lum = node(mat, unreal.MaterialExpressionDotProduct, -1000, 100)
    link(far, '', far_lum, 'A'); link(vec(mat, (0.2126, 0.7152, 0.0722), -1150, 200), '', far_lum, 'B')
    shade = op(mat, unreal.MaterialExpressionMultiply, far_lum, const(mat, 0.55, -1000, 200), -850, 100)
    shade = op(mat, unreal.MaterialExpressionAdd, shade, const(mat, 0.72, -850, 200), -700, 100)
    near = lerp(mat, vec(mat, (0.035, 0.060, 0.012), -1150, 350), vec(mat, (0.055, 0.075, 0.018), -1150, 420), macro, -1000, 380)
    far = lerp(mat, vec(mat, (0.050, 0.068, 0.020), -1000, 250), vec(mat, (0.075, 0.085, 0.032), -1000, 300), macro, -850, 250)
    far = op(mat, unreal.MaterialExpressionMultiply, far, shade, -550, 150)
    depth = node(mat, unreal.MaterialExpressionPixelDepth, -1150, 560)
    dist = op(mat, unreal.MaterialExpressionSubtract, depth, const(mat, 4000, -1150, 640), -1000, 560)
    ratio = op(mat, unreal.MaterialExpressionDivide, dist, const(mat, 6000, -1000, 640), -850, 560)
    dist = node(mat, unreal.MaterialExpressionSaturate, -700, 560)
    link(ratio, '', dist, '')
    grass = lerp(mat, near, far, dist, -550, 250)
    normal_ws = node(mat, unreal.MaterialExpressionVertexNormalWS, -1150, 760)
    nz = node(mat, unreal.MaterialExpressionComponentMask, -1000, 760, r=False, g=False, b=True, a=False)
    link(normal_ws, '', nz, '')
    steep = node(mat, unreal.MaterialExpressionSmoothStep, -800, 760)
    link(const(mat, 0.86, -1000, 820), '', steep, 'Min'); link(const(mat, 0.66, -1000, 870), '', steep, 'Max'); link(nz, '', steep, 'Value')
    rock = vec(mat, (0.28, 0.28, 0.27), -800, 880)
    low = node(mat, unreal.MaterialExpressionSmoothStep, -800, 980)       # 海平面附近转为礁石/沙
    zc = node(mat, unreal.MaterialExpressionComponentMask, -1000, 980, r=False, g=False, b=True, a=False)
    link(world, '', zc, '')
    link(const(mat, -2600, -1000, 1040), '', low, 'Min'); link(const(mat, -3300, -1000, 1090), '', low, 'Max'); link(zc, '', low, 'Value')
    base = lerp(mat, grass, rock, steep, -350, 400)
    base = lerp(mat, base, vec(mat, (0.20, 0.18, 0.15), -500, 1000), low, -200, 500)
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 50, 300)
    link(base, '', slab, 'Diffuse Albedo')
    link(const(mat, 0.9, -200, 650), '', slab, 'Roughness')
    link(vec(mat, (0.04, 0.04, 0.04), -200, 700), '', slab, 'F0')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    LIB.layout_material_expressions(mat)
    compile_check(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    note('material M_PampasTerrain (far pampas field texture)')


def sea_material():
    mat = owned('M_PampasSea', '/Game/GoT/Pampas/Materials', unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(mat)
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 0, 0)
    link(vec(mat, (0.010, 0.035, 0.060), -300, 0), '', slab, 'Diffuse Albedo')
    link(const(mat, 0.12, -300, 100), '', slab, 'Roughness')
    link(vec(mat, (0.02, 0.02, 0.02), -300, 200), '', slab, 'F0')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    compile_check(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    return mat


# ---------- 关卡 ----------
def find(label):
    return next((a for a in ACTORS.get_all_level_actors() if a.get_actor_label() == label), None)


def ensure(cls, label, folder, location=(0, 0, 0)):
    actor = find(label)
    if actor is None:
        actor = ACTORS.spawn_actor_from_class(cls, unreal.Vector(*location))
        assert actor, label
        actor.set_actor_label(label)
        actor.set_editor_property('tags', ['GoTPampas'])
    actor.set_folder_path(folder)
    return actor


def sea_and_boundary(sea_mat):
    plane = unreal.load_asset('/Engine/BasicShapes/Plane.Plane')
    sea = ensure(unreal.StaticMeshActor, 'Pampas_Sea', 'GoT_Pampas/Environment', (0, 0, -3500))
    sea.set_editor_property('is_spatially_loaded', False)
    sea.set_actor_location(unreal.Vector(0, 0, -3500), False, False)
    sea.set_actor_scale3d(unreal.Vector(60000, 60000, 1))     # 60 km
    c = sea.static_mesh_component
    c.set_static_mesh(plane)
    c.set_material(0, sea_mat)
    c.set_collision_profile_name('NoCollision')
    c.set_editor_property('cast_shadow', False)
    cube = unreal.load_asset('/Engine/BasicShapes/Cube.Cube')
    half, height = PLAY_HALF_CM, 30000
    length = 2 * half + 200
    for label, loc, scale in [('Pampas_Boundary_E', (half + 50, 0), (1, length / 100, height / 100)),
                              ('Pampas_Boundary_W', (-half - 50, 0), (1, length / 100, height / 100)),
                              ('Pampas_Boundary_N', (0, half + 50), (length / 100, 1, height / 100)),
                              ('Pampas_Boundary_S', (0, -half - 50), (length / 100, 1, height / 100))]:
        a = ensure(unreal.StaticMeshActor, label, 'GoT_Pampas/Gameplay')
        a.set_editor_property('is_spatially_loaded', False)
        a.set_actor_location(unreal.Vector(loc[0], loc[1], 0), False, False)
        a.set_actor_scale3d(unreal.Vector(*scale))
        bc = a.static_mesh_component
        bc.set_static_mesh(cube)
        bc.set_collision_profile_name('BlockAll')
        bc.set_visibility(False)
        bc.set_editor_property('cast_shadow', False)
        a.set_actor_hidden_in_game(True)
    note('sea plane at -35 m; boundary +-280 m')


def descriptor(mesh, start, end, shadow=False):
    d = unreal.PCGSoftISMComponentDescriptor()
    d.set_editor_property('static_mesh', mesh)
    d.set_editor_property('component_class', unreal.HierarchicalInstancedStaticMeshComponent)
    # 只有画到 1 km 的芒草远层进 HLOD（块卸载后远景由 HLOD 实例接管）；近层与草叶不进
    for k, v in dict(instance_start_cull_distance=start, instance_end_cull_distance=end, cast_shadow=shadow,
                     affect_distance_field_lighting=False, visible_in_ray_tracing=False, enable_density_scaling=True,
                     include_in_hlod=end >= 90000).items():
        try:
            d.set_editor_property(k, v)
        except Exception as error:
            warn(f'descriptor.{k}: {error}')
    try:
        d.set_editor_property('collision_profile', unreal.CollisionProfileName('NoCollision'))
    except Exception as error:
        warn(f'descriptor.collision_profile: {error}')
    return d


def layer(graph, x, y, cell, jitter, yaw_range, scale_range, entries, start, end, shadow=False):
    grid, s = graph.add_node_of_type(unreal.PCGCreatePointsGridSettings)
    s.set_editor_property('grid_extents', unreal.Vector(VEG_HALF_CM, VEG_HALF_CM, 0))
    s.set_editor_property('cell_size', unreal.Vector(cell, cell, 100))
    s.set_editor_property('coordinate_space', unreal.PCGCoordinateSpace.LOCAL_COMPONENT)
    s.set_editor_property('cull_points_outside_volume', True)
    grid.set_node_position(x, y)
    jit, s = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
    s.set_editor_property('offset_min', unreal.Vector(-jitter, -jitter, 20000))
    s.set_editor_property('offset_max', unreal.Vector(jitter, jitter, 20000))
    s.set_editor_property('absolute_offset', True)
    jit.set_node_position(x + 250, y)
    ray, s = graph.add_node_of_type(unreal.PCGWorldRaycastElementSettings)
    s.set_editor_property('raycast_mode', unreal.PCGWorldRaycastMode.NORMALIZED_WITH_LENGTH)
    s.set_editor_property('ray_direction', unreal.Vector(0, 0, -1))
    s.set_editor_property('ray_length', 40000)
    s.set_editor_property('unbounded', True)
    query = s.get_editor_property('world_query_params')
    query.set_editor_property('trace_complex', True)
    try:
        query.set_editor_property('ignore_landscape_hits', False)
    except Exception as error:
        warn(f'query.ignore_landscape_hits: {error}')
    try:
        current = query.get_editor_property('select_landscape_hits')
        enum_cls = type(current)
        members = {m: getattr(enum_cls, m) for m in dir(enum_cls) if m.isupper()}
        pick = next((v for k, v in members.items() if 'INCLUDE' in k), None)
        if pick is not None:
            query.set_editor_property('select_landscape_hits', pick)
        STATE['report']['landscape_hit_modes'] = dict(before=str(current), options=list(members), chosen=str(pick))
    except Exception as error:
        warn(f'query.select_landscape_hits: {error}')
    s.set_editor_property('world_query_params', query)
    ray.set_node_position(x + 500, y)
    tr, s = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
    s.set_editor_property('rotation_min', unreal.Rotator(yaw=yaw_range[0]))
    s.set_editor_property('rotation_max', unreal.Rotator(yaw=yaw_range[1]))
    s.set_editor_property('absolute_rotation', True)
    s.set_editor_property('scale_min', unreal.Vector(scale_range[0], scale_range[0], scale_range[0]))
    s.set_editor_property('scale_max', unreal.Vector(scale_range[1], scale_range[1], scale_range[1]))
    s.set_editor_property('offset_min', unreal.Vector(0, 0, -3))
    s.set_editor_property('offset_max', unreal.Vector(0, 0, -3))
    tr.set_node_position(x + 750, y)
    sp, s = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
    selector = s.get_editor_property('mesh_selector_parameters')
    items = []
    for mesh, weight in entries:
        e = unreal.PCGMeshSelectorWeightedEntry()
        e.set_editor_property('descriptor', descriptor(mesh, start, end, shadow))
        e.set_editor_property('weight', weight)
        items.append(e)
    selector.set_editor_property('mesh_entries', items)
    sp.set_node_position(x + 1000, y)
    for a, b, pin in [(grid, jit, 'In'), (jit, ray, 'Origins'), (ray, tr, 'In'), (tr, sp, 'In')]:
        assert graph.add_edge(a, 'Out', b, pin), (a, b, pin)


def pcg_graph(meshes):
    graph = owned('PCG_PampasField', '/Game/GoT/Pampas/PCG', unreal.PCGGraph, unreal.PCGGraphFactory())
    for n in list(graph.get_editor_property('nodes')):
        graph.remove_node(n)
    # 按距离分层的密度（原版远处 tile 翻倍、四片留一片的思路）：远层稀疏、可见远；近层补足近处密度。
    pampas = [(meshes['SM_Pampas_A'], 5), (meshes['SM_Pampas_B'], 3), (meshes['SM_Pampas_C'], 2)]
    # 远层画到 1 km（2026-11-07 远景发白修复）：截帧中芒草穗一直画到海边，远处由 LOD3 承担
    layer(graph, 0, 0, 200, 90, (WIND_YAW - 30, WIND_YAW + 30), (0.95, 1.25), pampas, 90000, 100000, shadow=False)
    layer(graph, 0, 400, 115, 50, (WIND_YAW - 30, WIND_YAW + 30), (0.85, 1.2), pampas, 2200, 4000, shadow=True)
    # 2026-11-07 P5: the two grass-blade layers are gone; grass is the GPU Bezier grass (AGoTGrassActor, Tools/ue_grass_setup.py)
    unreal.EditorAssetLibrary.save_loaded_asset(graph)
    note('PCG graph: pampas far 2.0 m/90 m + near 1.15 m/40 m (shadow); grass = GPU grass')
    return graph


TILES = 5                 # 植被分块：5x5 个 PCG 体积，每块 136 m，各自作为空间加载的 World Partition Actor


def pcg_volumes(graph):
    """手动分块：每块一个非分区 PCG 体积（分区组件在脚本化编辑器中不执行本地生成，见 Tools/state/pampas_pcg_diag.json）。"""
    for a in ACTORS.get_all_level_actors():
        if a.get_actor_label() == 'Pampas_PCG_Field' or a.get_class().get_name() == 'PCGPartitionActor':
            ACTORS.destroy_actor(a)
    tile = 2 * VEG_HALF_CM / TILES
    comps = []
    for ix in range(TILES):
        for iy in range(TILES):
            cx, cy = -VEG_HALF_CM + tile * (ix + 0.5), -VEG_HALF_CM + tile * (iy + 0.5)
            vol = ensure(unreal.PCGVolume, f'Pampas_PCG_{ix}_{iy}', 'GoT_Pampas/Vegetation', (cx, cy, 0))
            vol.set_actor_location(unreal.Vector(cx, cy, 0), False, False)
            vol.set_actor_scale3d(unreal.Vector(tile / 200, tile / 200, 120))
            vol.set_editor_property('is_spatially_loaded', True)
            vol.set_editor_property('hlod_layer', unreal.load_asset('/Game/GoT/Maps/L_Pampas_HLODLayer_Instanced'))
            comp = vol.pcg_component
            comp.set_graph(graph)
            for k, v in dict(seed=20261107 + ix * 10 + iy, generation_trigger=unreal.PCGComponentGenerationTrigger.GENERATE_ON_DEMAND,
                             regenerate_in_editor=False, is_component_partitioned=False).items():
                comp.set_editor_property(k, v)
            comps.append(comp)
    note(f'{len(comps)} PCG tiles of {tile / 100:.0f} m')
    return comps


def grade():
    """对应原版最终调色：曝光略降，饱和度与对比度提高（截帧中色调映射前偏淡、最终输出鲜艳）。"""
    post = find('Pampas_PostProcess')
    pp = post.get_editor_property('settings')
    # 2026-11-07 起整体氛围按 Ref.png 调整，数值以 Tools/ue_pampas_atmosphere.py 为准（重跑本脚本后再跑一次它）
    for k, v in dict(auto_exposure_min_brightness=14.2, auto_exposure_max_brightness=14.2,
                     color_saturation=unreal.Vector4(0.95, 0.95, 0.95, 1.0), color_contrast=unreal.Vector4(0.95, 0.95, 0.95, 1.0)).items():
        pp.set_editor_property('override_' + k, True)
        pp.set_editor_property(k, v)
    for k, v in dict(local_exposure_highlight_contrast_scale=0.8, local_exposure_shadow_contrast_scale=0.8,
                     local_exposure_blurred_luminance_blend=0.6).items():
        try:
            pp.set_editor_property('override_' + k, True)
            pp.set_editor_property(k, v)
        except Exception as error:
            warn(f'post.{k}: {error}')
    post.set_editor_property('settings', pp)
    note('grade: EV 14.8, saturation 1.25, contrast 1.1, local exposure 0.8/0.8 blend 0.6')
    sun = find('Pampas_Sun').light_component
    for k, v in dict(contact_shadow_length=0.08, contact_shadow_length_in_ws=False,
                     contact_shadow_casting_intensity=1.0, contact_shadow_non_casting_intensity=1.0).items():
        try:
            sun.set_editor_property(k, v)
        except Exception as error:
            warn(f'sun.{k}: {error}')
    note('sun contact shadows on (non-shadow-casting grass also receives/casts screen-space shadow)')
    cloud = find('Pampas_Cloud').get_component_by_class(unreal.VolumetricCloudComponent)
    for k, v in dict(view_sample_count_scale=0.5, shadow_view_sample_count_scale=0.5).items():
        try:
            cloud.set_editor_property(k, v)
        except Exception as error:
            warn(f'cloud.{k}: {error}')
    note('volumetric cloud half samples')


def build():
    atlas = import_texture(TEX_DIR / 'pampas_d.png', 'T_PampasAtlas_D')
    atlas.set_editor_property('do_scale_mips_for_alpha_coverage', True)          # 远处 mip 保住穗的覆盖率
    atlas.set_editor_property('alpha_coverage_thresholds', unreal.Vector4(0, 0, 0, 0.4))
    unreal.EditorAssetLibrary.save_loaded_asset(atlas)
    far_a = import_texture(TEX_DIR / 'whr_foliage_jw_pampas_001.png', 'T_PampasField_Far_A')
    far_b = import_texture(TEX_DIR / 'whr_foliage_jw_pampas_002.png', 'T_PampasField_Far_B')
    ngt = import_texture(TEX_DIR / 'pampas_ngt_bc7.png', 'T_PampasAtlas_NGT', srgb=False)
    foliage = foliage_material(atlas, ngt)
    foliage = pampas_pbr_instance(foliage)
    blade = blade_material()
    terrain_material(far_a, far_b)
    sea = sea_material()
    meshes = import_meshes(dict(foliage=foliage, blades=blade))
    graph = pcg_graph(meshes)
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    STATE['world'] = world
    descs = unreal.WorldPartitionBlueprintLibrary.get_actor_descs()
    unreal.WorldPartitionBlueprintLibrary.load_actors([d.get_editor_property('guid') for d in descs])
    sea_and_boundary(sea)
    grade()
    if unreal.EditorAssetLibrary.does_directory_exist('/Game/GoT/Pampas/PCG/Diag'):
        unreal.EditorAssetLibrary.delete_directory('/Game/GoT/Pampas/PCG/Diag')
    comps = pcg_volumes(graph)
    assert unreal.EditorLoadingAndSavingUtils.save_map(world, MAP)
    for comp in comps:
        comp.generate_local(True)
    STATE['pcg'] = comps
    STATE['gen_start'] = time.monotonic()
    STATE['callback'] = unreal.register_slate_post_tick_callback(tick)
    unreal.EditorPythonScripting.set_keep_python_script_alive(True)


def instance_stats():
    stats = dict(components=0, instances=0, partition_actors=0, by_mesh={})
    for a in ACTORS.get_all_level_actors():
        name = a.get_class().get_name()
        if name != 'PCGVolume':
            continue
        stats['partition_actors'] += 1
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            n = c.get_instance_count()
            stats['components'] += 1
            stats['instances'] += n
            m = c.static_mesh.get_name() if c.static_mesh else '?'
            stats['by_mesh'][m] = stats['by_mesh'].get(m, 0) + n
    return stats


def local_components():
    comps = []
    for a in ACTORS.get_all_level_actors():
        if a.get_class().get_name() == 'PCGPartitionActor':
            comps += list(a.get_components_by_class(unreal.PCGComponent))
    return comps


def tick(delta):
    if STATE.get('busy'):
        return
    STATE['busy'] = True
    try:
        now = time.monotonic()
        if now - STATE['gen_start'] > 1500:
            raise RuntimeError('PCG generation timeout')
        if now - STATE['gen_start'] > 240 and STATE.get('prev_instances', 0) == 0 and STATE.get('diagnosed'):
            raise RuntimeError('no instances after 240 s; see local_state')
        if now - STATE.get('last', 0) > 10:
            STATE['last'] = now
            s = instance_stats()
            unreal.log(f"PAMPAS_VEG progress {s['instances']} instances, {s['partition_actors']} partition actors")
            done = sum(1 for c in STATE['pcg'] if c.get_editor_property('generated'))
            unreal.log(f'PAMPAS_VEG tiles generated {done}/{len(STATE["pcg"])}')
            if done < len(STATE['pcg']):
                STATE['prev_instances'] = None
                return
            if s['instances'] == 0 and now - STATE['gen_start'] > 90:
                STATE['diagnosed'] = True
            stable = s['instances'] > 0 and s['instances'] == STATE.get('prev_instances')
            STATE['prev_instances'] = s['instances']
            if stable and now - STATE['gen_start'] > 40:
                STATE['report']['pcg'] = s
                unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
                assert unreal.EditorLoadingAndSavingUtils.save_map(STATE['world'], MAP)
                note('saved after PCG generation')
                finish(True)
    except Exception:
        finish(False)
    finally:
        STATE['busy'] = False


def finish(passed):
    rep = STATE['report']
    rep['passed'] = passed
    rep['elapsed_s'] = round(time.monotonic() - STATE['start'], 1)
    if not passed:
        rep['error'] = traceback.format_exc()
        unreal.log_error(rep['error'])
    REPORT.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=str), 'utf-8')
    if STATE.get('callback'):
        unreal.unregister_slate_post_tick_callback(STATE['callback'])
    unreal.EditorPythonScripting.set_keep_python_script_alive(False)
    unreal.SystemLibrary.quit_editor()


try:
    build()
except Exception:
    finish(False)
