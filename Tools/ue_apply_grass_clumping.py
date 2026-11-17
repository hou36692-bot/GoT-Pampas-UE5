"""定向应用中景草簇初值；仅改 M_GoTGrass 和 Pampas_GPUGrass 的覆盖参数。

通过 Tools/mcp/ue_py.py 运行本文件。导入不会改资产；apply_grass_clumping(profile=None)
只更新材质，profile='middle_ground' 才应用本轮组件初值。数值均为 UE 适配，不是原版参数声明。
"""
import hashlib
import importlib.util
import struct
from pathlib import Path
import unreal


def load_setup():
    path = Path(__file__).with_name('ue_grass_setup.py')
    spec = importlib.util.spec_from_file_location('got_grass_clumping_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_hash(component):
    values = list(component.get_editor_property('kind_table'))
    return hashlib.sha256(struct.pack(f'<{len(values)}f', *values)).hexdigest()


def apply_component_profile(component, profile):
    if profile is None:
        return
    assert profile == 'middle_ground', profile
    overrides = list(component.get_editor_property('kind_overrides'))
    matches = [i for i, item in enumerate(overrides) if item.get_editor_property('kind_index') == 2]
    assert len(matches) <= 1, 'Duplicate overrides for kind 2'
    override = overrides[matches[0]] if matches else unreal.GoTGrassKindOverride()
    for key, value in {'kind_index': 2, 'enabled': True, 'height_width_variation': 0.8,
                       'wind_coefficient': 0.45}.items():
        override.set_editor_property(key, value)
    if matches:
        overrides[matches[0]] = override
    else:
        overrides.append(override)
    component.set_editor_property('kind_overrides', overrides)
    for key, value in {'clump_normal_start_cm': 1500.0, 'clump_normal_end_cm': 6000.0,
                       'clump_normal_strength': 0.6}.items():
        component.set_editor_property(key, value)
        assert abs(component.get_editor_property(key) - value) < 1e-5, key
    effective = list(component.get_effective_kind_table())
    assert abs(effective[2 * 59 + 228 // 4] - 0.8) < 1e-5, 'Effective kind 2 height/width variation'
    assert abs(effective[2 * 59 + 200 // 4] - 0.45) < 1e-5, 'Effective kind 2 wind coefficient'
    print('Applied middle_ground UE adaptation: kind 2 enabled, height/width=.8, wind=.45; '
          'clump normal=15..60 m, strength=.6')


def apply_grass_clumping(profile=None):
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = editor.get_editor_world()
    assert world and world.get_path_name() == '/Game/GoT/Maps/L_Pampas.L_Pampas', str(world)
    assert editor.get_game_world() is None, 'Stop PIE before updating grass assets'
    assert profile in (None, 'middle_ground'), profile
    setup = load_setup()
    mat = unreal.load_asset('/Game/GoT/Grass/Materials/M_GoTGrass')
    assert mat and unreal.EditorAssetLibrary.get_metadata_tag(mat, 'GoTOwner') == setup.OWNER, 'Existing owned grass material required'
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    matches = [a for a in actors if a.get_actor_label() == 'Pampas_GPUGrass']
    assert len(matches) == 1, ('Expected one Pampas_GPUGrass', len(matches))
    component = matches[0].get_editor_property('grass')
    assigned = component.get_editor_property('material')
    assert assigned == mat or assigned.get_base_material() == mat, 'GPU grass must use M_GoTGrass or its instance'
    original_table = table_hash(component)
    original_maps = {name: component.get_editor_property(name)
                     for name in ('height_map', 'kind_map', 'grass_height_map')}
    setup.update_grass_clumping_material(mat)
    apply_component_profile(component, profile)
    assert table_hash(component) == original_table, 'Captured base KindTable changed'
    assert all(component.get_editor_property(name) == value for name, value in original_maps.items()), 'Grass maps changed'
    assert component.get_editor_property('material') == assigned, 'Grass material assignment changed'
    assert unreal.EditorAssetLibrary.save_loaded_asset(mat), 'Failed to save M_GoTGrass'
    if profile is not None:
        assert unreal.EditorLoadingAndSavingUtils.save_map(world, '/Game/GoT/Maps/L_Pampas'), 'Failed to save L_Pampas component profile'
    print('\n'.join(setup.log))
    print('Grass clumping applied: base KindTable and maps preserved; wind, pampas functions and PCG untouched')


if __name__ in ('__main__', '__ue_remote__'):
    apply_grass_clumping(profile='middle_ground')
