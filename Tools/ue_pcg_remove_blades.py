"""P5: remove the two grass-blade layers (PCG HISM grass) from PCG_PampasField and regenerate the vegetation tiles.
Grass is now the GPU Bezier grass (AGoTGrassActor). Run in the open editor:
  python -I Tools/mcp/ue_py.py Tools/ue_pcg_remove_blades.py          (removes + starts generation)
  python -I Tools/mcp/ue_py.py Tools/ue_pcg_remove_blades.py          (again: reports progress, saves when all tiles are done)
"""
import unreal

ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
g = unreal.load_asset('/Game/GoT/Pampas/PCG/PCG_PampasField')
blade_rows = set()
for n in g.get_editor_property('nodes'):
    s = n.get_settings()
    if isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
        sel = s.get_editor_property('mesh_selector_parameters')
        names = [e.get_editor_property('descriptor').get_editor_property('static_mesh').get_name() for e in sel.get_editor_property('mesh_entries')]
        if any('GrassBlades' in m for m in names):
            blade_rows.add(n.get_node_position()[1])
comps = [a.pcg_component for a in ACTORS.get_all_level_actors()
         if a.get_class().get_name() == 'PCGVolume' and a.get_actor_label().startswith('Pampas_PCG_')]
if blade_rows:
    removed = [n for n in list(g.get_editor_property('nodes')) if n.get_node_position()[1] in blade_rows]
    for n in removed:
        g.remove_node(n)
    unreal.EditorAssetLibrary.save_loaded_asset(g)
    print('removed', len(removed), 'nodes in rows', sorted(blade_rows))
    for c in comps:
        c.generate_local(True)
    print('generation started for', len(comps), 'tiles')
else:
    done = sum(1 for c in comps if c.get_editor_property('generated'))
    blades = 0
    total = 0
    for a in ACTORS.get_all_level_actors():
        if a.get_class().get_name() != 'PCGVolume':
            continue
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            n = c.get_instance_count()
            total += n
            if c.static_mesh and 'GrassBlades' in c.static_mesh.get_name():
                blades += n
    print(f'tiles generated {done}/{len(comps)}; instances {total}, grass-blade instances left {blades}')
    if done == len(comps) and blades == 0:
        unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
        print('saved')
