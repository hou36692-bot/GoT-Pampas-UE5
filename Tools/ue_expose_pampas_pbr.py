"""芒草 PBR 参数：把 M_PampasFoliage 的着色常量原位换成参数，建 MI_PampasFoliage 并挂到使用它的网格上。

  python -I Tools/mcp/ue_py.py Tools/ue_expose_pampas_pbr.py
参数默认值等于原常量，画面不变；可重复运行。ue_pampas_v2_vegetation.build() 重建材质后也会调用 apply()。
[适配] 数值都是 UE 近似初值，不是原版恢复参数。
"""
import importlib.util
from pathlib import Path
import unreal

MAT = '/Game/GoT/Pampas/Materials/M_PampasFoliage'
INST_DIR, INST_NAME = '/Game/GoT/Pampas/Materials', 'MI_PampasFoliage'
OWNER = 'Pampas_20261107'
GROUPS = ('01 反照率', '02 高光与法线', '03 透光', '04 穗部绒毛', '05 AO', '06 穗叶分区')


def _load_setup():
    path = Path(__file__).with_name('ue_grass_setup.py')
    spec = importlib.util.spec_from_file_location('got_pampas_pbr_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _load_setup()
LIB = S.LIB
P = S.grass_pbr_param
gi = S.graph_inputs


def only_input(mat, node):
    return list(LIB.get_inputs_for_material_expression(mat, node))[0]


def is_param(node, cls, name):
    return isinstance(node, cls) and str(node.get_editor_property('parameter_name')) == name


def insert_multiply(mat, consumer, pin, name, cls):
    """consumer.pin 前插一个 Multiply(原输入, 参数)；已插过则复用。返回 Multiply 节点。"""
    src = gi(mat, consumer)[pin]
    if isinstance(src, unreal.MaterialExpressionMultiply) and is_param(gi(mat, src).get('B'), cls, name):
        return src
    m = S.mnode(mat, unreal.MaterialExpressionMultiply, consumer.get_editor_property('material_expression_editor_x') - 180,
                consumer.get_editor_property('material_expression_editor_y') - 120)
    S.link(src, '', m, 'A')
    S.link(m, '', consumer, pin)
    return m


def expose_pampas_pbr_params(mat):
    g_alb, g_spec, g_sss, g_fuzz, g_ao, g_region = GROUPS
    slab = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL)
    ao = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    assert isinstance(slab, unreal.MaterialExpressionSubstrateSlabBSDF), 'Expected Substrate slab'
    assert isinstance(ao, unreal.MaterialExpressionLinearInterpolate), 'Expected AO lerp'
    pins = gi(mat, slab)

    # 01 反照率：整体乘色插在风场调试函数之前（重建后尚未接调试函数时直接插在 Slab 前）
    alb = pins['Diffuse Albedo']
    is_debug = isinstance(alb, unreal.MaterialExpressionMaterialFunctionCall) \
        and alb.get_editor_property('material_function').get_name() == 'MF_GoTWindDebug'
    consumer, pin = (alb, 'Albedo') if is_debug else (slab, 'Diffuse Albedo')
    tint = insert_multiply(mat, consumer, pin, 'PampasAlbedoTint', unreal.MaterialExpressionVectorParameter)
    P(mat, tint, 'B', 'PampasAlbedoTint', g_alb, 0, '最终反照率整体乘色（白=不变）', (1.0, 1.0, 1.0))
    blend = gi(mat, tint)['A']
    assert isinstance(blend, unreal.MaterialExpressionLinearInterpolate), 'Expected leaf/plume lerp'
    bi = gi(mat, blend)
    leaf, plume_sat, region = bi['A'], bi['B'], bi['Alpha']
    li = gi(mat, leaf)
    P(mat, li['A'], 'B', 'PampasLeafTint', g_alb, 1, '叶片：图集颜色乘色')
    vary = li['B']
    P(mat, gi(mat, vary)['A'], 'B', 'PampasLeafRandomBrightness', g_alb, 2, '叶片：逐实例随机亮度幅度')
    P(mat, vary, 'B', 'PampasLeafBaseBrightness', g_alb, 3, '叶片：基础亮度（最终 = 基础 + 随机×幅度）')
    boosted = only_input(mat, plume_sat)
    desat = gi(mat, boosted)['A']
    P(mat, desat, 'Alpha', 'PampasPlumeDesaturate', g_alb, 4, '穗部：去饱和程度（0=图集原色，1=全灰）')
    P(mat, gi(mat, desat)['B'], 'B', 'PampasPlumeGreyTint', g_alb, 5, '穗部：去饱和后的灰色偏色')
    P(mat, boosted, 'B', 'PampasPlumeBrightness', g_alb, 6, '穗部：提亮倍数（结果再截到 0..1）')

    # 02 高光与法线
    P(mat, slab, 'F0', 'PampasF0', g_spec, 0, '法线入射反射率（0.02≈2%）')
    rough = pins['Roughness']
    ri = gi(mat, rough)
    sub = ri['A']
    assert isinstance(sub, unreal.MaterialExpressionSubtract), 'Expected leaf roughness = 1 - gloss'
    P(mat, sub, 'A', 'PampasLeafRoughnessMax', g_spec, 1, '叶片：光泽贴图为 0 处的粗糙度（粗糙度 = 上限 - 光泽×强度）')
    gloss = insert_multiply(mat, sub, 'B', 'PampasLeafGlossScale', unreal.MaterialExpressionScalarParameter)
    P(mat, gloss, 'B', 'PampasLeafGlossScale', g_spec, 2, '叶片：NGT 光泽通道强度', 1.0)
    P(mat, rough, 'B', 'PampasPlumeRoughness', g_spec, 3, '穗部粗糙度')
    normal = pins['Normal']
    derive = gi(mat, normal)['TangentNormal'] if isinstance(normal, unreal.MaterialExpressionMaterialFunctionCall) else normal
    assert isinstance(derive, unreal.MaterialExpressionDeriveNormalZ), 'Expected DeriveNormalZ'
    P(mat, gi(mat, derive)['InXY'], 'B', 'PampasNormalStrength', g_spec, 4, 'NGT 法线 XY 强度')

    # 03 透光
    sss = pins['SSS MFP']
    si = gi(mat, sss)
    P(mat, si['A'], 'A', 'PampasLeafSSSMFP', g_sss, 0, '叶片次表面平均自由程颜色（透光色）')
    P(mat, si['A'], 'B', 'PampasPlumeSSSMFP', g_sss, 1, '穗部次表面平均自由程颜色')
    trans = si['B']
    P(mat, gi(mat, trans)['A'], 'B', 'PampasTransmissionScale', g_sss, 2, 'NGT 透光通道强度')
    P(mat, trans, 'B', 'PampasTransmissionBias', g_sss, 3, '透光基础量（MFP 倍数 = 透光通道×强度 + 基础）')
    P(mat, slab, 'SSS MFP Scale', 'PampasSSSMFPScale', g_sss, 4, 'MFP 整体倍数（Slab 默认 1）', 1.0)
    P(mat, slab, 'SSS Phase Anisotropy', 'PampasSSSPhaseAnisotropy', g_sss, 5, '透光相位各向异性 -1..1（Slab 默认 0）', 0.0)

    # 04 穗部绒毛
    P(mat, pins['Fuzz Amount'], 'B', 'PampasPlumeFuzzAmount', g_fuzz, 0, '穗部绒毛量（叶片为 0）')
    P(mat, slab, 'Fuzz Color', 'PampasFuzzColor', g_fuzz, 1, '绒毛颜色')

    # 05 AO
    P(mat, ao, 'A', 'PampasAORoot', g_ao, 0, '根部 AO')
    P(mat, ao, 'B', 'PampasAOTip', g_ao, 1, '顶部 AO')
    P(mat, only_input(mat, gi(mat, ao)['Alpha']), 'B', 'PampasAOHeightCm', g_ao, 2, 'AO 从根到顶的渐变高度（cm，网格局部 Z）')

    # 06 穗叶分区（图集 V 坐标阈值，穗部取色/粗糙度/透光/绒毛都用它）
    assert isinstance(region, unreal.MaterialExpressionSmoothStep)
    P(mat, region, 'Min', 'PampasPlumeMaskMin', g_region, 0, '图集 V 低于此值为叶片')
    P(mat, region, 'Max', 'PampasPlumeMaskMax', g_region, 1, '图集 V 高于此值为穗部')

    LIB.delete_unused_expressions(mat)
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    assert not errors, (mat.get_name(), errors)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    scalars = [str(n) for n in LIB.get_scalar_parameter_names(mat)]
    vectors = [str(n) for n in LIB.get_vector_parameter_names(mat)]
    print(f'M_PampasFoliage PBR params: {len(scalars)} scalar {scalars}; {len(vectors)} vector {vectors}')
    return mat


def ensure_instance(mat):
    path = f'{INST_DIR}/{INST_NAME}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        inst = unreal.load_asset(path)
        assert unreal.EditorAssetLibrary.get_metadata_tag(inst, 'GoTOwner') == OWNER, path
    else:
        inst = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            INST_NAME, INST_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
        unreal.EditorAssetLibrary.set_metadata_tag(inst, 'GoTOwner', OWNER)
    if inst.get_editor_property('parent') != mat:
        LIB.set_material_instance_parent(inst, mat)
    LIB.update_material_instance(inst)
    unreal.EditorAssetLibrary.save_loaded_asset(inst)
    return inst


def assign_instance(mat, inst):
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    changed = []
    for ref in reg.get_referencers(MAT, unreal.AssetRegistryDependencyOptions()) or []:
        mesh = unreal.load_asset(str(ref))
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        slots = list(mesh.get_editor_property('static_materials'))
        hit = [i for i, s in enumerate(slots) if s.get_editor_property('material_interface') == mat]
        for i in hit:
            mesh.set_material(i, inst)
        if hit:
            unreal.EditorAssetLibrary.save_loaded_asset(mesh)
            changed.append(mesh.get_name())
    print('meshes switched to MI_PampasFoliage:', changed)
    return changed


def apply(mat=None):
    mat = mat or unreal.load_asset(MAT)
    expose_pampas_pbr_params(mat)
    return ensure_instance(mat)


def main():
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    assert editor.get_game_world() is None, 'Stop PIE before updating pampas assets'
    mat = unreal.load_asset(MAT)
    inst = apply(mat)
    assign_instance(mat, inst)
    print('MI_PampasFoliage sees', len(LIB.get_scalar_parameter_names(inst)), 'scalar /',
          len(LIB.get_vector_parameter_names(inst)), 'vector params')


if __name__ in ('__main__', '__ue_remote__'):
    main()
