#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "GoTWindTypes.h"
#include "GoTWindSettings.generated.h"

class UMaterialParameterCollection;
class UTextureRenderTarget2D;

/**
 * Project Settings > Plugins > GoT Wind.
 *
 * Asset bindings plus the project-default wind parameters. Day-to-day tuning happens on the
 * AGoTWindController placed in the level (its Details panel updates the wind live); this
 * section is the fallback for levels without a controller ("Save As Project Defaults" on the
 * controller writes here).
 */
UCLASS(config = Game, defaultconfig, meta = (DisplayName = "GoT Wind"))
class GOTENVIRONMENT_API UGoTWindSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	virtual FName GetCategoryName() const override { return TEXT("Plugins"); }

	/** 每帧更新主风、WindDetailNoise、WindResponse、交互和各类植被响应的共享 MPC。 */
	UPROPERTY(config, EditAnywhere, Category = "Assets")
	TSoftObjectPtr<UMaterialParameterCollection> WindCollection;

	/** RGBA16F with UAV: RG = interaction displacement (trail particles), BA = vorticle wind (cm/s). Written by a compute pass. */
	UPROPERTY(config, EditAnywhere, Category = "Assets")
	TSoftObjectPtr<UTextureRenderTarget2D> InteractionTarget;

	/** 前帧局部场，须与当前场同尺寸及 RGBA16F 格式；每帧先复制再写入当前场。 */
	UPROPERTY(config, EditAnywhere, Category = "Assets")
	TSoftObjectPtr<UTextureRenderTarget2D> PreviousInteractionTarget;

	/** [截帧] Side length of the square interaction field centred on the player (captured: 100 m, 256 texels). */
	UPROPERTY(config, EditAnywhere, Category = "Interaction Field", meta = (ClampMin = "500"))
	float InteractionWorldSizeCm = 10000.f;

	UPROPERTY(config, EditAnywhere, Category = "Interaction Field")
	bool bAutoRegisterPlayerPawn = true;

	/** Used when the level has no AGoTWindController. */
	UPROPERTY(config, EditAnywhere, Category = "Default Wind", meta = (ShowOnlyInnerProperties))
	FGoTWindParams Params;
};
