"""芒草/草叶跑图跳变优化（在打开的编辑器里经远程执行运行：python -I Tools/mcp/ue_py.py Tools/ue_pampas_lod_fade.py）。

跳变来源：
1. LOD 切换太近：屏幕尺寸 ≈ 包围球半径 / 距离（90° FOV），芒草 [1, 0.45, 0.2, 0.08] 意味着 1.8 m / 4 m / 10 m 就切 LOD，
   LOD3 只剩 36–64 顶点，跑动时近处卡片形状一直在变；草叶 [1, 0.3, 0.12, 0.05] 同理（2.8 m / 7 m / 17 m）。
2. 剔除没有过渡：草叶材质没有接 PerInstanceFadeAmount，到剔除距离直接消失；芒草只把透明度乘了 fade，
   透明遮罩在 fade≈0.4 时整片同时被裁掉，仍是一次跳变。剔除过渡带也只有 6–10 m。
修复：
- LOD 推远：芒草 [1, 0.08, 0.035, 0.015]（≈10 / 23 / 54 m），草叶 [1, 0.06, 0.03, 0.015]（≈14 / 28 / 57 m）。
- 芒草：开启 Dithered LOD Transition；剔除淡出改为 DitherTemporalAA 抖动溶解（TSR 抹平）。
- 草叶：不改成 Masked（避免 160 万实例失去 early-Z），改为在过渡带内用 WPO 把草丛缩回根部（fade 1→0）。
- 过渡带拉长：芒草近层 22→40 m，草叶远层 20→35 m，草叶近层 9→18 m（PCG 图与已生成组件同时改）。
"""
import unreal

LIB = unreal.MaterialEditingLibrary
MESH_EDITOR = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
log = []
LOD_SIZES = {'SM_Pampas_A': [1.0, 0.08, 0.035, 0.015], 'SM_Pampas_B': [1.0, 0.08, 0.035, 0.015], 'SM_Pampas_C': [1.0, 0.08, 0.035, 0.015],
             'SM_GrassBlades_A': [1.0, 0.06, 0.03, 0.015], 'SM_GrassBlades_B': [1.0, 0.06, 0.03, 0.015]}
# (旧 start, 旧 end) -> 新 start
CULL_START = {(3000, 4000): 2200, (2500, 3500): 2000, (1200, 1800): 900}


def node(mat, cls, x=0, y=0, **props):
    n = LIB.create_material_expression(mat, cls, x, y)
    for k, v in props.items():
        n.set_editor_property(k, v)
    return n


def link(a, out, b, pin):
    if LIB.connect_material_expressions(a, out, b, pin):
        return
    names = [str(n) for n in LIB.get_material_expression_input_names(b)]
    alt = next((n for n in names if n.lower().replace(' ', '').startswith(pin.lower().replace(' ', '')[:4])), None)
    assert alt and LIB.connect_material_expressions(a, out, b, alt), (a.get_name(), out, b.get_name(), pin, names)


def lods():
    for name, sizes in LOD_SIZES.items():
        m = unreal.load_asset(f'/Game/GoT/Pampas/Meshes/{name}')
        MESH_EDITOR.set_lod_screen_sizes(m, sizes)
        unreal.EditorAssetLibrary.save_loaded_asset(m)
        log.append(f'{name} LOD screen sizes {sizes} -> {[round(s, 3) for s in MESH_EDITOR.get_lod_screen_sizes(m)]}')


def foliage():
    mat = unreal.load_asset('/Game/GoT/Pampas/Materials/M_PampasFoliage')
    mat.set_editor_property('dithered_lod_transition', True)
    old = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_OPACITY_MASK)
    atlas = unreal.load_asset('/Game/GoT/Pampas/Textures/T_PampasAtlas_D')
    tex = node(mat, unreal.MaterialExpressionTextureSample, -700, 1700, texture=atlas)
    fade = node(mat, unreal.MaterialExpressionPerInstanceFadeAmount, -700, 1900)
    dither = node(mat, unreal.MaterialExpressionMaterialFunctionCall, -500, 1900)
    dither.set_material_function(unreal.load_asset('/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA'))
    link(fade, '', dither, 'Alpha Threshold')
    mask = node(mat, unreal.MaterialExpressionMultiply, -300, 1800)
    link(tex, 'A', mask, 'A'); link(dither, '', mask, 'B')
    assert LIB.connect_material_property(mask, '', unreal.MaterialProperty.MP_OPACITY_MASK)
    if old:
        LIB.delete_material_expression(mat, old)
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log.append(f'M_PampasFoliage dithered LOD + dithered cull fade; errors={errors}')


def blades():
    mat = unreal.load_asset('/Game/GoT/Pampas/Materials/M_PampasGrassBlade')
    old = LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    assert old, 'grass WPO missing'
    local = node(mat, unreal.MaterialExpressionLocalPosition, -700, 1800)
    to_world = node(mat, unreal.MaterialExpressionTransform, -500, 1800,
                    transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL,
                    transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    link(local, '', to_world, '')
    fade = node(mat, unreal.MaterialExpressionPerInstanceFadeAmount, -700, 1950)
    gone = node(mat, unreal.MaterialExpressionOneMinus, -500, 1950)
    link(fade, '', gone, '')
    shrink = node(mat, unreal.MaterialExpressionMultiply, -300, 1850)
    link(to_world, '', shrink, 'A'); link(gone, '', shrink, 'B')
    back = node(mat, unreal.MaterialExpressionMultiply, -150, 1850)       # 指向根部：-偏移
    link(shrink, '', back, 'A'); link(node(mat, unreal.MaterialExpressionConstant, -300, 1950, r=-1.0), '', back, 'B')
    total = node(mat, unreal.MaterialExpressionAdd, 50, 1500)
    link(old, '', total, 'A'); link(back, '', total, 'B')
    assert LIB.connect_material_property(total, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    errors = [str(e) for e in (LIB.recompile_material(mat) or [])]
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log.append(f'M_PampasGrassBlade WPO shrink-to-root over cull fade band; errors={errors}')


def culls():
    graph = unreal.load_asset('/Game/GoT/Pampas/PCG/PCG_PampasField')
    for n in graph.get_editor_property('nodes'):
        s = n.get_settings()
        if not isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
            continue
        sel = s.get_editor_property('mesh_selector_parameters')
        entries = list(sel.get_editor_property('mesh_entries'))
        changed = False
        for e in entries:
            d = e.get_editor_property('descriptor')
            key = (d.get_editor_property('instance_start_cull_distance'), d.get_editor_property('instance_end_cull_distance'))
            if key in CULL_START:
                d.set_editor_property('instance_start_cull_distance', CULL_START[key])
                e.set_editor_property('descriptor', d)
                changed = True
        if changed:
            sel.modify()
            sel.set_editor_property('mesh_entries', entries)
    unreal.EditorAssetLibrary.save_loaded_asset(graph)
    pkgs, count = [], 0
    for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
        if a.get_class().get_name() != 'PCGVolume' or not a.get_actor_label().startswith('Pampas_PCG_'):
            continue
        hit = False
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            key = (c.get_editor_property('instance_start_cull_distance'), c.get_editor_property('instance_end_cull_distance'))
            if key in CULL_START:
                c.modify()
                c.set_editor_property('instance_start_cull_distance', CULL_START[key])
                c.set_cull_distances(CULL_START[key], key[1])
                count += 1; hit = True
        if hit:
            a.modify(); pkgs.append(a.get_package())
    ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True) if pkgs else True
    log.append(f'cull fade bands widened on {count} components / {len(pkgs)} volumes (saved {ok})')


lods()
foliage()
blades()
culls()
print('\n'.join(log))
