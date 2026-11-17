#include "Interfaces/IPluginManager.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "ShaderCore.h"

/** Maps /Plugin/GoTEnvironment to <plugin>/Shaders (global shaders + the grass vertex factory need PostConfigInit). */
class FGoTEnvironmentModule : public IModuleInterface
{
public:
	virtual void StartupModule() override
	{
		const FString ShaderDir = FPaths::Combine(IPluginManager::Get().FindPlugin(TEXT("GoTEnvironment"))->GetBaseDir(), TEXT("Shaders"));
		AddShaderSourceDirectoryMapping(TEXT("/Plugin/GoTEnvironment"), ShaderDir);
	}
};

IMPLEMENT_MODULE(FGoTEnvironmentModule, GoTEnvironment)
