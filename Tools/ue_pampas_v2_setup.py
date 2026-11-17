"""建立 L_Pampas（依据三帧截帧重做的场景渲染关卡）的地图骨架与地形材质。

在完整编辑器中运行（-ExecutePythonScript），结束后自动退出。不修改旧 L_PampasDemo。
- 新建 World Partition 地图 /Game/GoT/Maps/L_Pampas，游戏模式用第三人称模板 BP_ThirdPersonGameMode。
- 晴天光照基线：太阳、SkyAtmosphere、SkyLight（实时捕获）、VolumetricCloud、淡高度雾、固定曝光后期。
- 出生点、三个参考相机占位。
- 地形材质 M_PampasTerrain：按坡度/高度/宏观噪声自动混合草地、土、岩，不需要绘制图层。
Landscape 本体由用户在编辑器中按高度图导入（见 Docs/Research/05_截帧分析.md 的操作说明）。
"""
import json
import time
import traceback
from pathlib import Path
import unreal

ROOT = Path('D:/HOU/Ghost of Tsushima')
MAP = '/Game/GoT/Maps/L_Pampas'
OWNER = 'Pampas_20261107'
REPORT = ROOT / 'Tools/state/pampas_v2_setup.json'
TERRAIN = json.loads((ROOT / 'Extracted/_converted/pampas_v2_terrain/terrain.json').read_text('utf-8'))
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
LEVELS = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
LIB = unreal.MaterialEditingLibrary
STATE = dict(report=dict(actions=[], warnings=[]))


def note(msg):
    STATE['report']['actions'].append(msg)
    unreal.log('PAMPAS_SETUP ' + msg)


def owned(name, folder, cls, factory):
    path = f'{folder}/{name}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        obj = unreal.load_asset(path)
        assert unreal.EditorAssetLibrary.get_metadata_tag(obj, 'GoTOwner') == OWNER, path
        return obj
    obj = ASSETS.create_asset(name, folder, cls, factory)
    assert obj, path
    unreal.EditorAssetLibrary.set_metadata_tag(obj, 'GoTOwner', OWNER)
    return obj


def node(mat, cls, x=0, y=0, **props):
    n = LIB.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def link(a, out, b, pin):
    if LIB.connect_material_expressions(a, out, b, pin):
        return
    names = [str(n) for n in LIB.get_material_expression_input_names(b)]
    alt = next((n for n in names if n.lower().startswith(pin.lower()[:3])), names[0] if names else '')
    assert LIB.connect_material_expressions(a, out, b, alt), (a, out, b, pin, names)
    STATE['report']['warnings'].append(f'pin {pin} -> {alt} on {b.get_class().get_name()} {names}')


def color(mat, rgb, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(*rgb, 1))


def scalar(mat, v, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant, x, y, r=v)


def lerp(mat, a, b, alpha, x=0, y=0):
    n = node(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
    link(a, '', n, 'A'); link(b, '', n, 'B'); link(alpha, '', n, 'Alpha')
    return n


def terrain_material():
    """草地为主；坡度大处转土/岩；宏观噪声做大块明暗与色相变化。颜色取自截帧 G-Buffer 反照率的目测近似。"""
    mat = owned('M_PampasTerrain', '/Game/GoT/Pampas/Materials', unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(mat)
    world = node(mat, unreal.MaterialExpressionWorldPosition, -1600, 0)
    macro = node(mat, unreal.MaterialExpressionNoise, -1200, 0, scale=0.00035, levels=4, output_min=0, output_max=1,
                 noise_function=unreal.NoiseFunction.NOISEFUNCTION_GRADIENT_ALU)
    link(world, '', macro, 'Position')
    detail = node(mat, unreal.MaterialExpressionNoise, -1200, 250, scale=0.004, levels=3, output_min=0, output_max=1,
                  noise_function=unreal.NoiseFunction.NOISEFUNCTION_GRADIENT_ALU)
    link(world, '', detail, 'Position')
    grass_a = color(mat, (0.105, 0.155, 0.030), -900, -300)   # 截帧草的橄榄绿（线性空间近似）
    grass_b = color(mat, (0.150, 0.170, 0.045), -900, -150)   # 偏黄绿的斑块
    grass = lerp(mat, grass_a, grass_b, macro, -650, -250)
    soil = color(mat, (0.150, 0.105, 0.060), -900, 50)
    rock = color(mat, (0.300, 0.300, 0.290), -900, 200)
    normal_ws = node(mat, unreal.MaterialExpressionVertexNormalWS, -1400, 450)
    nz = node(mat, unreal.MaterialExpressionComponentMask, -1200, 450, r=False, g=False, b=True, a=False)
    link(normal_ws, '', nz, '')
    slope_soil = node(mat, unreal.MaterialExpressionSmoothStep, -900, 400)
    link(scalar(mat, 0.93, -1100, 380), '', slope_soil, 'Min'); link(scalar(mat, 0.80, -1100, 420), '', slope_soil, 'Max')
    link(nz, '', slope_soil, 'Value')
    slope_rock = node(mat, unreal.MaterialExpressionSmoothStep, -900, 550)
    link(scalar(mat, 0.80, -1100, 530), '', slope_rock, 'Min'); link(scalar(mat, 0.62, -1100, 570), '', slope_rock, 'Max')
    link(nz, '', slope_rock, 'Value')
    soil_mix = lerp(mat, grass, soil, slope_soil, -450, 0)
    base = lerp(mat, soil_mix, rock, slope_rock, -250, 100)
    shade = node(mat, unreal.MaterialExpressionLinearInterpolate, -250, 300)
    link(scalar(mat, 0.82, -450, 280), '', shade, 'A'); link(scalar(mat, 1.08, -450, 320), '', shade, 'B'); link(detail, '', shade, 'Alpha')
    albedo = node(mat, unreal.MaterialExpressionMultiply, -50, 150)
    link(base, '', albedo, 'A'); link(shade, '', albedo, 'B')
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 200, 150)
    link(albedo, '', slab, 'Diffuse Albedo')
    link(scalar(mat, 0.9, 0, 350), '', slab, 'Roughness')
    link(color(mat, (0.04, 0.04, 0.04), 0, 420), '', slab, 'F0')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    LIB.layout_material_expressions(mat)
    LIB.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    note('material ' + mat.get_path_name())
    return mat


def spawn(cls, label, folder, location=(0, 0, 0), rotation=(0, 0, 0)):
    actor = ACTORS.spawn_actor_from_class(cls, unreal.Vector(*location), unreal.Rotator(pitch=rotation[0], yaw=rotation[1], roll=rotation[2]))
    assert actor, label
    actor.set_actor_label(label)
    actor.set_folder_path(folder)
    actor.set_editor_property('is_spatially_loaded', False)
    actor.set_editor_property('tags', ['GoTPampas'])
    return actor


def build():
    material = terrain_material()
    if unreal.EditorAssetLibrary.does_asset_exist(MAP):
        raise RuntimeError(f'{MAP} 已存在：本脚本只用于首次建立，避免覆盖用户导入的 Landscape')
    assert LEVELS.new_level(MAP, True), 'new_level failed'
    world = unreal.EditorLevelLibrary.get_editor_world()
    settings = world.get_world_settings()
    assert settings.get_editor_property('world_partition'), 'not a partitioned world'
    settings.set_editor_property('default_game_mode', unreal.load_class(None, '/Game/ThirdPerson/Blueprints/BP_ThirdPersonGameMode.BP_ThirdPersonGameMode_C'))
    sun = spawn(unreal.DirectionalLight, 'Pampas_Sun', 'GoT_Pampas/LightingAndSky', rotation=(-52, 130, 0))
    lc = sun.light_component
    lc.set_mobility(unreal.ComponentMobility.MOVABLE)
    for k, v in dict(atmosphere_sun_light=True, intensity=75000.0, use_temperature=True, temperature=5900.0,
                     light_source_angle=0.535, dynamic_shadow_distance_movable_light=20000.0).items():
        try:
            lc.set_editor_property(k, v)
        except Exception as error:
            STATE['report']['warnings'].append(f'sun.{k}: {error}')
    spawn(unreal.SkyAtmosphere, 'Pampas_SkyAtmosphere', 'GoT_Pampas/LightingAndSky')
    sky = spawn(unreal.SkyLight, 'Pampas_SkyLight', 'GoT_Pampas/LightingAndSky')
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    sky.light_component.set_editor_property('real_time_capture', True)
    cloud = spawn(unreal.VolumetricCloud, 'Pampas_Cloud', 'GoT_Pampas/LightingAndSky')
    cloud.get_component_by_class(unreal.VolumetricCloudComponent).set_material(
        unreal.load_asset('/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst'))
    fog = spawn(unreal.ExponentialHeightFog, 'Pampas_HeightFog', 'GoT_Pampas/LightingAndSky', (0, 0, -3500))
    fc = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
    fc.set_fog_density(0.0015)
    fc.set_fog_height_falloff(0.05)
    post = spawn(unreal.PostProcessVolume, 'Pampas_PostProcess', 'GoT_Pampas/LightingAndSky')
    post.set_editor_property('unbound', True)
    pp = post.get_editor_property('settings')
    for k, v in dict(auto_exposure_min_brightness=14.0, auto_exposure_max_brightness=14.0, bloom_intensity=0.2).items():
        pp.set_editor_property('override_' + k, True)
        pp.set_editor_property(k, v)
    post.set_editor_property('settings', pp)
    sx, sy, sz = TERRAIN['spawn_m']
    spawn(unreal.PlayerStart, 'Pampas_PlayerStart', 'GoT_Pampas/Gameplay', (sx * 100, sy * 100, sz * 100 + 200), (0, 40, 0))
    for i, (x, y, yaw) in enumerate([(-60, -40, 40), (40, 60, 20), (-30, 120, 250)]):
        cam = spawn(unreal.CameraActor, f'Pampas_RefCamera_{i + 1}', 'GoT_Pampas/Cameras', (x * 100, y * 100, 2400), (-6, yaw, 0))
        cam.camera_component.set_editor_property('field_of_view', 72.0)
    assert unreal.EditorLoadingAndSavingUtils.save_map(world, MAP)
    note('saved ' + MAP)
    STATE['report'].update(passed=True, map=MAP, terrain_material=material.get_path_name(), terrain=TERRAIN)


try:
    build()
except Exception:
    STATE['report'].update(passed=False, error=traceback.format_exc())
    unreal.log_error(traceback.format_exc())
REPORT.write_text(json.dumps(STATE['report'], indent=2, ensure_ascii=False, default=str), 'utf-8')
unreal.SystemLibrary.quit_editor()
