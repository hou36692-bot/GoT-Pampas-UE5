"""Trees: stop WPO wind beyond 120 m (Nanite VSM pages of animated trees are re-rendered every frame; far trees barely move).
Run in the open editor via remote execution. Updates the PCG graph descriptor and the generated components."""
import unreal

DIST = 12000.0
graph = unreal.load_asset('/Game/GoT/Pampas/PCG/PCG_PampasTrees_Uniform')
for n in graph.get_editor_property('nodes'):
    s = n.get_settings()
    if isinstance(s, unreal.PCGStaticMeshSpawnerSettings):
        sel = s.get_editor_property('mesh_selector_parameters')
        entries = list(sel.get_editor_property('mesh_entries'))
        for e in entries:
            d = e.get_editor_property('descriptor')
            d.set_editor_property('world_position_offset_disable_distance', int(DIST))
            e.set_editor_property('descriptor', d)
        sel.modify()
        sel.set_editor_property('mesh_entries', entries)
unreal.EditorAssetLibrary.save_loaded_asset(graph)
pkgs, n = [], 0
for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():
    if a.get_actor_label().startswith('Pampas_Trees_'):
        for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
            c.modify()
            c.set_editor_property('world_position_offset_disable_distance', int(DIST))
            n += 1
        a.modify()
        pkgs.append(a.get_package())
print('tree components', n, 'saved', unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True))
