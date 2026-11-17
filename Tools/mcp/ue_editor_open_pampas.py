"""Reopen L_Pampas in the editor (init_unreal.py then auto-loads Pampas_EditorLoadAll)."""
import unreal

w = unreal.EditorLoadingAndSavingUtils.load_map('/Game/GoT/Maps/L_Pampas')
print('opened', w.get_path_name() if w else None)
