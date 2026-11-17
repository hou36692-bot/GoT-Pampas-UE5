"""GPU grass + official wind content for L_Pampas (run in the open editor via remote execution; re-runnable).

  python -I Tools/mcp/ue_py.py Tools/ue_grass_setup.py

  1. textures  /Game/GoT/Grass/Textures: T_GoTGrass_TerrainHeight (G16, heightmap_1009.png, same source as the Landscape),
               T_GoTGrass_Kind (G8 kind index), T_GoTGrass_Height (G8 grass height) - Tools/build_grass_maps.py
  2. MPC_Wind  WindDir (dir.xy, base force), GustNoise (offset.xy, z, scale), GustShape (base, gain, mul, add), WindTime,
               Interact, Pampas/Tree (height, wind coef, bend rad, flutter freq), ConsumerPush, WindDebug
  3. RT_GoTInteraction: 256^2 RGBA16F with UAV (GPU interaction field, 100 m)  [截帧 100 m / 256^2]
  4. MF_GoTWind / MF_GoTWindDebug rebuilt on the shared shader include (3D Perlin from the capture, no noise texture)
  5. M_GoTGrass (Substrate, two-sided, usage flag of the grass vertex factory)
  6. AGoTGrassActor 'Pampas_GPUGrass' with the captured kind table (Captures/analysis/shaders_02/res3558_kinds.bin)
Wind model and evidence levels: GoTWindTypes.h / Shaders/Private/GoTWindCommon.ush.
"""
import json
import struct
from pathlib import Path
import unreal

ROOT = Path('D:/HOU/Ghost of Tsushima')
TERRAIN = ROOT / 'Extracted/_converted/pampas_v2_terrain'
KINDS_BIN = ROOT / 'Captures/analysis/shaders_02/res3558_kinds.bin'
OWNER = 'Pampas_20261107'
WIND = '/Game/GoT/Wind'
GRASS = '/Game/GoT/Grass'
INCLUDE = '/Plugin/GoTEnvironment/Private/GoTWindCommon.ush'
LIB = unreal.MaterialEditingLibrary
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
log, warns = [], []


def tag(obj):
    unreal.EditorAssetLibrary.set_metadata_tag(obj, 'GoTOwner', OWNER)


def owned(name, folder, cls, factory):
    path = f'{folder}/{name}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        obj = unreal.load_asset(path)
        assert unreal.EditorAssetLibrary.get_metadata_tag(obj, 'GoTOwner') == OWNER, path
        return obj
    obj = ASSETS.create_asset(name, folder, cls, factory)
    tag(obj)
    return obj


def setp(obj, **kw):
    for k, v in kw.items():
        try:
            obj.set_editor_property(k, v)
        except Exception as e:
            warns.append(f'{obj.get_name()}.{k}: {e}')


# ---------------------------------------------------------------- 1. textures
def import_map(png, name, nearest=False):
    task = unreal.AssetImportTask()
    setp(task, filename=str(TERRAIN / png), destination_path=f'{GRASS}/Textures', destination_name=name,
         automated=True, save=False, replace_existing=True)
    ASSETS.import_asset_tasks([task])
    tex = unreal.load_asset(f'{GRASS}/Textures/{name}')
    assert tex, name
    setp(tex, srgb=False, compression_settings=unreal.TextureCompressionSettings.TC_GRAYSCALE,
         mip_gen_settings=unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS, never_stream=True,
         address_x=unreal.TextureAddress.TA_CLAMP, address_y=unreal.TextureAddress.TA_CLAMP,
         filter=unreal.TextureFilter.TF_NEAREST if nearest else unreal.TextureFilter.TF_BILINEAR,
         lod_group=unreal.TextureGroup.TEXTUREGROUP_WORLD)   # 16-bit-data group turns G16/G8 into RGBA16F
    tag(tex)
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    log.append(f'{name}: {tex.blueprint_get_size_x()}x{tex.blueprint_get_size_y()}')
    return tex


# ---------------------------------------------------------------- 2/3. MPC + RT
MPC_PARAMS = [
    ('WindDir', (-0.940, -0.342, 1500.0, 1.0)),
    ('GustNoise', (0.0, 0.0, 0.0, 0.0004)),
    ('GustShape', (1500.0, 1.0, 1.0, 0.0)),
    ('WindDetailNoise', (37.0, 91.0, 17.0, 0.002)),
    ('WindResponse', (0.2, 0.2, 1.0, 0.25)),
    ('WindTime', (0.0, 0.0, 0.0, 0.0)),
    ('Interact', (0.0, 0.0, 1.0 / 10000.0, 0.0)),
    ('Pampas', (120.0, 0.65, 0.663, 1.0)),
    ('Tree', (1300.0, 0.3, 0.07, 1.6)),
    ('ConsumerPush', (0.873, 0.0, 0.0, 0.0)),
    ('WindDebug', (0.0, 0.8, 600.0, 0.0)),
    ('Grass', (80.0, 0.8, 60.0, 1.4)),        # legacy: only the retired PCG blade material (M_PampasGrassBlade) reads it
]
HISTORY_MPC_NAMES = ('WindDir', 'GustNoise', 'GustShape', 'WindDetailNoise', 'WindResponse',
                     'WindTime', 'Interact', 'Pampas', 'Tree', 'ConsumerPush')
MPC_PARAMS += [(name + 'Prev', dict(MPC_PARAMS)[name]) for name in HISTORY_MPC_NAMES]


def collection(preserve_existing=False):
    mpc = unreal.load_asset(f'{WIND}/MPC_Wind')
    existing = {str(p.get_editor_property('parameter_name')): p for p in mpc.get_editor_property('vector_parameters')}
    params = list(mpc.get_editor_property('vector_parameters')) if preserve_existing else []
    for name, v in MPC_PARAMS:
        p = existing.get(name) or unreal.CollectionVectorParameter()
        p.set_editor_property('parameter_name', name)
        if not preserve_existing or name not in existing:
            p.set_editor_property('default_value', unreal.LinearColor(*v))
        if not preserve_existing or name not in existing:
            params.append(p)
    mpc.set_editor_property('vector_parameters', params)
    unreal.EditorAssetLibrary.save_loaded_asset(mpc)
    log.append('MPC_Wind: ' + ', '.join(n for n, _ in MPC_PARAMS))
    return mpc


def field_target():
    rt = unreal.load_asset(f'{WIND}/RT_GoTInteraction')
    setp(rt, size_x=256, size_y=256, render_target_format=unreal.TextureRenderTargetFormat.RTF_RGBA16F,
         clear_color=unreal.LinearColor(0, 0, 0, 0), address_x=unreal.TextureAddress.TA_CLAMP,
         address_y=unreal.TextureAddress.TA_CLAMP, auto_generate_mips=False)   # bCanCreateUAV is set by UGoTWindSubsystem (not a UPROPERTY)
    unreal.EditorAssetLibrary.save_loaded_asset(rt)
    log.append('RT_GoTInteraction 256 RGBA16F')
    return rt


def previous_field_target():
    """只创建历史纹理；已有纹理必须保持与当前场相同的尺寸和格式。"""
    path = f'{WIND}/RT_GoTInteractionPrev'
    exists = unreal.EditorAssetLibrary.does_asset_exist(path)
    rt = owned('RT_GoTInteractionPrev', WIND, unreal.TextureRenderTarget2D, unreal.TextureRenderTargetFactoryNew())
    settings = dict(size_x=256, size_y=256, render_target_format=unreal.TextureRenderTargetFormat.RTF_RGBA16F,
                    clear_color=unreal.LinearColor(0, 0, 0, 0), address_x=unreal.TextureAddress.TA_CLAMP,
                    address_y=unreal.TextureAddress.TA_CLAMP, auto_generate_mips=False)
    if not exists:
        for name, value in settings.items():
            rt.set_editor_property(name, value)
        assert unreal.EditorAssetLibrary.save_loaded_asset(rt), 'Failed to save interaction history RT'
    else:
        for name in ('size_x', 'size_y', 'render_target_format'):
            assert rt.get_editor_property(name) == settings[name], ('Unexpected history RT format', name)
    return rt


# ---------------------------------------------------------------- 4. material functions
def fnode(func, cls, x, y, **props):
    n = LIB.create_material_expression_in_function(func, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def link(a, out, b, pin):
    assert LIB.connect_material_expressions(a, out, b, pin), (a.get_name(), out, b.get_name(), pin,
                                                              [str(n) for n in LIB.get_material_expression_input_names(b)])


def clear_function(func):
    for _ in range(10):
        if LIB.get_num_material_expressions_in_function(func) == 0:
            break
        LIB.delete_all_material_expressions_in_function(func)
    assert LIB.get_num_material_expressions_in_function(func) == 0, func.get_name()


def custom_node(create, owner, x, y, names, code, out_type, extra, desc, node=None):
    c = node or create(owner, unreal.MaterialExpressionCustom, x, y)
    ins = []
    for n in names:
        ci = unreal.CustomInput()
        ci.set_editor_property('input_name', n)
        ins.append(ci)
    c.set_editor_property('inputs', ins)
    c.set_editor_property('code', code)
    c.set_editor_property('output_type', out_type)
    c.set_editor_property('description', desc)
    c.set_editor_property('include_file_paths', [INCLUDE])
    outs = []
    for name, t in extra:
        o = unreal.CustomOutput()
        o.set_editor_property('output_name', name)
        o.set_editor_property('output_type', t)
        outs.append(o)
    c.set_editor_property('additional_outputs', outs)
    return c


# [适配] 网格没有逐茎枢轴：圆弧中心线弯曲整簇，横截面随中心线旋转。
# Theta 对整株恒定；0 < z < H 时 J = R diag(1, 1, s)，s = 1 - Theta/H * dot(Dir, Rel.xy)。
# z >= H 是末端切线延伸，s = 1；z <= 0 保持原状。调用者必须统一限制 Theta，保证 s > 0。
WIND_STEM_HLSL = r'''
float3 GoTStemArc(float3 Rel, float H, float Theta, float2 Dir, out float3 AxisAngle, out float NormalStretch)
{
    AxisAngle = float3(0, 0, 0);
    NormalStretch = 1.0;
    if (Rel.z <= 0.0) return Rel;
    float z = min(Rel.z, H);
    float a = Theta * z / H;
    float a2 = a * a;
    float sinc = abs(a) < 0.001 ? 1.0 - a2 / 6.0 + a2 * a2 / 120.0 : sin(a) / a;
    float cosc = abs(a) < 0.001 ? a * (0.5 - a2 / 24.0 + a2 * a2 / 720.0)
                               : 2.0 * sin(a * 0.5) * sin(a * 0.5) / a;
    float3 center = float3(Dir * (z * cosc), z * sinc);
    float3 axis = float3(-Dir.y, Dir.x, 0.0);
    float3 crossSection = float3(Rel.xy, 0.0);
    float3 rotated = crossSection * cos(a) + cross(axis, crossSection) * sin(a)
                   + axis * dot(axis, crossSection) * (2.0 * sin(a * 0.5) * sin(a * 0.5));
    center += max(Rel.z - H, 0.0) * float3(Dir * sin(Theta), cos(Theta));
    AxisAngle = axis * a;
    NormalStretch = Rel.z < H ? 1.0 - (Theta / H) * dot(Dir, Rel.xy) : 1.0;
    return center + rotated;
}
'''

WIND_HLSL = 'struct GoTStemFunctions {\n' + WIND_STEM_HLSL + '\n};\n' + r'''
GoTStemFunctions stem;
float3 rel = WorldPos - Pivot;
float H = max(Consumer.x * (BendModel > 0.5 ? abs(InstanceScale.z) : 1.0), 1.0);
float h = saturate(rel.z / H);
float force = GoTGrassGustForce(Pivot.xy, GustNoise, GustShape, WindDetailNoise, WindResponse.w * DetailWeight);
// 首帧 InteractPrev.w 为 0，共享采样器直接返回 0；之后严格配对各帧纹理和中心变换。
float4 field;
if (PreviousFrame > 0.5) field = GoTSampleWindField(FieldTexPrev, FieldTexPrevSampler, Pivot.xy, Interact);
else field = GoTSampleWindField(FieldTex, FieldTexSampler, Pivot.xy, Interact);
float speed, deflection;
GoTComposeWind(WindDir.xy, force, field.zw, WindDir.w, speed, deflection);
float w = Consumer.y * GOT_WIND_NORMALIZER * speed;
float phase = WindTime.x * 22.0 * Consumer.w + Rand * 62.8319;
if (BendModel < 0.5) phase -= 1.5 * h;
float idle = 0.1 + sin(phase) * (WindDir.z * 4.54545e-5 + 0.1) * FlutterScale;
// 共享纯数学：idle 保持主向，只有风分量随净风偏转；无局部风时完全恢复旧式。
float3 bend = GoTBuildWindBend(WindDir.xy, idle, w, deflection);
float2 lean = Consumer.z * bend.xy + field.xy * PushRad;
float theta = length(lean);
float2 ld = theta > 1e-5 ? lean / theta : WindDir.xy;
NormalStretch = 1.0;
if (BendModel > 0.5)
{
    // [适配] 固定全株角度上限；实际实例缩放纳入几何域，保证 s >= 0.15，避免横截面折叠。
    float radius = max(StemRadiusCm * max(abs(InstanceScale.x), abs(InstanceScale.y)), 1.0);
    theta = min(theta, 0.85 * H / radius);
    float3 bent = stem.GoTStemArc(rel, H, theta, ld, Tilt, NormalStretch);
    return float4(bent - rel, length(Tilt));
}
float a = theta * h * h;
float3 k = float3(-ld.y, ld.x, 0.0);
float c = cos(a), s = sin(a);
float3 rot = rel * c + cross(k, rel) * s + k * dot(k, rel) * (1.0 - c);
Tilt = k * a;
return float4(rot - rel, a);
'''


def existing_function_node(func, cls, x, y, match=None, **props):
    """复用节点，尤其保留函数输入和输出的 GUID；只创建缺失节点。"""
    nodes = [e for e in LIB.get_material_function_expressions(func) if isinstance(e, cls)]
    if match:
        key, value = match
        nodes = [e for e in nodes if str(e.get_editor_property(key)) == str(value)]
    assert len(nodes) <= 1, (func.get_name(), cls, match)
    node = nodes[0] if nodes else fnode(func, cls, x, y)
    for key, value in props.items():
        node.set_editor_property(key, value)
    return node


def function_frame_switch(func, name, current, previous, x, y):
    label = 'GoTWindFrame_' + name
    node = existing_function_node(func, unreal.MaterialExpressionPreviousFrameSwitch, x, y,
                                  match=('desc', label), desc=label)
    link(current, '', node, 'Current Frame')
    link(previous, '', node, 'Previous Frame')
    return node


def wind_function(mpc, rt, previous_rt=None):
    previous_rt = previous_rt or previous_field_target()
    func = owned('MF_GoTWind', WIND, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew())
    func.set_editor_property('description', '[官方] 统一主阵风与草类细节层。[适配] 芒草圆弧茎，树保留根部旋转。'
                             'BendModel: 0 根旋转，1 圆弧茎；DetailWeight 独立控制细节风，NormalStretch 是轴向尺度 s。')
    inputs = {}
    for i, (name, typ, default) in enumerate([
            ('Consumer', unreal.FunctionInputType.FUNCTION_INPUT_VECTOR4, None),
            ('FlutterScale', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, 1.0),
            ('PushRad', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, 0.0),
            ('DetailWeight', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, 0.0),
            ('BendModel', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, 0.0),
            ('StemRadiusCm', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, 100.0)]):
        n = existing_function_node(func, unreal.MaterialExpressionFunctionInput, -1600, i * 120,
                                  match=('input_name', name), input_name=name, input_type=typ, sort_priority=i,
                                  use_preview_value_as_default=default is not None)
        if default is not None:
            pv = n.get_editor_property('preview_value'); pv.set_editor_property('x', default)
            n.set_editor_property('preview_value', pv)
        inputs[name] = n
    world = existing_function_node(func, unreal.MaterialExpressionWorldPosition, -1400, 800)
    local0 = existing_function_node(func, unreal.MaterialExpressionConstant3Vector, -1500, 700)
    pivot = existing_function_node(func, unreal.MaterialExpressionTransformPosition, -1200, 700,
                   transform_source_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_INSTANCE,
                  transform_type=unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD)
    link(local0, '', pivot, '')
    mpcs = {}
    for i, n in enumerate(['WindDir', 'GustNoise', 'GustShape', 'WindTime', 'Interact', 'WindDetailNoise', 'WindResponse']):
        m = existing_function_node(func, unreal.MaterialExpressionCollectionParameter, -1400, 950 + i * 100,
                                  match=('parameter_name', n), collection=mpc, parameter_name=n)
        prev = existing_function_node(func, unreal.MaterialExpressionCollectionParameter, -1200, 950 + i * 100,
                                     match=('parameter_name', n + 'Prev'), collection=mpc, parameter_name=n + 'Prev')
        mpcs[n] = function_frame_switch(func, n, m, prev, -1000, 950 + i * 100)
    ftex = existing_function_node(func, unreal.MaterialExpressionTextureObject, -1400, 1700, match=('texture', rt), texture=rt)
    fprev = existing_function_node(func, unreal.MaterialExpressionTextureObject, -1200, 1700,
                                   match=('texture', previous_rt), texture=previous_rt)
    flags = []
    for name, value in (('CurrentFrame', 0.0), ('PreviousFrame', 1.0)):
        label = 'GoTWind' + name + 'Flag'
        flags.append(existing_function_node(func, unreal.MaterialExpressionConstant, -1400, int(2000 + value * 100),
                                            match=('desc', label), desc=label, r=value))
    frame_flag = function_frame_switch(func, 'TextureChoice', flags[0], flags[1], -1000, 2000)
    rnd = existing_function_node(func, unreal.MaterialExpressionPerInstanceRandom, -1400, 1800)
    # UE 内置函数用 INSTANCE -> WORLD 的三单位轴长度，支持 ISM 非等比实例缩放。
    scale_func = unreal.load_asset('/Engine/Functions/Engine_MaterialFunctions02/WorldPositionOffset/ObjectScale')
    assert scale_func, 'Engine ObjectScale function'
    scale = existing_function_node(func, unreal.MaterialExpressionMaterialFunctionCall, -1400, 1900)
    scale.set_material_function(scale_func)
    names = ['WorldPos', 'Pivot', 'WindDir', 'GustNoise', 'GustShape', 'WindTime', 'Interact', 'FieldTex', 'Rand', 'Consumer',
              'FlutterScale', 'PushRad', 'DetailWeight', 'BendModel', 'StemRadiusCm', 'InstanceScale', 'WindDetailNoise', 'WindResponse',
              'FieldTexPrev', 'PreviousFrame']
    previous_custom = [e for e in LIB.get_material_function_expressions(func) if isinstance(e, unreal.MaterialExpressionCustom)]
    assert len(previous_custom) <= 1, func.get_name()
    custom = custom_node(LIB.create_material_expression_in_function, func, -800, 600, names, WIND_HLSL,
                         unreal.CustomMaterialOutputType.CMOT_FLOAT4, [('Tilt', unreal.CustomMaterialOutputType.CMOT_FLOAT3),
                         ('NormalStretch', unreal.CustomMaterialOutputType.CMOT_FLOAT1)], 'GoTWindRotate',
                         node=previous_custom[0] if previous_custom else None)
    src = dict(WorldPos=world, Pivot=pivot, FieldTex=ftex, FieldTexPrev=fprev, PreviousFrame=frame_flag,
               Rand=rnd, InstanceScale=scale, **inputs, **mpcs)
    for n in names:
        link(src[n], 'Scale XYZ' if n == 'InstanceScale' else '', custom, n)
    wpo = existing_function_node(func, unreal.MaterialExpressionComponentMask, -500, 600, match=('a', False), r=True, g=True, b=True, a=False)
    link(custom, '', wpo, '')
    bend = existing_function_node(func, unreal.MaterialExpressionComponentMask, -500, 750, match=('a', True), r=False, g=False, b=False, a=True)
    link(custom, '', bend, '')
    o1 = existing_function_node(func, unreal.MaterialExpressionFunctionOutput, -250, 600, match=('output_name', 'WPO'), output_name='WPO', sort_priority=0)
    link(wpo, '', o1, '')
    o2 = existing_function_node(func, unreal.MaterialExpressionFunctionOutput, -250, 750, match=('output_name', 'Bend'), output_name='Bend', sort_priority=1)
    link(bend, '', o2, '')
    interps = [e for e in LIB.get_material_function_expressions(func) if isinstance(e, unreal.MaterialExpressionVertexInterpolator)]
    interp = interps[0] if interps else fnode(func, unreal.MaterialExpressionVertexInterpolator, -500, 900)
    link(custom, 'Tilt', interp, 'VS')
    o3 = existing_function_node(func, unreal.MaterialExpressionFunctionOutput, -250, 900, match=('output_name', 'Tilt'), output_name='Tilt', sort_priority=2,
               description='World-space rotation vector (axis * angle) for MF_GoTWindNormal [截帧: normals rotate with the vertices]')
    link(interp, 'PS', o3, '')
    stretch = existing_function_node(func, unreal.MaterialExpressionVertexInterpolator, -500, 1040,
                                    match=('desc', 'GoTStemNormalStretch'), desc='GoTStemNormalStretch')
    link(custom, 'NormalStretch', stretch, 'VS')
    o4 = existing_function_node(func, unreal.MaterialExpressionFunctionOutput, -250, 1040,
                               match=('output_name', 'NormalStretch'), output_name='NormalStretch', sort_priority=3,
                               description='[适配] 轴向尺度 s；MF_GoTWindNormal 对世界 up 分量除 s 一次，再旋转法线。')
    link(stretch, 'PS', o4, '')
    LIB.layout_material_function_expressions(func)
    LIB.update_material_function(func)
    unreal.EditorAssetLibrary.save_loaded_asset(func)
    log.append('MF_GoTWind updated in place (grass detail + stem arc / legacy tree)')
    return func


NORMAL_STEM_HLSL = r'''
float3 GoTStemNormal(float3 WorldNormal, float3 AxisAngle, float NormalStretch)
{
    // [适配] J^{-T} = R diag(1, 1, 1/s)，只校正轴向分量一次。几何调用者保证 s >= 0.15。
    float3 n = WorldNormal;
    n.z /= max(NormalStretch, 0.000001);
    float a = length(AxisAngle);
    if (a < 0.000001) return normalize(n);
    float3 k = AxisAngle / a;
    float c = cos(a), s = sin(a);
    return normalize(n * c + cross(k, n) * s + k * dot(k, n) * (1.0 - c));
}
'''
NORMAL_HLSL = 'struct GoTStemNormalFunctions {\n' + NORMAL_STEM_HLSL + '\n};\n' + r'''
GoTStemNormalFunctions normals;
return normals.GoTStemNormal(WorldNormal, AxisAngle, NormalStretch);
'''


def normal_function():
    """保留原函数接口 GUID，增加轴向尺度输入，校正圆弧茎的逆转置法线。"""
    func = owned('MF_GoTWindNormal', WIND, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew())
    func.set_editor_property('description', '[适配] 圆弧茎法线：世界 up 分量除 NormalStretch 后按 Tilt 旋转，再回切线空间。')
    inputs = {}
    for i, (name, typ, default) in enumerate([
            ('TangentNormal', unreal.FunctionInputType.FUNCTION_INPUT_VECTOR3, (0.0, 0.0, 1.0)),
            ('Tilt', unreal.FunctionInputType.FUNCTION_INPUT_VECTOR3, None),
            ('NormalStretch', unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, (1.0, 0.0, 0.0))]):
        n = existing_function_node(func, unreal.MaterialExpressionFunctionInput, -1100, i * 140,
                                  match=('input_name', name), input_name=name, input_type=typ, sort_priority=i,
                                  use_preview_value_as_default=default is not None)
        if default is not None:
            pv = n.get_editor_property('preview_value')
            for ch, value in zip('xyz', default):
                pv.set_editor_property(ch, value)
            n.set_editor_property('preview_value', pv)
        inputs[name] = n
    to_world = existing_function_node(func, unreal.MaterialExpressionTransform, -850, 0,
                                      match=('transform_source_type', unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_TANGENT),
                                      transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_TANGENT,
                                      transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    link(inputs['TangentNormal'], '', to_world, '')
    customs = [e for e in LIB.get_material_function_expressions(func) if isinstance(e, unreal.MaterialExpressionCustom)]
    assert len(customs) <= 1, func.get_name()
    c = custom_node(LIB.create_material_expression_in_function, func, -600, 0,
                    ['WorldNormal', 'AxisAngle', 'NormalStretch'], NORMAL_HLSL,
                    unreal.CustomMaterialOutputType.CMOT_FLOAT3, [], 'GoTWindNormal', node=customs[0] if customs else None)
    link(to_world, '', c, 'WorldNormal')
    link(inputs['Tilt'], '', c, 'AxisAngle')
    link(inputs['NormalStretch'], '', c, 'NormalStretch')
    to_ts = existing_function_node(func, unreal.MaterialExpressionTransform, -350, 0,
                                   match=('transform_source_type', unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD),
                                   transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD,
                                   transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_TANGENT)
    link(c, '', to_ts, '')
    o = existing_function_node(func, unreal.MaterialExpressionFunctionOutput, -100, 0,
                              match=('output_name', 'Normal'), output_name='Normal')
    link(to_ts, '', o, '')
    LIB.update_material_function(func)
    unreal.EditorAssetLibrary.save_loaded_asset(func)
    log.append('MF_GoTWindNormal updated in place (inverse axial scale then rotation)')
    return func


# WindDebug = (0 off / 1 macro / 2 blade response / 3 detail / 4 combined speed, opacity, stripe spacing, stripe phase).
# Mode 2 follows the third-party UE5 recreation (bilibili BV1ff421R7CW, Docs/Research/07): a lit jet colour replaces the
# albedo; on grass blades it is the vertex height above the root / blade length (VF TexCoord3.x), so upright blades in a
# lull run green -> red to the tip and gust-flattened blades turn blue/cyan [推断 from the video]. Surfaces without a
# blade (BladeRise < 0) show the tip height of a reference blade under the local force: P2.z = L (1 - 0.78 W) [截帧 grass VS].
DEBUG_HLSL = r'''
AlbedoOut = Albedo;
if (WindDebug.x < 0.5) return float3(0, 0, 0);
float2 p = WorldPos.xy;
float4 it = GoTSampleWindField(FieldTex, FieldTexSampler, p, Interact);
float grassForce = GoTGrassGustForce(p, GustNoise, GustShape, WindDetailNoise, WindResponse.w);
float speed, deflection;
GoTComposeWind(WindDir.xy, grassForce, it.zw, WindDir.w, speed, deflection);
const float DebugMaxSpeedCmPerSec = 4000.0;  // 具名调试显示范围；不参与风的计算。
if (WindDebug.x > 3.5)
{
    float value = saturate(speed / DebugMaxSpeedCmPerSec);
    float3 jet = saturate(1.5 - abs(4.0 * value - float3(3.0, 2.0, 1.0)));
    AlbedoOut = lerp(Albedo, jet * 0.7, WindDebug.y);
    return float3(0, 0, 0);
}
if (WindDebug.x > 2.5)
{
    float noise = GoTPerlin3D(float3(p * WindDetailNoise.w + WindDetailNoise.xy, WindDetailNoise.z));
    float amplitude = max(GustShape.x * WindResponse.w, 0.0);
    float detail = amplitude * noise;
    // 细节层的有符号贡献按自身振幅归一化；振幅为 0 时显示中性值，不显示虚假的风速。
    float value = saturate(0.5 + 0.5 * detail / max(amplitude, 1.0));
    float3 jet = saturate(1.5 - abs(4.0 * value - float3(3.0, 2.0, 1.0)));
    AlbedoOut = lerp(Albedo, jet * 0.7, WindDebug.y);
    return float3(0, 0, 0);
}
if (WindDebug.x > 1.5)
{
    float rise = BladeRise;
    if (rise < 0.0)
    {
        float W = saturate(0.1 + speed * GOT_WIND_NORMALIZER);
        rise = (1.0 - 0.78 * W) * (1.0 - 0.6 * saturate(length(it.xy)));
    }
    float3 jet = saturate(1.5 - abs(4.0 * saturate(rise) - float3(3.0, 2.0, 1.0)));
    AlbedoOut = lerp(Albedo, jet * 0.7, WindDebug.y);
    return float3(0, 0, 0);
}
float gust = GoTGustAmount(p, GustNoise, GustShape);
float3 c = gust < 0.5 ? lerp(float3(0.03, 0.18, 1.0), float3(0.1, 0.9, 0.15), gust * 2.0)
                      : lerp(float3(0.1, 0.9, 0.15), float3(1.0, 0.12, 0.03), gust * 2.0 - 1.0);
float w = fwidth(gust) * 1.5 + 1e-4;                          // contour lines at 0.25 / 0.75 (same as the debug lines)
float edge = max(1.0 - saturate(abs(gust - 0.25) / w), 1.0 - saturate(abs(gust - 0.75) / w));
c = lerp(c, float3(1, 1, 1), edge);
if (WindDebug.z > 1.0)                                        // 旧主层调试装饰条纹，不作为真实传播速度的证据。
{
    float t = frac((dot(p, WindDir.xy) - WindDebug.w) / WindDebug.z);
    float d = min(t, 1.0 - t) * WindDebug.z;
    float lw = fwidth(dot(p, WindDir.xy)) * 1.5 + WindDebug.z * 0.015;
    c *= 1.0 - 0.65 * (1.0 - saturate(d / lw));
}
c = lerp(c, float3(1, 0, 1), saturate(length(it.xy)));
AlbedoOut = Albedo * (1.0 - 0.85 * WindDebug.y);
return c * WindDebug.y;
'''
DEBUG_INPUTS = ['WorldPos', 'WindDir', 'GustNoise', 'GustShape', 'Interact', 'WindDebug', 'FieldTex', 'Albedo', 'BladeRise',
                'WindDetailNoise', 'WindResponse']


def debug_function(mpc, rt):
    func = owned('MF_GoTWindDebug', WIND, unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew())
    func.set_editor_property('description', '风调试：1 主层，2 草响应，3 细节有符号贡献，4 草类双层与局部源的净风速（0–4000 cm/s）。'
                             '装饰条纹仅在旧主层视图显示，不作为物理证据。')
    exprs = list(LIB.get_material_function_expressions(func))
    customs = [e for e in exprs if isinstance(e, unreal.MaterialExpressionCustom)]
    fins = {str(e.get_editor_property('input_name')) for e in exprs if isinstance(e, unreal.MaterialExpressionFunctionInput)}
    if len(customs) == 1 and {'Albedo', 'BladeRise'} <= fins:
        # Same pins as before: update the code in place. Rebuilding gives the function outputs new GUIDs and every
        # material call node would lose its links (the Albedo pass-through cannot be recovered after that).
        c = customs[0]
        names = [str(n) for n in LIB.get_material_expression_input_names(c)]
        values = list(LIB.get_inputs_for_material_function_expression(func, c))
        src = {name: values[i] if i < len(values) else None for i, name in enumerate(names)}
        for i, name in enumerate(('WindDetailNoise', 'WindResponse')):
            src[name] = existing_function_node(func, unreal.MaterialExpressionCollectionParameter, -1400, 1200 + i * 100,
                                               match=('parameter_name', name), collection=mpc, parameter_name=name)
        custom_node(LIB.create_material_expression_in_function, func, -800, 300, DEBUG_INPUTS, DEBUG_HLSL,
                    unreal.CustomMaterialOutputType.CMOT_FLOAT3, [('AlbedoOut', unreal.CustomMaterialOutputType.CMOT_FLOAT3)],
                    'GoTWindDebug', node=c)
        assert all(src.get(name) is not None for name in DEBUG_INPUTS), 'Incomplete existing debug graph'
        for name in DEBUG_INPUTS:
            link(src[name], '', c, name)
        LIB.update_material_function(func)
        unreal.EditorAssetLibrary.save_loaded_asset(func)
        log.append('MF_GoTWindDebug code updated in place')
        return func
    assert not exprs, 'Unsupported existing debug function; preserve its output nodes'
    world = fnode(func, unreal.MaterialExpressionWorldPosition, -1400, 0)
    mpcs = {}
    for i, n in enumerate(['WindDir', 'GustNoise', 'GustShape', 'Interact', 'WindDebug', 'WindDetailNoise', 'WindResponse']):
        m = fnode(func, unreal.MaterialExpressionCollectionParameter, -1400, 120 + i * 100)
        m.set_editor_property('collection', mpc)
        m.set_editor_property('parameter_name', n)
        mpcs[n] = m
    ftex = fnode(func, unreal.MaterialExpressionTextureObject, -1400, 800, texture=rt)
    albedo = fnode(func, unreal.MaterialExpressionFunctionInput, -1400, 950, input_name='Albedo',
                   input_type=unreal.FunctionInputType.FUNCTION_INPUT_VECTOR3, sort_priority=0,
                   description='Material albedo; returned unchanged when the heatmap is off')
    rise = fnode(func, unreal.MaterialExpressionFunctionInput, -1400, 1080, input_name='BladeRise',
                 input_type=unreal.FunctionInputType.FUNCTION_INPUT_SCALAR, use_preview_value_as_default=True, sort_priority=1,
                 description='Grass: vertex height above the root / blade length (TexCoord3.x). Leave unconnected (-1) elsewhere.')
    pv = rise.get_editor_property('preview_value')
    pv.set_editor_property('x', -1.0)
    rise.set_editor_property('preview_value', pv)
    custom = custom_node(LIB.create_material_expression_in_function, func, -800, 300, DEBUG_INPUTS, DEBUG_HLSL,
                         unreal.CustomMaterialOutputType.CMOT_FLOAT3, [('AlbedoOut', unreal.CustomMaterialOutputType.CMOT_FLOAT3)],
                         'GoTWindDebug')
    src = dict(WorldPos=world, FieldTex=ftex, Albedo=albedo, BladeRise=rise, **mpcs)
    for n in DEBUG_INPUTS:
        link(src[n], '', custom, n)
    inv = fnode(func, unreal.MaterialExpressionEyeAdaptationInverse, -500, 300)
    link(custom, '', inv, 'LightValueInput')
    o1 = fnode(func, unreal.MaterialExpressionFunctionOutput, -250, 300, output_name='Emissive', sort_priority=0)
    link(inv, '', o1, '')
    o2 = fnode(func, unreal.MaterialExpressionFunctionOutput, -250, 450, output_name='Albedo', sort_priority=1,
               description='Albedo with the heatmap applied (wire to the slab Diffuse Albedo)')
    link(custom, 'AlbedoOut', o2, '')
    LIB.layout_material_function_expressions(func)
    LIB.update_material_function(func)
    unreal.EditorAssetLibrary.save_loaded_asset(func)
    log.append('MF_GoTWindDebug rebuilt (Albedo pass-through, BladeRise)')
    return func


# Re-wire after rebuilding the functions: new function outputs get new GUIDs, so existing call nodes lose the links from
# their outputs. Reconnect by graph structure (idempotent). Wind consumers also get PushRad <- MPC_Wind.ConsumerPush.
# material: (MPC consumer, flutter scale, ConsumerPush channel)
WIND_CONSUMERS = {'M_PampasFoliage': ('Pampas', 1.0, 'r'), 'M_PampasMapleLeaf': ('Tree', 1.0, 'g'),
                  'M_PampasMapleBark': ('Tree', 0.0, 'g'), 'M_PampasGrassBlade': ('Grass', 1.0, 'b')}
DEBUG_USERS = ['M_PampasTerrain', 'M_PampasFoliage', 'M_PampasGrassBlade', 'M_PampasMapleLeaf', 'M_PampasMapleBark']
ACTIVE_WIND_USERS = ['M_PampasFoliage', 'M_PampasMapleLeaf', 'M_PampasMapleBark']


def wind_material_node(mat, cls, label, x, y, **props):
    nodes = [e for e in LIB.get_material_expressions(mat)
             if isinstance(e, cls) and str(e.get_editor_property('desc')) == label]
    assert len(nodes) <= 1, (mat.get_name(), label)
    node = nodes[0] if nodes else LIB.create_material_expression(mat, cls, x, y)
    node.set_editor_property('desc', label)
    for key, value in props.items():
        node.set_editor_property(key, value)
    return node


def wind_material_frame_value(mat, label, name, mpc, x, y):
    current = wind_material_node(mat, unreal.MaterialExpressionCollectionParameter, label, x, y,
                                 collection=mpc, parameter_name=name)
    if name not in HISTORY_MPC_NAMES:
        return current
    previous = wind_material_node(mat, unreal.MaterialExpressionCollectionParameter, label + 'Prev', x, y + 80,
                                  collection=mpc, parameter_name=name + 'Prev')
    switch = wind_material_node(mat, unreal.MaterialExpressionPreviousFrameSwitch, label + 'Frame', x + 150, y)
    link(current, '', switch, 'Current Frame')
    link(previous, '', switch, 'Previous Frame')
    return switch


def wire_wind_material(mat, wind, normal, mpc, stem_radius_cm=100.0):
    """只更新风消费者输入与法线；保留已有 WPO、贴图、材质函数输出连接。"""
    name = mat.get_name()
    consumer, _, push_ch = WIND_CONSUMERS[name]
    wind_calls = calls_of(mat, wind)
    assert len(wind_calls) == 1, (name, 'Expected one existing wind call', len(wind_calls))
    call = wind_calls[0]
    source = wind_material_frame_value(mat, 'GoTWindConsumer', consumer, mpc, 0, 2300)
    link(source, '', call, 'Consumer')
    response = wind_material_frame_value(mat, 'GoTWindResponse', 'WindResponse', mpc, 0, 2450)
    flutter_ch = {'M_PampasFoliage': 'g', 'M_PampasMapleLeaf': 'b', 'M_PampasGrassBlade': 'r'}.get(name)
    if flutter_ch:
        flutter = wind_material_node(mat, unreal.MaterialExpressionComponentMask, 'GoTWindFlutter', 180, 2450,
                                     r=flutter_ch == 'r', g=flutter_ch == 'g', b=flutter_ch == 'b', a=False)
        link(response, '', flutter, '')
    else:
        flutter = wind_material_node(mat, unreal.MaterialExpressionConstant, 'GoTWindFlutter', 180, 2450, r=0.0)
    link(flutter, '', call, 'FlutterScale')
    push = wind_material_frame_value(mat, 'GoTWindPush', 'ConsumerPush', mpc, 0, 2600)
    pmask = wind_material_node(mat, unreal.MaterialExpressionComponentMask, 'GoTWindPushChannel', 180, 2600,
                               r=push_ch == 'r', g=push_ch == 'g', b=push_ch == 'b', a=False)
    link(push, '', pmask, '')
    link(pmask, '', call, 'PushRad')
    for i, (pin, value) in enumerate([
            ('DetailWeight', 1.0 if consumer in ('Pampas', 'Grass') else 0.0),
            ('BendModel', 1.0 if consumer == 'Pampas' else 0.0),
            ('StemRadiusCm', stem_radius_cm)]):
        n = wind_material_node(mat, unreal.MaterialExpressionConstant, f'GoTWind{pin}', 0, 2770 + i * 120, r=value)
        link(n, '', call, pin)
    ncalls = calls_of(mat, normal)
    assert len(ncalls) <= 1, (name, 'Duplicate normal calls')
    if ncalls:
        ncall = ncalls[0]
    else:
        slab = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL)
        previous = slab_pin(mat, slab, 'Normal')
        ncall = LIB.create_material_expression(mat, unreal.MaterialExpressionMaterialFunctionCall, 450, 3100)
        ncall.set_material_function(normal)
        if previous:
            link(previous, LIB.get_input_node_output_name_for_material_expression(slab, previous), ncall, 'TangentNormal')
        link(ncall, 'Normal', slab, 'Normal')
    link(call, 'Tilt', ncall, 'Tilt')
    link(call, 'NormalStretch', ncall, 'NormalStretch')
    LIB.delete_unused_expressions(mat)
    log.append(f'{name}: detail={consumer in ("Pampas", "Grass")}, stem={consumer == "Pampas"}, '
               f'flutter={flutter_ch or 0}, radius={stem_radius_cm} cm; preserved WPO')


def calls_of(mat, func):
    return [e for e in LIB.get_material_expressions(mat)
            if isinstance(e, unreal.MaterialExpressionMaterialFunctionCall) and e.get_editor_property('material_function') == func]


def open_add(mat, root):
    """First Add node in the chain below root with a missing input (pin name, node)."""
    stack, seen = [root], set()
    while stack:
        n = stack.pop()
        if n is None or n.get_name() in seen:
            continue
        seen.add(n.get_name())
        ins = list(LIB.get_inputs_for_material_expression(mat, n))
        if isinstance(n, unreal.MaterialExpressionAdd):
            for pin, i in zip(('A', 'B'), ins + [None] * (2 - len(ins))):
                if i is None:
                    return pin, n
        stack += [i for i in ins if i is not None]
    return None, None


def slab_pin(mat, slab, pin):
    names = [str(n) for n in LIB.get_material_expression_input_names(slab)]
    vals = list(LIB.get_inputs_for_material_expression(mat, slab))
    i = names.index(pin)
    return vals[i] if i < len(vals) else None


def rewire_all(wind, debug, mpc):
    normal = unreal.load_asset(f'{WIND}/MF_GoTWindNormal')
    for name in sorted(set(WIND_CONSUMERS) | set(DEBUG_USERS)):
        mat = unreal.load_asset(f'/Game/GoT/Pampas/Materials/{name}')
        notes = []
        calls = calls_of(mat, wind)
        if len(calls) > 1:                     # earlier wiring runs left extra call nodes: keep the one in the WPO chain
            root = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
            chain, stack = set(), [root]
            while stack:
                n = stack.pop()
                if n is None or n.get_name() in chain:
                    continue
                chain.add(n.get_name())
                stack += [i for i in LIB.get_inputs_for_material_expression(mat, n) if i is not None]
            keep = next((c for c in calls if c.get_name() in chain), calls[0])
            for c in calls:
                if c != keep:
                    LIB.delete_material_expression(mat, c)
            notes.append(f'removed {len(calls) - 1} duplicate wind calls')
            calls = [keep]
        for call in calls:
            root = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
            if root is None:
                assert LIB.connect_material_property(call, 'WPO', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
                notes.append('WPO')
            else:
                pin, add = open_add(mat, root)
                if add is not None:
                    link(call, 'WPO', add, pin)
                    notes.append(f'WPO->{add.get_name()}.{pin}')
            for ncall in calls_of(mat, normal):
                link(call, 'Tilt', ncall, 'Tilt')
                notes.append('Tilt')
            if name in WIND_CONSUMERS:
                consumer, flutter, ch = WIND_CONSUMERS[name]
                cp = LIB.create_material_expression(mat, unreal.MaterialExpressionCollectionParameter, 0, 2300)
                cp.set_editor_property('collection', mpc)
                cp.set_editor_property('parameter_name', consumer)
                link(cp, '', call, 'Consumer')
                fs = LIB.create_material_expression(mat, unreal.MaterialExpressionConstant, 0, 2420)
                fs.set_editor_property('r', flutter)
                link(fs, '', call, 'FlutterScale')
                p = LIB.create_material_expression(mat, unreal.MaterialExpressionCollectionParameter, 0, 2560)
                p.set_editor_property('collection', mpc)
                p.set_editor_property('parameter_name', 'ConsumerPush')
                m = LIB.create_material_expression(mat, unreal.MaterialExpressionComponentMask, 150, 2560)
                for c in 'rgba':
                    m.set_editor_property(c, c == ch)
                link(p, '', m, '')
                link(m, '', call, 'PushRad')
                notes.append(f'Consumer={consumer} flutter={flutter} PushRad<-ConsumerPush.{ch}')
        for call in calls_of(mat, debug):
            slab = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL)
            alb = slab_pin(mat, slab, 'Diffuse Albedo')
            if alb is None:
                warns.append(f'{name}: slab Diffuse Albedo is unconnected, heatmap albedo not wired')
            elif alb != call:
                # Old wiring: Diffuse Albedo = albedo * call.AlbedoScale (B may have lost its link when the function
                # was rebuilt). New: albedo -> call.Albedo -> Diffuse Albedo.
                src, out = alb, ''
                if isinstance(alb, unreal.MaterialExpressionMultiply):
                    ins = list(LIB.get_inputs_for_material_expression(mat, alb)) + [None, None]
                    if ins[1] is None or ins[1] == call:
                        src = ins[0]
                        out = LIB.get_input_node_output_name_for_material_expression(alb, src)
                link(src, out, call, 'Albedo')
                link(call, 'Albedo', slab, 'Diffuse Albedo')
                notes.append('Albedo pass-through')
            em = slab_pin(mat, slab, 'Emissive Color')
            if em is None:
                link(call, 'Emissive', slab, 'Emissive Color')
                notes.append('Emissive')
            elif isinstance(em, unreal.MaterialExpressionAdd):
                ins = list(LIB.get_inputs_for_material_expression(mat, em))
                if len(ins) < 2 or ins[1] is None:
                    link(call, 'Emissive', em, 'B')
                    notes.append('Emissive(add)')
        if name in WIND_CONSUMERS:
            wire_wind_material(mat, wind, normal, mpc)
        LIB.delete_unused_expressions(mat)
        errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
        log.append(f'{name}: rewired {notes}; errors={errors}')


# ---------------------------------------------------------------- 5. grass material
def mnode(mat, cls, x, y, **props):
    n = LIB.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def const(mat, v, x, y):
    return mnode(mat, unreal.MaterialExpressionConstant, x, y, r=v)


def vec(mat, rgb, x, y):
    return mnode(mat, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(*rgb, 1))


def op(mat, cls, a, b, x, y, ao=''):
    n = mnode(mat, cls, x, y)
    link(a, ao, n, 'A')
    link(b, '', n, 'B')
    return n


def lerp(mat, a, b, alpha, x, y, alpha_out=''):
    n = mnode(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
    link(a, '', n, 'A'); link(b, '', n, 'B'); link(alpha, alpha_out, n, 'Alpha')
    return n


def mask(mat, src, ch, x, y):
    n = mnode(mat, unreal.MaterialExpressionComponentMask, x, y, r=ch == 'r', g=ch == 'g', b=False, a=False)
    link(src, '', n, '')
    return n


def graph_inputs(mat, node):
    names = [str(n) for n in LIB.get_material_expression_input_names(node)]
    values = list(LIB.get_inputs_for_material_expression(mat, node))
    return {name: values[i] if i < len(values) else None for i, name in enumerate(names)}


def reachable_nodes(mat, root):
    """从实际输出反向追踪，忽略材质中遗留的孤立旧节点。"""
    result, seen, pending = [], set(), [root]
    while pending:
        node = pending.pop()
        if node is None or node.get_path_name() in seen:
            continue
        seen.add(node.get_path_name())
        result.append(node)
        pending.extend(LIB.get_inputs_for_material_expression(mat, node))
    return result


def grass_profile_node(mat, label, input_name, source, code, x, y):
    nodes = [n for n in LIB.get_material_expressions(mat)
             if isinstance(n, unreal.MaterialExpressionCustom) and str(n.get_editor_property('desc')) == label]
    assert len(nodes) <= 1, (mat.get_name(), label)
    node = nodes[0] if nodes else mnode(mat, unreal.MaterialExpressionCustom, x, y, desc=label)
    pin = unreal.CustomInput()
    pin.set_editor_property('input_name', input_name)
    node.set_editor_property('inputs', [pin])
    node.set_editor_property('code', code)
    node.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    link(source, '', node, input_name)
    return node


def update_grass_clumping_material(mat):
    """原位更新可达草材质：保留两档簇色，弱化逐叶色噪声，恢复叶宽光泽变化。

    [官方] GDC 15:18–16:10：gloss/vein 跨叶宽，颜色沿叶长和簇变化。
    [适配] 叶宽 profile、roughness 数值和 15–60 m 过渡为本轮 UE 初值，不是原版已恢复参数。
    """
    if 'GrassRoughnessFar' in [str(n) for n in LIB.get_scalar_parameter_names(mat)]:
        log.append('M_GoTGrass clumping update skipped: PBR constants already exposed as parameters')
        return mat
    slab = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL)
    assert isinstance(slab, unreal.MaterialExpressionSubstrateSlabBSDF), (mat.get_name(), 'Expected reachable slab')
    pins = graph_inputs(mat, slab)
    albedo, rough = pins['Diffuse Albedo'], pins['Roughness']
    assert albedo and isinstance(rough, unreal.MaterialExpressionLinearInterpolate)
    roots_before = {p: LIB.get_material_property_input_node(mat, p)
                    for p in (unreal.MaterialProperty.MP_FRONT_MATERIAL, unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
                              unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)}
    nodes = reachable_nodes(mat, albedo)

    def scalar(node):
        return float(node.get_editor_property('r')) if isinstance(node, unreal.MaterialExpressionConstant) else None

    def uv_mask(node, index, channel):
        if not isinstance(node, unreal.MaterialExpressionComponentMask):
            return False
        if any(bool(node.get_editor_property(c)) != (c == channel) for c in 'rgba'):
            return False
        sources = list(LIB.get_inputs_for_material_expression(mat, node))
        return len(sources) == 1 and isinstance(sources[0], unreal.MaterialExpressionTextureCoordinate) \
            and sources[0].get_editor_property('coordinate_index') == index

    random_coefficients, brightness = [], []
    for node in nodes:
        if isinstance(node, unreal.MaterialExpressionMultiply):
            inputs = graph_inputs(mat, node)
            for rnd, coefficient in ((inputs.get('A'), inputs.get('B')), (inputs.get('B'), inputs.get('A'))):
                value = scalar(coefficient)
                if uv_mask(rnd, 1, 'r') and value is not None and (abs(value - 0.35) < 1e-5 or abs(value) < 1e-5):
                    random_coefficients.append(coefficient)
        elif isinstance(node, unreal.MaterialExpressionLinearInterpolate):
            inputs = graph_inputs(mat, node)
            a, b = scalar(inputs.get('A')), scalar(inputs.get('B'))
            if uv_mask(inputs.get('Alpha'), 1, 'r') and a is not None and b is not None \
                    and ((abs(a - 0.85) < 1e-5 and abs(b - 1.15) < 1e-5)
                         or (abs(a - 0.97) < 1e-5 and abs(b - 1.03) < 1e-5)):
                brightness.append((inputs['A'], inputs['B']))
    assert len(random_coefficients) == 1, ('Random dry-colour coefficient not unique', len(random_coefficients))
    assert len(brightness) == 1, ('Random brightness lerp not unique', len(brightness))
    across = [n for n in nodes if uv_mask(n, 0, 'r')]
    assert len(across) == 1, ('Reachable across-blade UV not unique', len(across))
    outer = graph_inputs(mat, rough)
    inner = outer.get('A')
    assert isinstance(inner, unreal.MaterialExpressionLinearInterpolate), 'Expected roughness profile lerp'
    inner_inputs = graph_inputs(mat, inner)
    assert abs(scalar(inner_inputs['A']) - 0.78) < 1e-5 and abs(scalar(inner_inputs['B']) - 0.45) < 1e-5
    assert abs(scalar(outer['B']) - 0.85) < 1e-5
    depth_nodes = [n for n in reachable_nodes(mat, outer['Alpha']) if isinstance(n, unreal.MaterialExpressionPixelDepth)]
    assert len(depth_nodes) == 1, ('Reachable pixel depth not unique', len(depth_nodes))

    random_coefficients[0].set_editor_property('r', 0.0)
    brightness[0][0].set_editor_property('r', 0.97)
    brightness[0][1].set_editor_property('r', 1.03)
    width = grass_profile_node(mat, 'GoTGrassAcrossGloss', 'U', across[0],
                               'float p = saturate(1.0 - abs(2.0 * U - 1.0)); return p * p;', -1050, 850)
    distance = grass_profile_node(mat, 'GoTGrassGlossDistance', 'DepthCm', depth_nodes[0],
                                  'return smoothstep(1500.0, 6000.0, DepthCm);', -800, 1100)
    link(width, '', inner, 'Alpha')
    link(distance, '', rough, 'Alpha')
    assert graph_inputs(mat, slab) == pins, 'Slab root pins changed'
    assert all(LIB.get_material_property_input_node(mat, p) == node for p, node in roots_before.items()), 'Material output root changed'
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    assert not errors, (mat.get_name(), errors)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log.append('M_GoTGrass updated in place: clump palette preserved; dry random=0, brightness=.97..1.03; '
               'gloss across blade, distance=15..60 m; longitudinal colour/AO/SSS/debug unchanged')
    return mat


GRASS_PBR_GROUPS = ('01 反照率', '02 高光', '03 透光', '04 AO')


def grass_pbr_param(mat, consumer, pin, name, group, priority, desc, default=None):
    """把 consumer.pin 上的常量换成同值参数（原位置、原默认值）；已是同名参数则只刷新分组和说明。"""
    cur = graph_inputs(mat, consumer).get(pin)
    is_vec = isinstance(cur, (unreal.MaterialExpressionConstant3Vector, unreal.MaterialExpressionVectorParameter)) \
        or isinstance(default, tuple)
    cls = unreal.MaterialExpressionVectorParameter if is_vec else unreal.MaterialExpressionScalarParameter
    if isinstance(cur, cls) and str(cur.get_editor_property('parameter_name')) == name:
        node = cur
    else:
        if cur is None:
            assert default is not None, (name, 'unconnected pin needs an explicit default')
            value, x, y = default, consumer.get_editor_property('material_expression_editor_x') - 300, \
                consumer.get_editor_property('material_expression_editor_y') + 80 * priority
        else:
            assert isinstance(cur, (unreal.MaterialExpressionConstant, unreal.MaterialExpressionConstant3Vector)), \
                (name, pin, cur.get_class().get_name())
            value = cur.get_editor_property('constant' if is_vec else 'r')
            x, y = cur.get_editor_property('material_expression_editor_x'), cur.get_editor_property('material_expression_editor_y')
        node = mnode(mat, cls, x, y, parameter_name=name)
        if is_vec:
            c = value if isinstance(value, unreal.LinearColor) else unreal.LinearColor(*value, 1.0)
            node.set_editor_property('default_value', unreal.LinearColor(c.r, c.g, c.b, 1.0))
        else:
            node.set_editor_property('default_value', float(value))
        link(node, '', consumer, pin)
    node.set_editor_property('group', group)
    node.set_editor_property('sort_priority', priority)
    node.set_editor_property('desc', desc)
    return node


def expose_grass_pbr_params(mat):
    """原位把 M_GoTGrass 的 PBR 常量换成实例可调参数，默认值等于当前常量，画面不变；可重复运行。

    [适配] 这些都是 UE 程序化近似的初值，不是原版恢复参数；原版 PS 仍待精读（G1 第 38 页）。
    """
    g_alb, g_spec, g_sss, g_ao = GRASS_PBR_GROUPS
    slab = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL)
    ao = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    assert isinstance(slab, unreal.MaterialExpressionSubstrateSlabBSDF) and isinstance(ao, unreal.MaterialExpressionLinearInterpolate)
    pins = graph_inputs(mat, slab)
    call = pins['Diffuse Albedo']
    assert isinstance(call, unreal.MaterialExpressionMaterialFunctionCall) and pins['Emissive Color'] == call

    # 01 反照率：整体着色插在调试函数之前，热力图叠加仍在最上层
    src = graph_inputs(mat, call)['Albedo']
    si = graph_inputs(mat, src) if isinstance(src, unreal.MaterialExpressionMultiply) else {}
    tint_node = si.get('B')
    if isinstance(tint_node, unreal.MaterialExpressionVectorParameter) \
            and str(tint_node.get_editor_property('parameter_name')) == 'GrassAlbedoTint':
        tint, product = src, si['A']
    else:
        product = src
        tint = mnode(mat, unreal.MaterialExpressionMultiply, call.get_editor_property('material_expression_editor_x') - 200,
                     call.get_editor_property('material_expression_editor_y') - 150)
        link(product, '', tint, 'A')
        link(tint, '', call, 'Albedo')
    grass_pbr_param(mat, tint, 'B', 'GrassAlbedoTint', g_alb, 0, '最终反照率整体乘色（白=不变）', (1.0, 1.0, 1.0))
    pi = graph_inputs(mat, product)
    palette, shade = pi['A'], pi['B']
    pal = graph_inputs(mat, palette)
    greens = pal['A']
    grass_pbr_param(mat, greens, 'A', 'GrassGreenColorA', g_alb, 1, '颜色档位 0 的主色（UV1.g 选档）')
    grass_pbr_param(mat, greens, 'B', 'GrassGreenColorB', g_alb, 2, '颜色档位 1 的主色')
    grass_pbr_param(mat, palette, 'B', 'GrassDryColor', g_alb, 3, '干枯色；硬草和随机干枯向它混合')
    dry_add = list(LIB.get_inputs_for_material_expression(mat, pal['Alpha']))[0]
    ai = graph_inputs(mat, dry_add)
    grass_pbr_param(mat, ai['A'], 'B', 'GrassDryRandom', g_alb, 4, '逐叶随机干枯量（0=关）')
    grass_pbr_param(mat, ai['B'], 'A > B', 'GrassStiffDry', g_alb, 5, '硬草（草种 2）固定干枯量')
    sh = graph_inputs(mat, shade)
    mul16, vein = sh['A'], sh['B']
    m16 = graph_inputs(mat, mul16)
    mul15, clump = m16['A'], m16['B']
    m15 = graph_inputs(mat, mul15)
    tone, vary = m15['A'], m15['B']
    grass_pbr_param(mat, tone, 'A', 'GrassRootTone', g_alb, 6, '叶根亮度倍数')
    grass_pbr_param(mat, tone, 'B', 'GrassTipTone', g_alb, 7, '叶尖亮度倍数')
    power = graph_inputs(mat, tone)['Alpha']
    assert isinstance(power, unreal.MaterialExpressionPower) and graph_inputs(mat, ao)['Alpha'] == power
    grass_pbr_param(mat, power, 'Exp', 'GrassRootToTipExponent', g_alb, 8, '根→尖渐变指数；同时作用于亮度和 AO')
    grass_pbr_param(mat, vary, 'A', 'GrassBladeBrightnessMin', g_alb, 9, '逐叶随机亮度下限')
    grass_pbr_param(mat, vary, 'B', 'GrassBladeBrightnessMax', g_alb, 10, '逐叶随机亮度上限')
    grass_pbr_param(mat, clump, 'A', 'GrassClumpToneA', g_alb, 11, '草簇明暗：簇值 0 端')
    grass_pbr_param(mat, clump, 'B', 'GrassClumpToneB', g_alb, 12, '草簇明暗：簇值 1 端')
    grass_pbr_param(mat, vein, 'B', 'GrassVeinBrightness', g_alb, 13, '中脉亮度倍数（1=无叶脉）')
    smooth = graph_inputs(mat, vein)['Alpha']
    assert isinstance(smooth, unreal.MaterialExpressionSmoothStep)
    grass_pbr_param(mat, smooth, 'Min', 'GrassVeinWidth', g_alb, 14, '中脉半宽（叶宽 UV 0..0.5）')

    # 02 高光
    grass_pbr_param(mat, slab, 'F0', 'GrassF0', g_spec, 0, '法线入射反射率（0.04≈4%）')
    rough = pins['Roughness']
    ri = graph_inputs(mat, rough)
    grass_pbr_param(mat, ri['A'], 'A', 'GrassRoughnessEdge', g_spec, 1, '叶缘粗糙度（近景）')
    grass_pbr_param(mat, ri['A'], 'B', 'GrassRoughnessCenter', g_spec, 2, '叶中线粗糙度（近景）')
    grass_pbr_param(mat, rough, 'B', 'GrassRoughnessFar', g_spec, 3, '远景统一粗糙度')
    fade = ri['Alpha']
    assert isinstance(fade, unreal.MaterialExpressionCustom) and str(fade.get_editor_property('desc')) == 'GoTGrassGlossDistance'
    depth = graph_inputs(mat, fade)['DepthCm']
    assert isinstance(depth, unreal.MaterialExpressionPixelDepth)
    if len(fade.get_editor_property('inputs')) != 3:
        start = 1500.0, 6000.0
        fade_pins = []
        for n in ('DepthCm', 'FadeStartCm', 'FadeEndCm'):
            p = unreal.CustomInput()
            p.set_editor_property('input_name', n)
            fade_pins.append(p)
        fade.set_editor_property('inputs', fade_pins)
        fade.set_editor_property('code', 'return smoothstep(FadeStartCm, FadeEndCm, DepthCm);')
    else:
        start = None
    link(depth, '', fade, 'DepthCm')
    grass_pbr_param(mat, fade, 'FadeStartCm', 'GrassGlossFadeStartCm', g_spec, 4, '近景光泽开始过渡到远景的距离（cm）',
                    start[0] if start else None)
    grass_pbr_param(mat, fade, 'FadeEndCm', 'GrassGlossFadeEndCm', g_spec, 5, '完全使用远景粗糙度的距离（cm）',
                    start[1] if start else None)

    # 03 透光（Two-Sided Wrap）
    grass_pbr_param(mat, slab, 'SSS MFP', 'GrassSSSMFP', g_sss, 0, '次表面平均自由程颜色，决定透光色')
    grass_pbr_param(mat, slab, 'SSS MFP Scale', 'GrassSSSMFPScale', g_sss, 1, 'MFP 整体倍数（Slab 默认 1）', 1.0)
    grass_pbr_param(mat, slab, 'SSS Phase Anisotropy', 'GrassSSSPhaseAnisotropy', g_sss, 2,
                    '透光相位各向异性 -1..1（Slab 默认 0）', 0.0)

    # 04 AO
    grass_pbr_param(mat, ao, 'A', 'GrassAORoot', g_ao, 0, '叶根 AO')
    grass_pbr_param(mat, ao, 'B', 'GrassAOTip', g_ao, 1, '叶尖 AO')

    LIB.delete_unused_expressions(mat)
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    assert not errors, (mat.get_name(), errors)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    scalars = [str(n) for n in LIB.get_scalar_parameter_names(mat)]
    vectors = [str(n) for n in LIB.get_vector_parameter_names(mat)]
    log.append(f'M_GoTGrass PBR params exposed: {len(scalars)} scalar {scalars}; {len(vectors)} vector {vectors}')
    return mat


def grass_material(debug):
    """生成或原位更新同一版草材质，不清空已有材质图。"""
    exists = unreal.EditorAssetLibrary.does_asset_exist(f'{GRASS}/Materials/M_GoTGrass')
    mat = owned('M_GoTGrass', f'{GRASS}/Materials', unreal.Material, unreal.MaterialFactoryNew())
    if exists:
        return expose_grass_pbr_params(update_grass_clumping_material(mat))
    setp(mat, two_sided=True, blend_mode=unreal.BlendMode.BLEND_OPAQUE, used_with_virtual_heightfield_mesh=True)
    uv0 = mnode(mat, unreal.MaterialExpressionTextureCoordinate, -2200, 0, coordinate_index=0)
    uv1 = mnode(mat, unreal.MaterialExpressionTextureCoordinate, -2200, 300, coordinate_index=1)
    uv2 = mnode(mat, unreal.MaterialExpressionTextureCoordinate, -2200, 600, coordinate_index=2)
    across, along = mask(mat, uv0, 'r', -2000, 0), mask(mat, uv0, 'g', -2000, 80)
    rnd, tier = mask(mat, uv1, 'r', -2000, 300), mask(mat, uv1, 'g', -2000, 380)
    cluster, kind = mask(mat, uv2, 'r', -2000, 600), mask(mat, uv2, 'g', -2000, 680)
    # colour: tier picks the palette, the random varies inside it, kind 2 (stiff grass) is drier
    green = lerp(mat, vec(mat, (0.078, 0.090, 0.010), -1700, -300), vec(mat, (0.048, 0.088, 0.015), -1700, -220), tier, -1500, -260)
    dry = vec(mat, (0.125, 0.110, 0.025), -1700, -140)
    is_k2 = mnode(mat, unreal.MaterialExpressionIf, -1700, 700)
    link(kind, '', is_k2, 'A'); link(const(mat, 1.5, -1850, 760), '', is_k2, 'B')
    link(const(mat, 0.55, -1850, 820), '', is_k2, 'A > B'); link(const(mat, 0.0, -1850, 880), '', is_k2, 'A < B')
    dry_amt = op(mat, unreal.MaterialExpressionMultiply, rnd, const(mat, 0.35, -1850, 960), -1550, 950)
    dry_amt = op(mat, unreal.MaterialExpressionAdd, dry_amt, is_k2, -1400, 900)
    sat = mnode(mat, unreal.MaterialExpressionSaturate, -1300, 900)
    link(dry_amt, '', sat, '')
    base = lerp(mat, green, dry, sat, -1150, -200)
    grad = mnode(mat, unreal.MaterialExpressionPower, -1700, 100)
    link(along, '', grad, 'Base'); link(const(mat, 0.7, -1850, 160), '', grad, 'Exp')
    tone = lerp(mat, const(mat, 0.55, -1550, 120), const(mat, 1.1, -1550, 170), grad, -1400, 120)
    vary = lerp(mat, const(mat, 0.85, -1550, 380), const(mat, 1.15, -1550, 420), rnd, -1400, 380)
    clump = lerp(mat, const(mat, 1.05, -1550, 600), const(mat, 0.9, -1550, 640), cluster, -1400, 600)
    off = op(mat, unreal.MaterialExpressionSubtract, across, const(mat, 0.5, -1850, 40), -1700, 20)
    mid = mnode(mat, unreal.MaterialExpressionAbs, -1550, 20)
    link(off, '', mid, '')
    vein = mnode(mat, unreal.MaterialExpressionSmoothStep, -1400, 20)
    link(const(mat, 0.12, -1550, 60), '', vein, 'Min'); link(const(mat, 0.0, -1550, 90), '', vein, 'Max'); link(mid, '', vein, 'Value')
    vein = lerp(mat, const(mat, 1.0, -1250, 40), const(mat, 1.18, -1250, 80), vein, -1100, 40)
    shade = op(mat, unreal.MaterialExpressionMultiply, tone, vary, -1200, 200)
    shade = op(mat, unreal.MaterialExpressionMultiply, shade, clump, -1050, 300)
    shade = op(mat, unreal.MaterialExpressionMultiply, shade, vein, -950, 150)
    albedo = op(mat, unreal.MaterialExpressionMultiply, base, shade, -800, 0)
    call = mnode(mat, unreal.MaterialExpressionMaterialFunctionCall, -800, 500)
    call.set_material_function(debug)
    link(albedo, '', call, 'Albedo')
    uv3 = mnode(mat, unreal.MaterialExpressionTextureCoordinate, -1100, 560, coordinate_index=3)   # VF: (rise / L, t)
    link(mask(mat, uv3, 'r', -950, 560), '', call, 'BladeRise')
    albedo = call
    depth = mnode(mat, unreal.MaterialExpressionPixelDepth, -1100, 1000)
    far = mnode(mat, unreal.MaterialExpressionSaturate, -800, 1000)
    link(op(mat, unreal.MaterialExpressionDivide, depth, const(mat, 2500, -1100, 1060), -950, 1000), '', far, '')
    rough = lerp(mat, const(mat, 0.78, -1000, 850), const(mat, 0.45, -1000, 900), grad, -850, 860)
    rough = lerp(mat, rough, const(mat, 0.85, -800, 1100), far, -650, 950)
    ao = lerp(mat, const(mat, 0.35, -800, 1200), const(mat, 1.0, -800, 1250), grad, -650, 1200)
    slab = mnode(mat, unreal.MaterialExpressionSubstrateSlabBSDF, -200, 300)
    slab.set_editor_property('sub_surface_type', unreal.MaterialSubSurfaceType.MSS_TWO_SIDED_WRAP)
    link(albedo, 'Albedo', slab, 'Diffuse Albedo')
    link(rough, '', slab, 'Roughness')
    link(vec(mat, (0.04, 0.04, 0.04), -400, 650), '', slab, 'F0')
    link(vec(mat, (0.05, 0.10, 0.015), -400, 720), '', slab, 'SSS MFP')
    link(call, 'Emissive', slab, 'Emissive Color')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    assert LIB.connect_material_property(ao, '', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    LIB.layout_material_expressions(mat)
    return expose_grass_pbr_params(update_grass_clumping_material(mat))


# ---------------------------------------------------------------- 6. actor
def grass_actor(mat, height, kind, gheight):
    actor = next((a for a in ACTORS.get_all_level_actors() if a.get_actor_label() == 'Pampas_GPUGrass'), None)
    if actor is None:
        actor = ACTORS.spawn_actor_from_class(unreal.GoTGrassActor, unreal.Vector(0, 0, 0))
        actor.set_actor_label('Pampas_GPUGrass')
    actor.set_folder_path('GoT_Pampas/Vegetation/Grass')
    actor.set_editor_property('tags', ['GoTPampas'])
    raw = KINDS_BIN.read_bytes()
    table = list(struct.unpack('<%df' % (len(raw) // 4), raw))
    comp = actor.get_editor_property('grass')
    current = comp.get_editor_property('material')
    if isinstance(current, unreal.MaterialInstance) and current.get_base_material() == mat:
        mat = current   # 保留用户在 M_GoTGrass 实例上调的参数
    setp(comp, material=mat, height_map=height, kind_map=kind, grass_height_map=gheight, kind_table=table,
         map_origin=unreal.Vector2D(-50450.0, -50450.0), map_size_cm=100900.0, height_scale=65535 * 50 / 128, height_bias=-32768 * 50 / 128)
    comp.mark_render_state_dirty() if hasattr(comp, 'mark_render_state_dirty') else None
    log.append(f'Pampas_GPUGrass: kinds {len(table) // 59}, spatially loaded={actor.get_editor_property("is_spatially_loaded")}')
    return actor


def verify_heights():
    """The GPU grass reads heightmap_1009.png: check the Landscape still matches it (traces at sample points)."""
    world = unreal.EditorLevelLibrary.get_editor_world()
    out = []
    for s in json.loads((TERRAIN / 'grass_samples.json').read_text('utf-8')):
        x, y = s['x_cm'], s['y_cm']
        hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector(x, y, 40000), unreal.Vector(x, y, -40000),
                                                     unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
        t = hit.to_tuple() if hit else None
        z = t[5].z if t else None
        who = t[9].get_class().get_name() if t and t[9] else '?'
        out.append((x, y, s['z_cm'], round(z, 1) if z is not None else None, who))
    log.append('height check (x, y, png, trace, hit class): ' + str(out))


def main():
    tex_h = import_map('heightmap_1009.png', 'T_GoTGrass_TerrainHeight')
    tex_k = import_map('grass_kind_1009.png', 'T_GoTGrass_Kind', nearest=True)
    tex_g = import_map('grass_height_1009.png', 'T_GoTGrass_Height')
    mpc = collection()
    rt = field_target()
    wf = wind_function(mpc, rt)
    normal_function()
    df = debug_function(mpc, rt)
    rewire_all(wf, df, mpc)
    gm = grass_material(df)
    grass_actor(gm, tex_h, tex_k, tex_g)
    verify_heights()
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    print('\n'.join(log))
    if warns:
        print('WARN', warns)


if __name__ in ('__main__', '__ue_remote__'):
    main()
