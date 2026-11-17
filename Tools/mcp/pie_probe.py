import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
print('game world', w.get_name() if w else None)
if w:
    for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.GoTGrassActor):
        c = a.get_editor_property('grass')
        print('PIE grass near', c.get_near_blade_count(), 'far', c.get_far_blade_count())
    pawn = unreal.GameplayStatics.get_player_pawn(w, 0)
    print('pawn', pawn.get_actor_location() if pawn else None)
    g = unreal.GoTWindSubsystem.get_wind_at_location(w, pawn.get_actor_location() if pawn else unreal.Vector())
    print('wind at pawn', g)
