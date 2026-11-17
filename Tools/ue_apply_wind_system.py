"""全局风定向更新；prepare_assets 只准备交互历史纹理，apply 在新插件加载后运行。

导入模块不会更改资产。两阶段均不重建草材质、草种图、芒草几何或 PCG。
"""
import hashlib
import importlib.util
import struct
from pathlib import Path
import unreal


def load_setup():
    path = Path(__file__).with_name('ue_grass_setup.py')
    spec = importlib.util.spec_from_file_location('got_wind_system_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def editor_world():
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = editor.get_editor_world()
    assert world and world.get_path_name() == '/Game/GoT/Maps/L_Pampas.L_Pampas', str(world)
    assert editor.get_game_world() is None, 'Stop PIE before updating wind assets'
    return world


def prepare_assets():
    """可在旧插件下运行：只创建/确认历史 RT，不读取新 C++ 属性或改变风参数。"""
    editor_world()
    setup = load_setup()
    rt = setup.previous_field_target()
    print('Interaction history RT ready:', rt.get_path_name(), '256 x 256 RGBA16F; wind parameters unchanged')
    return rt


def function_outputs(setup, function):
    return {str(n.get_editor_property('output_name')): n
            for n in setup.LIB.get_material_function_expressions(function)
            if isinstance(n, unreal.MaterialExpressionFunctionOutput)}


def material_roots(setup, material):
    return {p: setup.LIB.get_material_property_input_node(material, p)
            for p in (unreal.MaterialProperty.MP_FRONT_MATERIAL, unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET,
                      unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)}


def preserved_parameters(params):
    values = {name: params.get_editor_property(name)
              for name in ('wind_speed_cm_per_sec', 'wind_yaw_degrees', 'time_scale', 'gust_noise_scale',
                           'gust_evolve_per_sec', 'gust_gain', 'gust_noise_mul', 'gust_noise_add',
                           'detail_noise_scale', 'detail_strength', 'grass_flutter_strength')}
    for consumer in ('pampas', 'trees'):
        item = params.get_editor_property(consumer)
        values[consumer] = tuple(item.get_editor_property(name)
                                 for name in ('height_cm', 'wind_coefficient', 'bend_degrees', 'flutter_frequency',
                                              'push_degrees', 'flutter_strength'))
    return values


def grass_component_state(component):
    # 捕获表含 NaN 位模式，不能用 float 元组相等判断是否被修改。
    table = list(component.get_editor_property('kind_table'))
    table_digest = hashlib.sha256(struct.pack(f'<{len(table)}f', *table)).hexdigest()
    return (table_digest,
            tuple((item.get_editor_property('kind_index'), item.get_editor_property('enabled'),
                   item.get_editor_property('height_width_variation'), item.get_editor_property('wind_coefficient'))
                  for item in component.get_editor_property('kind_overrides')),
            tuple(component.get_editor_property(name) for name in ('clump_normal_start_cm', 'clump_normal_end_cm',
                                                                  'clump_normal_strength', 'height_map', 'kind_map',
                                                                  'grass_height_map', 'material')))


def apply():
    """新插件重启后更新消费者与调试，只把两层传播速度设为 800/1500 cm/s。"""
    editor_world()
    setup = load_setup()
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    controllers = [a for a in actors if a.get_actor_label() == 'Pampas_WindController']
    grass_actors = [a for a in actors if a.get_actor_label() == 'Pampas_GPUGrass']
    assert len(controllers) == len(grass_actors) == 1, 'Expected one wind controller and one GPU grass actor'
    controller, grass_actor = controllers[0], grass_actors[0]
    params = controller.get_editor_property('params')
    # 在改资产前确认新插件已加载；旧版本应在此明确失败，而不是部分执行。
    params.get_editor_property('gust_travel_speed_cm_per_sec')
    params.get_editor_property('detail_travel_speed_cm_per_sec')
    parameters_before = preserved_parameters(params)
    grass = grass_actor.get_editor_property('grass')
    grass_before = grass_component_state(grass)
    grass_material = unreal.load_asset('/Game/GoT/Grass/Materials/M_GoTGrass')
    grass_nodes_before = tuple(setup.LIB.get_material_expressions(grass_material))
    wf = unreal.load_asset(f'{setup.WIND}/MF_GoTWind')
    debug = unreal.load_asset(f'{setup.WIND}/MF_GoTWindDebug')
    normal = unreal.load_asset(f'{setup.WIND}/MF_GoTWindNormal')
    rt = unreal.load_asset(f'{setup.WIND}/RT_GoTInteraction')
    previous_rt = unreal.load_asset(f'{setup.WIND}/RT_GoTInteractionPrev')
    assert wf and debug and normal and rt and previous_rt, 'Run prepare_assets before loading the new plugin'
    outputs_before = {function: function_outputs(setup, function) for function in (wf, debug, normal)}
    normal_nodes_before = tuple(setup.LIB.get_material_function_expressions(normal))
    materials = [unreal.load_asset(f'/Game/GoT/Pampas/Materials/{name}') for name in setup.ACTIVE_WIND_USERS]
    assert all(materials)
    roots_before = {material: material_roots(setup, material) for material in materials}
    mpc = setup.collection(preserve_existing=True)
    setup.wind_function(mpc, rt, previous_rt)
    setup.debug_function(mpc, rt)
    for function, outputs in outputs_before.items():
        after = function_outputs(setup, function)
        assert all(after.get(name) == node for name, node in outputs.items()), ('Function output replaced', function.get_name())
    assert tuple(setup.LIB.get_material_function_expressions(normal)) == normal_nodes_before, 'Wind normal function changed'
    for material in materials:
        wind_calls = setup.calls_of(material, wf)
        assert len(wind_calls) == 1
        radius = setup.graph_inputs(material, wind_calls[0])['StemRadiusCm']
        assert isinstance(radius, unreal.MaterialExpressionConstant), 'Preserve the existing stem-radius input'
        setup.wire_wind_material(material, wf, normal, mpc, float(radius.get_editor_property('r')))
        assert material_roots(setup, material) == roots_before[material], ('Material root replaced', material.get_name())
        errors = [str(e) for e in (setup.LIB.recompile_material(material) or [])]
        assert not errors, (material.get_name(), errors)
    params.set_editor_property('gust_travel_speed_cm_per_sec', 800.0)
    params.set_editor_property('detail_travel_speed_cm_per_sec', 1500.0)
    controller.set_editor_property('params', params)
    assert preserved_parameters(controller.get_editor_property('params')) == parameters_before, 'Other wind parameters changed'
    assert grass_component_state(grass) == grass_before, 'GPU grass overrides, maps or captured table changed'
    assert tuple(setup.LIB.get_material_expressions(grass_material)) == grass_nodes_before, 'GPU grass material graph changed'
    packages = {asset.get_package() for asset in [mpc, wf, debug, previous_rt, *materials, controller]}
    assert unreal.EditorLoadingAndSavingUtils.save_packages(list(packages), True), 'Failed to save wind-system packages'
    print('\n'.join(setup.log))
    print('Wind system applied: travel speeds=800/1500 cm/s; previous-frame data connected; normal/grass state preserved')


if __name__ in ('__main__', '__ue_remote__'):
    apply()
