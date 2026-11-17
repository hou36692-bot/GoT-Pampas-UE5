"""定向：把 M_GoTGrass 的 PBR 常量暴露成参数，并让 Pampas_GPUGrass 改用 M_GoTGrass_Inst。

  python -I Tools/mcp/ue_py.py Tools/ue_expose_grass_pbr.py
参数默认值等于原常量，画面不变；只改 M_GoTGrass、M_GoTGrass_Inst 的父材质刷新和草 Actor 的材质槽。
"""
import importlib.util
from pathlib import Path
import unreal

INST = '/Game/GoT/Grass/Materials/M_GoTGrass_Inst'


def load_setup():
    path = Path(__file__).with_name('ue_grass_setup.py')
    spec = importlib.util.spec_from_file_location('got_grass_pbr_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    editor = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    assert editor.get_game_world() is None, 'Stop PIE before updating grass assets'
    setup = load_setup()
    mat = unreal.load_asset('/Game/GoT/Grass/Materials/M_GoTGrass')
    inst = unreal.load_asset(INST)
    assert mat and inst and inst.get_editor_property('parent') == mat, 'M_GoTGrass_Inst must be a child of M_GoTGrass'
    setup.expose_grass_pbr_params(mat)
    print('\n'.join(setup.log))
    lib = unreal.MaterialEditingLibrary
    print('Inst sees', len(lib.get_scalar_parameter_names(inst)), 'scalar /',
          len(lib.get_vector_parameter_names(inst)), 'vector params')

    world = editor.get_editor_world()
    if world and world.get_path_name() == '/Game/GoT/Maps/L_Pampas.L_Pampas':
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        grass = [a for a in actors if a.get_actor_label() == 'Pampas_GPUGrass']
        assert len(grass) == 1, ('Expected one Pampas_GPUGrass', len(grass))
        comp = grass[0].get_editor_property('grass')
        before = comp.get_editor_property('material')
        if before != inst:
            comp.set_editor_property('material', inst)
            comp.mark_render_state_dirty() if hasattr(comp, 'mark_render_state_dirty') else None
            ok = unreal.EditorLoadingAndSavingUtils.save_packages([grass[0].get_outermost()], True)
            print(f'Pampas_GPUGrass material: {before.get_name() if before else None} -> {inst.get_name()}, saved={ok}')
        else:
            print('Pampas_GPUGrass already uses M_GoTGrass_Inst')
    else:
        print('L_Pampas not open: grass actor material slot not changed')


if __name__ in ('__main__', '__ue_remote__'):
    main()
