"""Save everything and quit the editor (used before building C++ modules)."""
import unreal

unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
print('saved; quitting')
unreal.SystemLibrary.quit_editor()
