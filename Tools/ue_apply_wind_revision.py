"""仅更新现有风材质函数、三个活动植被材质及控制器；不重建场景或导入贴图。

通过 Tools/mcp/ue_py.py 执行本文件，明确应用 first_pass 调参组。
需要只修材质时，可导入本模块并调用 apply_wind_revision(profile=None)。
公开资料确定两层风的结构；以下数值与圆弧网格变形均为 UE 适配，未经原版参数等价验证。
"""
import importlib.util
import math
from pathlib import Path
import unreal


FIRST_PASS = {
    'time_scale': 1.0,
    'wind_speed_cm_per_sec': 1500.0,
    'gust_noise_scale': 0.0004,
    'gust_evolve_per_sec': 0.049,
    'gust_gain': 1.0,
    'gust_noise_mul': 2.0,
    'gust_noise_add': -0.5,
    'detail_noise_scale': 0.002,
    'detail_strength': 0.25,
    'grass_flutter_strength': 0.2,
}
FIRST_PASS_PAMPAS = {'wind_coefficient': 1.0, 'bend_degrees': 80.0, 'flutter_strength': 0.2}


def load_setup():
    path = Path(__file__).with_name('ue_grass_setup.py')
    spec = importlib.util.spec_from_file_location('got_grass_setup_revision', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def output_nodes(setup, function):
    # UE Python 不公开输出 GUID；验证同一个输出 UObject 被复用，并另查材质根连接。
    return {str(n.get_editor_property('output_name')): n
            for n in setup.LIB.get_material_function_expressions(function)
            if isinstance(n, unreal.MaterialExpressionFunctionOutput)}


def stem_radius_cm(setup):
    """三个实际芒草网格的局部 XY 包围盒，向上取整并留 4 cm 余量。"""
    radius = 0.0
    for name in ('SM_Pampas_A', 'SM_Pampas_B', 'SM_Pampas_C'):
        mesh = unreal.load_asset(f'/Game/GoT/Pampas/Meshes/{name}')
        assert mesh, name
        bounds = mesh.get_bounds()
        x = abs(bounds.origin.x) + bounds.box_extent.x
        y = abs(bounds.origin.y) + bounds.box_extent.y
        radius = max(radius, math.hypot(x, y))
    result = math.ceil(radius) + 4.0
    assert result > 0.0
    setup.log.append(f'Stem radius: mesh conservative bound={radius:.3f} cm, protected radius={result:.1f} cm')
    return result


def apply_profile(profile):
    if profile is None:
        return
    assert profile == 'first_pass', profile
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    controller = next(a for a in actors if a.get_actor_label() == 'Pampas_WindController')
    params = controller.get_editor_property('params')
    for key, value in FIRST_PASS.items():
        params.set_editor_property(key, value)
    pampas = params.get_editor_property('pampas')
    for key, value in FIRST_PASS_PAMPAS.items():
        pampas.set_editor_property(key, value)
    params.set_editor_property('pampas', pampas)
    controller.set_editor_property('params', params)
    print('Applied first_pass UE adaptation parameters:', FIRST_PASS, FIRST_PASS_PAMPAS)


def apply_wind_revision(profile=None):
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = editor.get_editor_world()
    assert world and world.get_path_name() == '/Game/GoT/Maps/L_Pampas.L_Pampas', str(world)
    assert editor.get_game_world() is None, 'Stop PIE before updating wind materials'
    setup = load_setup()
    wf = unreal.load_asset(f'{setup.WIND}/MF_GoTWind')
    nf = unreal.load_asset(f'{setup.WIND}/MF_GoTWindNormal')
    rt = unreal.load_asset(f'{setup.WIND}/RT_GoTInteraction')
    assert wf and nf and rt, 'Existing wind assets required'
    before = {wf: output_nodes(setup, wf), nf: output_nodes(setup, nf)}
    materials = [unreal.load_asset(f'/Game/GoT/Pampas/Materials/{name}') for name in setup.ACTIVE_WIND_USERS]
    assert all(materials)
    roots = {mat: (setup.LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET),
                   setup.LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL))
             for mat in materials}
    mpc = setup.collection(preserve_existing=True)
    setup.wind_function(mpc, rt)
    setup.normal_function()
    for function, nodes in before.items():
        after = output_nodes(setup, function)
        assert all(after.get(name) == node for name, node in nodes.items()), ('Function output node replaced', function.get_name())
    radius = stem_radius_cm(setup)
    for mat in materials:
        setup.wire_wind_material(mat, wf, nf, mpc, radius)
        after = (setup.LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET),
                 setup.LIB.get_material_property_input_node(mat, unreal.MaterialProperty.MP_FRONT_MATERIAL))
        assert after == roots[mat], (mat.get_name(), 'Material root changed')
        errors = [str(e) for e in (setup.LIB.recompile_material(mat) or [])]
        assert not errors, (mat.get_name(), errors)
        unreal.EditorAssetLibrary.save_loaded_asset(mat)
    apply_profile(profile)
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    print('\n'.join(setup.log))
    if setup.warns:
        print('WARN', setup.warns)
    print('Wind revision complete: output nodes and material roots preserved; no terrain/PCG/texture rebuild')


if __name__ in ('__main__', '__ue_remote__'):
    apply_wind_revision(profile='first_pass')
