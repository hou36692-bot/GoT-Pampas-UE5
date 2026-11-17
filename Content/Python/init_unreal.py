"""GhostOfTsushima_ 编辑器启动脚本（项目规范：World Partition 地图在编辑器中必须能直接看到并编辑场景）。

打开地图时，自动加载带标签 GoTEditorAutoLoad 的 LocationVolume。只影响编辑器里加载了哪些 Actor，
运行时（PIE/游戏）仍按 World Partition 网格流式加载。
"""
import unreal

TAG = 'GoTEditorAutoLoad'


def _load_auto_volumes():
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not world or not world.get_world_settings().get_editor_property('world_partition'):
            return
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        volumes = [a for a in actors if isinstance(a, unreal.LocationVolume) and a.actor_has_tag(TAG)]
        for volume in volumes:
            if not volume.is_loaded():
                volume.load()
        if volumes:
            unreal.log(f'GoT editor autoload: loaded {len(volumes)} location volume(s) in {world.get_name()}')
    except Exception as error:
        unreal.log_warning(f'GoT editor autoload failed: {error}')


_pending = {'handle': None}


def _deferred(delta):
    unreal.unregister_slate_post_tick_callback(_pending['handle'])
    _pending['handle'] = None
    _load_auto_volumes()


def _schedule():
    if _pending['handle'] is None:
        _pending['handle'] = unreal.register_slate_post_tick_callback(_deferred)


def _on_map_opened(filename, as_template):
    _schedule()


try:
    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).on_map_opened.add_callable(_on_map_opened)
    _schedule()   # 启动地图在本脚本运行前就已打开
except Exception as _error:
    unreal.log_warning(f'GoT editor autoload not installed: {_error}')
