#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "GoTWindTypes.h"
#include "GoTWindController.generated.h"

class UArrowComponent;
class UBillboardComponent;
class UTextRenderComponent;

/** What the heatmap shows (MPC_Wind.WindDebug.x: 1 = gust noise, 2 = blade response). */
UENUM(BlueprintType)
enum class EGoTHeatmapStyle : uint8
{
	/** Gust amount of the shared Perlin noise: emissive blue -> green -> red overlay, contours, downwind stripes. */
	GustNoise = 0,
	/**
	 * Like the third-party UE5 recreation (bilibili BV1ff421R7CW): jet colour replaces the albedo and stays lit.
	 * Grass blades are coloured per vertex by height above the root / blade length, so upright blades in a lull run
	 * green -> red towards the tip and blades flattened by a gust turn blue / cyan. Other surfaces show the tip height
	 * of a reference blade (wind coefficient 1) under the local gust force. [推断 from the video frames]
	 */
	BladeResponse = 1,
	/** 细节 Perlin 的有符号强度，仅诊断显示，不生成新风。 */
	DetailNoise = 2,
	/** 主层、可选细节与局部风向量相加后的净风速/方向。 */
	CombinedWind = 3,
};

/**
 * Place one in the level and edit Params in the Details panel: the wind (grass, pampas, trees,
 * interaction) updates live in the editor viewport and in PIE.
 *
 * Debug views (category "GoT Wind Debug", all live in editor and PIE):
 *  - Heatmap, style GustNoise: terrain and vegetation tinted by gust strength (blue calm -> green -> yellow -> red full gust),
 *    white lines where gusts begin (calm edge) and reach full strength, dark stripes that travel downwind
 *    at the gust speed (direction + front speed), magenta where the player pushes the grass.
 *    Like the wind-strength debug view in the GDC 2021 grass talk (rolling noise strength per tile).
 *  - Heatmap, style BladeResponse: lit jet colour by blade height (see EGoTHeatmapStyle).
 *  - Arrows: grid around the view, length = tip bend of a stiffness-1 consumer, colour = gust.
 *  - Gust edges: contour lines of the calm edge (cyan) and full-gust edge (red) at the same positions as the heatmap lines.
 *  - Interaction (PIE): field bounds, player radius, trail points (green = pushing, red = swinging back,
 *    like the official displacement debug view).
 *  - Info text above the controller: current direction, amplitude, gust scale/speed and gust at the view.
 */
UCLASS(hidecategories = (Rendering, Replication, Collision, Input, LOD, Cooking, Physics, Networking, HLOD, DataLayers, WorldPartition))
class GOTENVIRONMENT_API AGoTWindController : public AActor
{
	GENERATED_BODY()

public:
	AGoTWindController();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category = "GoT Wind", meta = (ShowOnlyInnerProperties))
	FGoTWindParams Params;

	/** Tint terrain and vegetation by gust strength (material overlay, no cost when off). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	bool bShowHeatmap = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (EditCondition = "bShowHeatmap"))
	EGoTHeatmapStyle HeatmapStyle = EGoTHeatmapStyle::BladeResponse;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (ClampMin = "0", ClampMax = "1", EditCondition = "bShowHeatmap"))
	float HeatmapOpacity = 0.8f;

	/** Spacing of the downwind-travelling stripes in the heatmap (0 = no stripes). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (ClampMin = "0", UIMax = "3000", EditCondition = "bShowHeatmap"))
	float HeatmapStripeSpacingCm = 600.f;

	/** Arrow grid around the view (length = bend, colour = gust). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	bool bShowArrows = false;

	/** Contour lines: cyan = gust starts (calm edge), red = gust at full strength. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	bool bShowGustEdges = false;

	/** Interaction field bounds, player radius and trail points (PIE). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	bool bShowInteraction = false;

	/** Wind summary above the controller. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	bool bShowInfoText = true;

	/** Arrows per side of the debug grid (gust edges use twice the resolution). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (ClampMin = "3", ClampMax = "61"))
	int32 DebugGridCount = 25;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (ClampMin = "50", UIMax = "2000"))
	float DebugSpacingCm = 400.f;

	/** 图示长度（cm）= 实际风速（cm/s）* 0.01 * 此倍率；箭头显示所选层真实方向。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug", meta = (ClampMin = "0.1", UIMax = "20"))
	float DebugArrowScale = 4.f;

	/** Height of arrows and contour lines above the ground. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT Wind Debug")
	float DebugHeightCm = 150.f;

	/** Copy Params into Project Settings > Plugins > GoT Wind (DefaultGame.ini). */
	UFUNCTION(CallInEditor, Category = "GoT Wind")
	void SaveAsProjectDefaults();

	/** Reset Params to the project defaults. */
	UFUNCTION(CallInEditor, Category = "GoT Wind")
	void LoadProjectDefaults();

	/** Called by UGoTWindSubsystem every frame. */
	void ShowDirection(float YawDegrees);
	void ShowInfo(const FString& Text, const FVector& ViewLocation);

private:
	UPROPERTY(VisibleAnywhere, Category = "GoT Wind")
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere, Category = "GoT Wind")
	TObjectPtr<UArrowComponent> Arrow;

	UPROPERTY(VisibleAnywhere, Category = "GoT Wind")
	TObjectPtr<UTextRenderComponent> InfoText;

#if WITH_EDITORONLY_DATA
	UPROPERTY()
	TObjectPtr<UBillboardComponent> Sprite;
#endif
};
