#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "GoTWindTypes.h"
#include "GoTWindRender.h"
#include "GoTWindSubsystem.generated.h"

class AGoTWindController;
class UGoTWindInteractorComponent;
class UMaterialParameterCollection;
class UTextureRenderTarget2D;

/**
 * Owns the single wind state of a world (official model, see FGoTWindParams) and the player-centred
 * interaction field.
 *
 * Every frame (editor viewport included):
 *  - integrates the gust noise (offset scrolls downwind at the wind speed, z evolves) and the flutter clock;
 *  - writes MPC_Wind for material consumers (MF_GoTWind: pampas, trees, debug heatmap):
 *      WindDir    = (dir.x, dir.y, base force, local wind scale)
 *      GustNoise  = (offset.x, offset.y, z, scale)
 *      GustShape  = (base, gain, mul, add)
 *      WindDetailNoise = (offset.x, offset.y, z, scale)，草和芒草共享的位置细节层
 *      WindResponse = (草颤动、芒草颤动、树颤动、细节风强度)，均为无单位比例
 *      WindTime   = (clock, 0, 0, 0)
 *      Interact   = (field centre x, y, 1 / field size, enabled)
 *      Pampas/Tree = (height cm, wind coefficient, bend rad at w = 1, flutter frequency)
 *      ConsumerPush = (pampas push rad, tree push rad, 0, 0)
 *      上述参数同步发布同名 Prev；全局首次 prev=current，局部前帧 enabled=0。
 *  - hands the same numbers to the render thread (GoTWindRender) for the GPU grass;
 *  - in game worlds, runs the interaction field compute pass (trail particles x damped wave, vorticles).
 */
UCLASS()
class GOTENVIRONMENT_API UGoTWindSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickableInEditor() const override { return true; }
	virtual bool IsTickableWhenPaused() const override { return true; }

	void RegisterInteractor(UGoTWindInteractorComponent* Component);
	void UnregisterInteractor(UGoTWindInteractorComponent* Component);

	/** Parameters in effect (level controller if present, else project defaults). */
	const FGoTWindParams& GetParams() const;
	const FGoTWindFrame& GetFrame() const { return Frame; }

	/** 当前平面局部风源（cm/s），使用位置/速度 XY，随寿命淡入淡出；尚无三维球面方向模型。 */
	UFUNCTION(BlueprintCallable, Category = "GoT|Wind", meta = (WorldContext = "WorldContextObject"))
	static void AddVorticle(const UObject* WorldContextObject, FVector Location, float RadiusCm, FVector WindCmPerSec, float LifetimeSeconds = 1.f);

	/** 兼容宏观查询：只返回主层速度（cm/s），不包含细节/局部风；OutGust 为主层阵风量 0..1。 */
	UFUNCTION(BlueprintPure, Category = "GoT|Wind", meta = (WorldContext = "WorldContextObject"))
	static FVector GetWindAtLocation(const UObject* WorldContextObject, FVector Location, float& OutGust);

	/** 当前完整 XY 净风（cm/s）。DetailWeight=0 为树的主场，1 为草的两层场；含共享局部风权重与 RT 采样。 */
	UFUNCTION(BlueprintPure, Category = "GoT|Wind", meta = (WorldContext = "WorldContextObject"))
	static FVector GetCombinedWindAtLocation(const UObject* WorldContextObject, FVector Location, float DetailWeight = 1.f);

private:
	struct FTrailPoint
	{
		FVector2f Position;
		float BirthTime;
		float Radius;
		float Strength;
	};

	struct FVorticle
	{
		FVector2f Position;
		FVector2f Wind;
		float Radius;
		float BirthTime;
		float Lifetime;
	};

	struct FInteractorState
	{
		TWeakObjectPtr<AActor> Actor;
		TWeakObjectPtr<UGoTWindInteractorComponent> Component;
		FVector2f LastStamp = FVector2f::ZeroVector;
		FVector2f LastPosition = FVector2f::ZeroVector;
		bool bHasStamp = false;
	};

	void FindController();
	void UpdateWindState(float DeltaTime);
	void WriteCollection();
	void UpdateInteraction();
	void GatherInteractors();
	float GustAt(const FVector2f& P) const;
	float ForceAt(const FVector2f& P) const;
	FVector2f CombinedAt(const FVector2f& P, float DetailWeight) const;
	void DrawDebug(AGoTWindController* Controller);
	FVector DebugFocus(const AGoTWindController* C) const;
	float GroundZ(const FVector2f& P, float FallbackZ);
	void DrawArrows(const AGoTWindController* C, const FVector& Focus);
	void DrawGustEdges(const AGoTWindController* C, const FVector& Focus);
	void DrawInteraction() const;
	void WriteDebugParams(const AGoTWindController* C);

	UPROPERTY(Transient)
	TObjectPtr<UMaterialParameterCollection> Collection = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<UTextureRenderTarget2D> Target = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<UTextureRenderTarget2D> PreviousTarget = nullptr;

	TWeakObjectPtr<AGoTWindController> Controller;
	double NextControllerSearch = 0.0;

	double RealTime = 0.0;
	double WindTime = 0.0;
	FGoTWindFrame Frame;
	FVector2f WindDirection = FVector2f(1.f, 0.f);
	float CurrentYaw = 0.f;
	float StripePhase = 0.f;
	FVector2f InteractCenter = FVector2f::ZeroVector;
	bool bInteractActive = false;
	bool bHasWindState = false;
	bool bClearFieldHistory = true;
	GoTWindField::FSnapshot FieldSnapshot;

	/** Ground heights for debug drawing, cached per snapped grid (traces are only redone when the grid moves). */
	TMap<FIntPoint, float> GroundCache;
	float GroundCacheSpacing = 0.f;

	TArray<FInteractorState> Interactors;
	TArray<TWeakObjectPtr<UGoTWindInteractorComponent>> RegisteredComponents;
	TArray<FTrailPoint> Trail;
	TArray<FVorticle> Vorticles;
};
