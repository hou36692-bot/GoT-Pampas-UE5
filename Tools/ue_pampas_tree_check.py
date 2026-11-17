"""给枫树网格设置 Nanite Preserve Area，并验证 PCG 树实例的树干碰撞：对几棵树做水平射线检测。"""
import json, unreal
out = {}
mesh = unreal.load_asset('/Game/GoT/Pampas/Meshes/SM_Maple_Pampas')
world = unreal.EditorLoadingAndSavingUtils.load_map('/Game/GoT/Maps/L_Pampas')
unreal.WorldPartitionBlueprintLibrary.load_actors([d.get_editor_property('guid') for d in unreal.WorldPartitionBlueprintLibrary.get_actor_descs()])
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
vol = next(a for a in actors if a.get_actor_label() == 'Pampas_Trees_KnollTop')
comp = vol.get_components_by_class(unreal.InstancedStaticMeshComponent)[0]
out['collision'] = dict(profile=str(comp.get_collision_profile_name()), enabled=str(comp.get_collision_enabled()))
hits = []
for i in range(min(4, comp.get_instance_count())):
    t = comp.get_instance_transform(i, True)
    p = t.translation
    start = unreal.Vector(p.x - 300, p.y, p.z + 150)
    end = unreal.Vector(p.x + 300, p.y, p.z + 150)
    h = unreal.SystemLibrary.line_trace_single(world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [], unreal.DrawDebugTrace.NONE, True)
    tup = h.to_tuple() if h else None
    hits.append(dict(instance=i, hit=bool(tup and tup[0]), component=(tup[9].get_class().get_name() if tup and tup[0] and tup[9] else None)))
out['trunk_traces'] = hits
open('D:/HOU/Ghost of Tsushima/Tools/state/pampas_tree_check.json', 'w').write(json.dumps(out, indent=1))
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
unreal.SystemLibrary.quit_editor()
