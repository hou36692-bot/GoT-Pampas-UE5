using UnrealBuildTool;

public class GoTEnvironment : ModuleRules
{
	public GoTEnvironment(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine", "DeveloperSettings", "RenderCore", "RHI"
		});
		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"Renderer", "Projects", "ImageCore"
		});
	}
}
