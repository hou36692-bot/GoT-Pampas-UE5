#pragma once

#include "CoreMinimal.h"
#include "GoTWindTypes.h"

class FSceneInterface;
class UTextureRenderTarget2D;

/** CPU mirror of the shader-side wind (GoTWindCommon.ush): same tables, same formula. */
namespace GoTWindNoise
{
	GOTENVIRONMENT_API float Perlin3D(const FVector3f& P);
	/** Wind force at a world location (cm/s units). Noise = (offset xy, z, scale), Shape = (base, gain, mul, add). */
	GOTENVIRONMENT_API float GustForce(const FVector2f& WorldXY, const FVector4f& Noise, const FVector4f& Shape);
	/** 草和芒草的两层风力 CPU 镜像（cm/s）；DetailStrength = 0 恢复主风，树和通用查询仍读 GustForce。 */
	GOTENVIRONMENT_API float GrassGustForce(const FVector2f& WorldXY, const FVector4f& MacroNoise, const FVector4f& MacroShape,
		const FVector4f& DetailNoise, float DetailStrength);
	/** 0 calm .. 1 full gust. */
	GOTENVIRONMENT_API float GustAmount(const FVector2f& WorldXY, const FVector4f& Noise, const FVector4f& Shape);
	/** 与 HLSL 同义的净风合成和分离 idle/风增弯。 */
	GOTENVIRONMENT_API FVector2f ComposeWind(const FVector2f& MainDir, float Force, const FVector2f& LocalVelocity,
		float LocalScale, float& Speed, float& DeflectionAngle);
	GOTENVIRONMENT_API FVector3f BuildWindBend(const FVector2f& Facing, float Idle, float WindValue, float DeflectionAngle);
}

/** Wind state per scene, readable on the render thread (grass generation / vertex factory). */
namespace GoTWindRender
{
	GOTENVIRONMENT_API void SetFrame_GameThread(const FSceneInterface* Scene, const FGoTWindFrame& Frame);
	GOTENVIRONMENT_API void RemoveScene_GameThread(const FSceneInterface* Scene);
	/** Thread safe (called from mesh gathering tasks). Returns false when no wind subsystem drives this scene. */
	GOTENVIRONMENT_API bool GetFrame(const FSceneInterface* Scene, FGoTWindFrame& OutFrame);
}

/** GPU interaction / vorticle field (GoTWindField.usf) written into the interaction render target. */
namespace GoTWindField
{
	struct FParticle
	{
		FVector2f Position;
		float Age;
		float Radius;
		float Strength;
	};

	struct FVorticle
	{
		FVector2f Position;
		float Radius;
		float Fade;
		FVector2f Wind;
	};

	struct FSnapshot
	{
		FVector2f Center = FVector2f::ZeroVector;
		float Size = 10000.f;
		int32 Resolution = 256;
		bool bEnabled = false;
		float WaveDecay = 1.5f;
		float WaveFrequency = 6.f;
		TArray<FParticle> Particles;
		TArray<FVorticle> Vorticles;
	};

	/** CPU 按四个 texel 中心的同源局部风，钳制/Half量化、双线性和边缘衰减匹配 GPU RT。 */
	GOTENVIRONMENT_API FVector2f SampleLocalWind(const FVector2f& WorldXY, const FSnapshot& Snapshot);
	/** Target/PreviousTarget 同尺寸 RGBA16F；首次清零两场，再先复制当前到前帧，最后生成当前。 */
	GOTENVIRONMENT_API void Update_GameThread(UTextureRenderTarget2D* Target, UTextureRenderTarget2D* PreviousTarget,
		const FSnapshot& Snapshot, bool bClearHistory);
}
