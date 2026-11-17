"""远景发白修复（在打开的编辑器里经远程执行运行：python -I Tools/mcp/ue_py.py Tools/ue_pampas_far_field.py）。

原因：芒草远层只画到 90 m，之外只剩地形；地形远景用的是提亮去饱和的米色贴图（线性反照率约 0.6），
于是 90 m 外整片发白，和近处绿底白穗断开。截帧第 2 帧里芒草穗一直画到海边。
修复：
1. 芒草远层（2 m 间距、不投影）的剔除距离拉到 1 km，远处靠 LOD3（36–64 顶点）承担；
2. 芒草图集开启 alpha coverage 保持，远处 mip 不把穗吃掉；
3. 地形远景改成深绿底 + 贴图亮度做轻微明暗变化（穗由几何提供，地表只露在穗之间）。
"""
import unreal

LIB = unreal.MaterialEditingLibrary
FAR_START, FAR_END = 90000, 100000
GRAPH = '/Game/GoT/Pampas/PCG/PCG_PampasField'
log = []


def node(mat, cls, x=0, y=0, **props):
    n = LIB.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def link(a, out, b, pin):
    assert LIB.connect_material_expressions(a, out, b, pin), (a.get_name(), out, b.get_name(), pin,
                                                              [str(n) for n in LIB.get_material_expression_input_names(b)])


def const(mat, v, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant, x, y, r=v)


def vec(mat, rgb, x=0, y=0):
    return node(mat, unreal.MaterialExpressionConstant3Vector, x, y, constant=unreal.LinearColor(*rgb, 1))


def op(mat, cls, a, b, x=0, y=0, out_a=''):
    n = node(mat, cls, x, y)
    link(a, out_a, n, 'A'); link(b, '', n, 'B')
    return n


def lerp(mat, a, b, alpha, x=0, y=0):
    n = node(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
    link(a, '', n, 'A'); link(b, '', n, 'B'); link(alpha, '', n, 'Alpha')
    return n


def atlas_alpha_coverage():
    tex = unreal.load_asset('/Game/GoT/Pampas/Textures/T_PampasAtlas_D')
    tex.set_editor_property('do_scale_mips_for_alpha_coverage', True)
    tex.set_editor_property('alpha_coverage_thresholds', unreal.Vector4(0, 0, 0, 0.4))   # = 材质 opacity clip 0.4
    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    log.append('T_PampasAtlas_D alpha coverage 0.4')


def far_layer_cull():
    graph = unreal.load_asset(GRAPH)
    for n in graph.get_editor_property('nodes'):
        s = n.get_settings()
        if not isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
            continue
        sel = s.get_editor_property('mesh_selector_parameters')
        entries = list(sel.get_editor_property('mesh_entries'))
        d0 = entries[0].get_editor_property('descriptor')
        if d0.get_editor_property('instance_end_cull_distance') != 9000 or 'Pampas' not in d0.get_editor_property('static_mesh').get_name():
            continue
        for e in entries:
            d = e.get_editor_property('descriptor')
            d.set_editor_property('instance_start_cull_distance', FAR_START)
            d.set_editor_property('instance_end_cull_distance', FAR_END)
            e.set_editor_property('descriptor', d)
        sel.modify()
        sel.set_editor_property('mesh_entries', entries)
        log.append(f'graph {n.get_name()} far pampas cull -> {FAR_START}/{FAR_END}')
    unreal.EditorAssetLibrary.save_loaded_asset(graph)

    # 已生成的组件直接改，不必重跑 162 万实例的生成
    changed, actors = 0, []
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_class().get_name() != 'PCGVolume':
            continue
        hit = False
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            m = c.get_editor_property('static_mesh')
            if m and m.get_name().startswith('SM_Pampas_') and c.get_editor_property('instance_end_cull_distance') in (9000, FAR_END):
                c.modify()
                c.set_editor_property('instance_start_cull_distance', FAR_START)
                c.set_editor_property('instance_end_cull_distance', FAR_END)
                c.set_cull_distances(FAR_START, FAR_END)
                changed += 1; hit = True
        if hit:
            a.modify(); actors.append(a)
    log.append(f'{changed} far HISM components in {len(actors)} volumes updated')
    return actors


def terrain_material():
    mat = unreal.load_asset('/Game/GoT/Pampas/Materials/M_PampasTerrain')
    LIB.delete_all_material_expressions(mat)
    world = node(mat, unreal.MaterialExpressionWorldPosition, -2000, 0)
    xy = node(mat, unreal.MaterialExpressionComponentMask, -1800, 0, r=True, g=True, b=False, a=False)
    link(world, '', xy, '')
    uv_a = op(mat, unreal.MaterialExpressionDivide, xy, const(mat, 700), -1600, 0)
    uv_b = op(mat, unreal.MaterialExpressionDivide, xy, const(mat, 1900), -1600, 120)
    far1 = node(mat, unreal.MaterialExpressionTextureSample, -1400, 0, texture=unreal.load_asset('/Game/GoT/Pampas/Textures/T_PampasField_Far_A'))
    link(uv_a, '', far1, 'UVs')
    far2 = node(mat, unreal.MaterialExpressionTextureSample, -1400, 250, texture=unreal.load_asset('/Game/GoT/Pampas/Textures/T_PampasField_Far_B'))
    link(uv_b, '', far2, 'UVs')
    macro = node(mat, unreal.MaterialExpressionNoise, -1400, 500, scale=0.0004, levels=4, output_min=0, output_max=1,
                 noise_function=unreal.NoiseFunction.NOISEFUNCTION_GRADIENT_ALU)
    link(world, '', macro, 'World Position')
    far = lerp(mat, far1, far2, macro, -1150, 100)
    lum = node(mat, unreal.MaterialExpressionDotProduct, -1000, 100)
    link(far, '', lum, 'A'); link(vec(mat, (0.2126, 0.7152, 0.0722)), '', lum, 'B')
    # 贴图亮度（线性 0.13–0.9）只做 0.75–1.2 倍的明暗起伏，不再直接当颜色
    shade = op(mat, unreal.MaterialExpressionMultiply, lum, const(mat, 0.55), -850, 100)
    shade = op(mat, unreal.MaterialExpressionAdd, shade, const(mat, 0.72), -700, 100)
    near = lerp(mat, vec(mat, (0.035, 0.060, 0.012)), vec(mat, (0.055, 0.075, 0.018)), macro, -1000, 380)
    far_col = lerp(mat, vec(mat, (0.050, 0.068, 0.020)), vec(mat, (0.075, 0.085, 0.032)), macro, -850, 250)
    far_col = op(mat, unreal.MaterialExpressionMultiply, far_col, shade, -550, 150)
    depth = node(mat, unreal.MaterialExpressionPixelDepth, -1150, 560)
    dist = op(mat, unreal.MaterialExpressionSubtract, depth, const(mat, 4000), -1000, 560)
    ratio = op(mat, unreal.MaterialExpressionDivide, dist, const(mat, 6000), -850, 560)
    sat = node(mat, unreal.MaterialExpressionSaturate, -700, 560)
    link(ratio, '', sat, '')
    grass = lerp(mat, near, far_col, sat, -450, 250)
    normal_ws = node(mat, unreal.MaterialExpressionVertexNormalWS, -1150, 760)
    nz = node(mat, unreal.MaterialExpressionComponentMask, -1000, 760, r=False, g=False, b=True, a=False)
    link(normal_ws, '', nz, '')
    steep = node(mat, unreal.MaterialExpressionSmoothStep, -800, 760)
    link(const(mat, 0.86), '', steep, 'Min'); link(const(mat, 0.66), '', steep, 'Max'); link(nz, '', steep, 'Value')
    low = node(mat, unreal.MaterialExpressionSmoothStep, -800, 980)
    zc = node(mat, unreal.MaterialExpressionComponentMask, -1000, 980, r=False, g=False, b=True, a=False)
    link(world, '', zc, '')
    link(const(mat, -2600), '', low, 'Min'); link(const(mat, -3300), '', low, 'Max'); link(zc, '', low, 'Value')
    base = lerp(mat, grass, vec(mat, (0.28, 0.28, 0.27)), steep, -300, 400)
    base = lerp(mat, base, vec(mat, (0.20, 0.18, 0.15)), low, -150, 500)
    slab = node(mat, unreal.MaterialExpressionSubstrateSlabBSDF, 50, 300)
    link(base, '', slab, 'Diffuse Albedo')
    link(const(mat, 0.9), '', slab, 'Roughness')
    link(vec(mat, (0.04, 0.04, 0.04)), '', slab, 'F0')
    assert LIB.connect_material_property(slab, '', unreal.MaterialProperty.MP_FRONT_MATERIAL)
    LIB.layout_material_expressions(mat)
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log.append(f'M_PampasTerrain far = dark green x texture shade; errors={errors}')


def cached_preexposure():
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.SystemLibrary.execute_console_command(world, 'r.EyeAdaptation.CachedLightingPreExposure 8')
    log.append('r.EyeAdaptation.CachedLightingPreExposure 8 (live)')


atlas_alpha_coverage()
actors = far_layer_cull()
terrain_material()
cached_preexposure()
pkgs = []
for a in actors:
    try:
        pkgs.append(a.get_package())
    except Exception:
        pkgs.append(a.get_outermost())
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True)
log.append(f'saved {len(pkgs)} actor packages: {ok}')
print('\n'.join(log))
