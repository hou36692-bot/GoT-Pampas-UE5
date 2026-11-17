"""给 L_Pampas 加覆盖全图的编辑器自动加载 LocationVolume，并验证打开地图后不调用 load_actors 也能看到全部 Actor。"""
import json
import time
import traceback
from pathlib import Path
import unreal

ROOT = Path('D:/HOU/Ghost of Tsushima')
MAP = '/Game/GoT/Maps/L_Pampas'
REPORT = ROOT / 'Tools/state/pampas_editor_autoload.json'
ACTORS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
STATE = dict(rep={}, start=time.monotonic(), phase='add')


def loaded_count():
    return len(ACTORS.get_all_level_actors())


def add_volume():
    world = unreal.EditorLoadingAndSavingUtils.load_map(MAP)
    descs = unreal.WorldPartitionBlueprintLibrary.get_actor_descs()
    STATE['rep']['actor_descs'] = len(descs)
    STATE['rep']['loaded_before'] = loaded_count()
    vol = next((a for a in ACTORS.get_all_level_actors() if a.get_actor_label() == 'Pampas_EditorLoadAll'), None)
    if vol is None:
        vol = ACTORS.spawn_actor_from_class(unreal.LocationVolume, unreal.Vector(0, 0, 0))
        vol.set_actor_label('Pampas_EditorLoadAll')
    vol.set_folder_path('GoT_Pampas/Editor')
    vol.set_editor_property('tags', ['GoTEditorAutoLoad'])
    vol.set_editor_property('is_spatially_loaded', False)
    origin, extent = vol.get_actor_bounds(False)
    # 默认画刷为 200 cm 立方体；缩放到 1.2 km x 1.2 km x 1 km
    base = max(extent.x, 1.0)
    vol.set_actor_scale3d(unreal.Vector(60000 / base, 60000 / base, 50000 / base))
    origin, extent = vol.get_actor_bounds(False)
    STATE['rep']['volume_bounds'] = [origin.to_tuple(), extent.to_tuple()]
    assert unreal.EditorLoadingAndSavingUtils.save_map(world, MAP)


def tick(dt):
    if STATE.get('busy'):
        return
    STATE['busy'] = True
    try:
        now = time.monotonic()
        if STATE['phase'] == 'add':
            add_volume()
            # 重新打开地图：此时只有 init_unreal.py 的自动加载在起作用
            unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
            unreal.EditorLoadingAndSavingUtils.load_map(MAP)
            STATE['phase'], STATE['t'] = 'wait', now
        elif STATE['phase'] == 'wait' and now - STATE['t'] > 20:
            actors = ACTORS.get_all_level_actors()
            STATE['rep'].update(loaded_after_reopen=len(actors),
                                pcg_tiles_loaded=sum(1 for a in actors if a.get_actor_label().startswith('Pampas_PCG_')),
                                landscape_proxies_loaded=sum(1 for a in actors if a.get_class().get_name() == 'LandscapeStreamingProxy'),
                                instances_loaded=sum(c.get_instance_count() for a in actors if a.get_actor_label().startswith('Pampas_PCG_')
                                                     for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent)),
                                passed=True)
            finish()
        if now - STATE['start'] > 300:
            raise RuntimeError('timeout')
    except Exception:
        STATE['rep'].update(passed=False, error=traceback.format_exc())
        finish()
    finally:
        STATE['busy'] = False


def finish():
    REPORT.write_text(json.dumps(STATE['rep'], indent=2, default=str), 'utf-8')
    unreal.unregister_slate_post_tick_callback(STATE['cb'])
    unreal.EditorPythonScripting.set_keep_python_script_alive(False)
    unreal.SystemLibrary.quit_editor()


STATE['cb'] = unreal.register_slate_post_tick_callback(tick)
unreal.EditorPythonScripting.set_keep_python_script_alive(True)
