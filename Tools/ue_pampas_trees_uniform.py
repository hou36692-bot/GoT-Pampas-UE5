"""L_Pampas 枫树改为全图均匀撒点 + World Partition 空间加载 + HLOD（在打开的编辑器里经远程执行运行）。

  python -I Tools/mcp/ue_py.py Tools/ue_pampas_trees_uniform.py

- 旧规则按 4 个区域分体积（南林带密、小丘顶、北/西边缘），中间大片无树，体积常驻加载。
- 新规则：与植被同样的 5x5 分块（每块 136 m，覆盖 ±340 m），每块一个空间加载的 PCG 体积，
  分层抖动网格（22.67 m 一格、格内 ±8 m 抖动，块边整除不留缝）→ 地形射线（射线止于 -25 m，海面以下自然丢弃）
  → 法线转密度 + 密度过滤（去掉 >30° 陡坡）→ 随机朝向/缩放 → Nanite 实例（ISM，按块一个组件）。
- 远处卸载的块由 HLOD 接管：树体积与芒草远层体积都进 HLOD Instanced 层（实例化 HLOD 保留 Nanite），
  其上再有 Merged 层（近似网格，常驻）。HLOD 构建见 Tools/ue_build_hlod.ps1。
生成是异步的：本脚本注册 tick 回调，生成完毕后自动保存，并把结果写到 Tools/state/pampas_trees_uniform.json。
"""
import json
import time
import traceback
from pathlib import Path
import unreal

ROOT = Path('D:/HOU/Ghost of Tsushima')
REPORT = ROOT / 'Tools/state/pampas_trees_uniform.json'
OWNER = 'Pampas_20261107'
TREE = '/Game/GoT/Pampas/Meshes/SM_Maple_Pampas'
GRAPH_DIR = '/Game/GoT/Pampas/PCG'
GRAPH_NAME = 'PCG_PampasTrees_Uniform'
HLOD_INSTANCED = '/Game/GoT/Maps/L_Pampas_HLODLayer_Instanced'
VEG_GRAPH = '/Game/GoT/Pampas/PCG/PCG_PampasField'
VEG_HALF_CM = 34000
TILES = 5
TILE_CM = 2 * VEG_HALF_CM / TILES          # 13600
CELL_CM = TILE_CM / 6                      # 2266.7：每块 6x6 格，块边对齐
JITTER_CM = 800
RAY_START_CM = 30000                       # 射线起点 +300 m
RAY_END_Z_CM = -2500                       # 射线止于 -25 m（海面 -35 m），更低处无命中 → 丢弃
SLOPE_MIN_DENSITY = 0.87                   # 法线 z ≥ 0.87 ≈ 坡度 ≤ 30°
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
STATE = globals().setdefault('_GOT_TREES_STATE', {})
STATE.clear()
STATE.update(report=dict(actions=[], warnings=[]), start=time.monotonic())


def note(m):
    STATE['report']['actions'].append(m)
    unreal.log('PAMPAS_TREES_UNIFORM ' + m)


def warn(m):
    STATE['report']['warnings'].append(m)
    unreal.log_warning('PAMPAS_TREES_UNIFORM ' + m)


def write_report():
    REPORT.write_text(json.dumps(STATE['report'], indent=2, ensure_ascii=False, default=str), 'utf-8')


def owned_graph():
    path = f'{GRAPH_DIR}/{GRAPH_NAME}'
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        g = unreal.load_asset(path)
        assert unreal.EditorAssetLibrary.get_metadata_tag(g, 'GoTOwner') == OWNER, path
        return g
    g = unreal.AssetToolsHelpers.get_asset_tools().create_asset(GRAPH_NAME, GRAPH_DIR, unreal.PCGGraph, unreal.PCGGraphFactory())
    unreal.EditorAssetLibrary.set_metadata_tag(g, 'GoTOwner', OWNER)
    return g


def tree_graph(mesh):
    graph = owned_graph()
    for n in list(graph.get_editor_property('nodes')):
        graph.remove_node(n)
    grid, s = graph.add_node_of_type(unreal.PCGCreatePointsGridSettings)
    s.set_editor_property('grid_extents', unreal.Vector(TILE_CM / 2, TILE_CM / 2, 0))
    s.set_editor_property('cell_size', unreal.Vector(CELL_CM, CELL_CM, 100))
    s.set_editor_property('coordinate_space', unreal.PCGCoordinateSpace.LOCAL_COMPONENT)
    s.set_editor_property('cull_points_outside_volume', True)
    jit, s = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
    s.set_editor_property('offset_min', unreal.Vector(-JITTER_CM, -JITTER_CM, RAY_START_CM))
    s.set_editor_property('offset_max', unreal.Vector(JITTER_CM, JITTER_CM, RAY_START_CM))
    s.set_editor_property('absolute_offset', True)
    ray, s = graph.add_node_of_type(unreal.PCGWorldRaycastElementSettings)
    s.set_editor_property('raycast_mode', unreal.PCGWorldRaycastMode.NORMALIZED_WITH_LENGTH)
    s.set_editor_property('ray_direction', unreal.Vector(0, 0, -1))
    s.set_editor_property('ray_length', RAY_START_CM - RAY_END_Z_CM)
    s.set_editor_property('unbounded', True)
    s.set_editor_property('keep_original_point_on_miss', False)
    q = s.get_editor_property('world_query_params')
    q.set_editor_property('trace_complex', True)
    q.set_editor_property('ignore_pcg_hits', True)
    q.set_editor_property('actor_tag_filter', unreal.PCGWorldQueryFilter.EXCLUDE)
    q.set_editor_property('actor_tags_list', 'GoTPampas')          # 不打海面/边界墙
    s.set_editor_property('world_query_params', q)
    slope, s = graph.add_node_of_type(unreal.PCGNormalToDensitySettings)
    s.set_editor_property('normal', unreal.Vector(0, 0, 1))
    s.set_editor_property('strength', 1.0)
    dens, s = graph.add_node_of_type(unreal.PCGDensityFilterSettings)
    s.set_editor_property('lower_bound', SLOPE_MIN_DENSITY)
    s.set_editor_property('upper_bound', 1.0)
    tr, s = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
    s.set_editor_property('rotation_min', unreal.Rotator(roll=-3, pitch=-3, yaw=-180))
    s.set_editor_property('rotation_max', unreal.Rotator(roll=3, pitch=3, yaw=180))
    s.set_editor_property('absolute_rotation', True)
    s.set_editor_property('scale_min', unreal.Vector(0.75, 0.75, 0.75))
    s.set_editor_property('scale_max', unreal.Vector(1.25, 1.25, 1.25))
    s.set_editor_property('offset_min', unreal.Vector(0, 0, -30))
    s.set_editor_property('offset_max', unreal.Vector(0, 0, -30))
    sp, s = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)
    d = unreal.PCGSoftISMComponentDescriptor()
    d.set_editor_property('static_mesh', mesh)
    # Nanite 网格用 ISM：Nanite 自己做逐实例/逐簇的视锥与 HZB 剔除和 LOD，HISM 的 CPU 簇树对 Nanite 没有收益
    d.set_editor_property('component_class', unreal.InstancedStaticMeshComponent)
    for k, v in dict(instance_start_cull_distance=0, instance_end_cull_distance=120000, cast_shadow=True,
                     affect_distance_field_lighting=False, visible_in_ray_tracing=False, include_in_hlod=True).items():
        d.set_editor_property(k, v)
    body = d.get_editor_property('body_instance')
    body.set_editor_property('collision_profile_name', 'BlockAll')
    body.set_editor_property('collision_enabled', unreal.CollisionEnabled.QUERY_AND_PHYSICS)
    d.set_editor_property('body_instance', body)
    e = unreal.PCGMeshSelectorWeightedEntry()
    e.set_editor_property('descriptor', d)
    sel = s.get_editor_property('mesh_selector_parameters')
    sel.set_editor_property('mesh_entries', [e])
    chain = (grid, jit, ray, slope, dens, tr, sp)
    for i, n in enumerate(chain):
        n.set_node_position(i * 250, 0)
    for a, b, pin in [(grid, jit, 'In'), (jit, ray, 'Origins'), (ray, slope, 'In'), (slope, dens, 'In'), (dens, tr, 'In'), (tr, sp, 'In')]:
        assert graph.add_edge(a, 'Out', b, pin), (a.get_name(), b.get_name(), pin)
    unreal.EditorAssetLibrary.save_loaded_asset(graph)
    note(f'graph {GRAPH_NAME}: cell {CELL_CM:.0f} cm, jitter ±{JITTER_CM} cm, slope ≤30°, ray to {RAY_END_Z_CM} cm')
    return graph


def remove_old():
    removed = []
    for a in ACTORS.get_all_level_actors():
        if a.get_class().get_name() == 'PCGVolume' and a.get_actor_label().startswith('Pampas_Trees_'):
            removed.append(a.get_actor_label())
            pc = a.get_component_by_class(unreal.PCGComponent)
            if pc:
                pc.cleanup_local(True)
            ACTORS.destroy_actor(a)
    note(f'removed old tree volumes: {removed}')
    for name in ['ForestSouth', 'KnollTop', 'EdgeNorth', 'EdgeWest']:
        path = f'{GRAPH_DIR}/PCG_PampasTrees_{name}'
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            g = unreal.load_asset(path)
            if unreal.EditorAssetLibrary.get_metadata_tag(g, 'GoTOwner') == OWNER:
                unreal.EditorAssetLibrary.delete_asset(path)
                note(f'deleted old graph {path}')


def far_pampas_into_hlod(layer):
    """芒草远层（画到 1 km、不投影）进 HLOD：块卸载后远处芒草仍由 HLOD 实例显示。近层与草叶不进 HLOD。"""
    graph = unreal.load_asset(VEG_GRAPH)
    for n in graph.get_editor_property('nodes'):
        s = n.get_settings()
        if not isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
            continue
        sel = s.get_editor_property('mesh_selector_parameters')
        entries = list(sel.get_editor_property('mesh_entries'))
        d0 = entries[0].get_editor_property('descriptor')
        if d0.get_editor_property('instance_end_cull_distance') < 90000:
            continue
        for e in entries:
            d = e.get_editor_property('descriptor')
            d.set_editor_property('include_in_hlod', True)
            e.set_editor_property('descriptor', d)
        sel.modify()
        sel.set_editor_property('mesh_entries', entries)
    unreal.EditorAssetLibrary.save_loaded_asset(graph)
    vols, comps = [], 0
    for a in ACTORS.get_all_level_actors():
        if a.get_class().get_name() != 'PCGVolume' or not a.get_actor_label().startswith('Pampas_PCG_'):
            continue
        a.modify()
        a.set_editor_property('hlod_layer', layer)
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            far = c.get_editor_property('instance_end_cull_distance') >= 90000
            if c.get_editor_property('enable_auto_lod_generation') != far:
                c.modify()
                c.set_editor_property('enable_auto_lod_generation', far)
            comps += int(far)
        vols.append(a)
    note(f'far pampas HLOD-relevant: {comps} components in {len(vols)} vegetation volumes')
    return vols


def build():
    mesh = unreal.load_asset(TREE)
    layer = unreal.load_asset(HLOD_INSTANCED)
    assert mesh and layer
    remove_old()
    graph = tree_graph(mesh)
    STATE['veg_vols'] = far_pampas_into_hlod(layer)
    comps = []
    for ix in range(TILES):
        for iy in range(TILES):
            cx, cy = -VEG_HALF_CM + TILE_CM * (ix + 0.5), -VEG_HALF_CM + TILE_CM * (iy + 0.5)
            vol = ACTORS.spawn_actor_from_class(unreal.PCGVolume, unreal.Vector(cx, cy, 0))
            vol.set_actor_label(f'Pampas_Trees_{ix}_{iy}')
            vol.set_folder_path('GoT_Pampas/Vegetation/Trees')
            vol.set_actor_scale3d(unreal.Vector(TILE_CM / 200, TILE_CM / 200, 300))
            vol.set_editor_property('is_spatially_loaded', True)
            vol.set_editor_property('hlod_layer', layer)
            vol.set_editor_property('tags', ['GoTPampasTrees'])
            c = vol.pcg_component
            c.set_graph(graph)
            for k, v in dict(seed=7300 + ix * 10 + iy, generation_trigger=unreal.PCGComponentGenerationTrigger.GENERATE_ON_DEMAND,
                             regenerate_in_editor=False, is_component_partitioned=False).items():
                c.set_editor_property(k, v)
            comps.append(c)
    note(f'{len(comps)} tree tiles ({TILE_CM / 100:.0f} m), spatially loaded, HLOD layer Instanced')
    for c in comps:
        c.generate_local(True)
    STATE['pcg'] = comps
    STATE['gen'] = time.monotonic()
    STATE['cb'] = unreal.register_slate_post_tick_callback(tick)


def tick(dt):
    if STATE.get('busy'):
        return
    STATE['busy'] = True
    try:
        el = time.monotonic() - STATE['gen']
        if el > 600:
            raise RuntimeError('tree generation timeout')
        if el < 5 or not all(c.get_editor_property('generated') for c in STATE['pcg']):
            return
        counts = {}
        for c in STATE['pcg']:
            a = c.get_owner()
            counts[a.get_actor_label()] = sum(x.get_instance_count() for x in a.get_components_by_class(unreal.InstancedStaticMeshComponent))
        if sum(counts.values()) == 0 and el < 60:
            return
        STATE['report']['trees'] = counts
        STATE['report']['trees_total'] = sum(counts.values())
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        assert unreal.EditorLoadingAndSavingUtils.save_map(world, world.get_path_name().split('.')[0])
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        note(f"saved: {STATE['report']['trees_total']} trees")
        finish(True)
    except Exception:
        finish(False)
    finally:
        STATE['busy'] = False


def finish(passed):
    STATE['report']['passed'] = passed
    STATE['report']['elapsed_s'] = round(time.monotonic() - STATE['start'], 1)
    if not passed:
        STATE['report']['error'] = traceback.format_exc()
        unreal.log_error(STATE['report']['error'])
    if STATE.get('cb'):
        unreal.unregister_slate_post_tick_callback(STATE['cb'])
        STATE['cb'] = None
    write_report()


try:
    if REPORT.exists():
        REPORT.unlink()
    build()
    print('\n'.join(STATE['report']['actions']))
    print('generation started; poll Tools/state/pampas_trees_uniform.json')
except Exception:
    finish(False)
    print(STATE['report'].get('error'))
