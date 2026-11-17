#pragma once

#include "CoreMinimal.h"
#include "Components/PrimitiveComponent.h"
#include "GameFramework/Actor.h"
#include <atomic>
#include "GoTGrassComponent.generated.h"

class UMaterialInterface;
class UTexture2D;

/** 本地草种校准覆盖；原始截帧表保持只读，整批通过验证后才应用。 */
USTRUCT(BlueprintType)
struct GOTENVIRONMENT_API FGoTGrassKindOverride
{
	GENERATED_BODY()

	/** 草种索引，0 表示无草，不允许覆盖。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass", meta = (ClampMin = "1", DisplayName = "草种索引"))
	int32 KindIndex = 2;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass", meta = (DisplayName = "启用覆盖"))
	bool bEnabled = false;

	/** 无单位，覆盖草种 [228]。0 关闭簇高与簇宽变化；不改变密度或逐叶随机参数。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass", meta = (ClampMin = "0", UIMin = "0", UIMax = "2", EditCondition = "bEnabled", DisplayName = "簇高宽变化"))
	float HeightWidthVariation = 0.8f;

	/** 无单位，覆盖草种 [200]。逐叶风值 = 系数 * 两层风力 / 6600，0 关闭风力响应。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass", meta = (ClampMin = "0", UIMin = "0", UIMax = "2", EditCondition = "bEnabled", DisplayName = "风响应系数"))
	float WindCoefficient = 0.45f;
};

namespace GoTGrassKinds
{
	/** 输出先复制基础表；任一索引、重复条目或启用数值非法时整批回退，返回错误说明。 */
	GOTENVIRONMENT_API bool ApplyOverrides(const TArray<float>& BaseTable, const TArray<FGoTGrassKindOverride>& Overrides,
		TArray<float>& OutTable, FString& OutError);
}

/** Blade counts read back from the GPU (debug only). */
struct FGoTGrassStats
{
	std::atomic<uint32> Near{0};
	std::atomic<uint32> Far{0};
	std::atomic<uint32> Tiles{0};
	std::atomic<uint32> Views{0};
};

/** One GPU grass tile: 256 x 256 lanes, every Multiplier-th global cell starting at CellOffset. */
struct FGoTGrassTile
{
	FIntPoint CellOffset;
	int32 Level = 0;
};

namespace GoTGrassTiles
{
	/**
	 * Quadtree tile choice for one view (official: tiles follow the terrain LOD, a tile twice as far keeps the
	 * same lane count with every second cell). Level L is used where the nearest point of the tile is past
	 * 2^(L-1) / LodScale, so every cell the shader keeps at that distance exists in the tile.
	 */
	GOTENVIRONMENT_API void Select(const FVector& Origin, const struct FConvexVolume* Frustum, const FBox& Area, float BaseCellCm,
		float LodScale, float MaxDistanceCm, int32 MaxLevel, int32 MaxTiles, TArray<FGoTGrassTile>& Out);
}

/**
 * GPU grass (official model, Docs/Handoffs/PLAN_20261107): every frame and view a compute shader generates
 * quadratic Bezier blades over terrain tiles (kind map, grass height map, Voronoi clusters, per-blade wind from
 * the shared 3D Perlin gusts), a finalize pass writes indirect draw arguments and the blades are drawn through
 * FGoTGrassVertexFactory with M_GoTGrass. Wind comes from UGoTWindSubsystem (one wind for all consumers).
 */
UCLASS(ClassGroup = (GoT), meta = (BlueprintSpawnableComponent), hidecategories = (Collision, Physics, Navigation, HLOD, Mobile, VirtualTexture, Lighting))
class GOTENVIRONMENT_API UGoTGrassComponent : public UPrimitiveComponent
{
	GENERATED_BODY()

public:
	UGoTGrassComponent();

	/** Must have "Used with Virtual Heightfield Mesh" checked (the usage flag the grass vertex factory compiles for). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Grass")
	TObjectPtr<UMaterialInterface> Material;

	// ---------------- Terrain data ----------------
	/** 16-bit terrain heightmap (same source as the Landscape import, G16, no mips). */
	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	TObjectPtr<UTexture2D> HeightMap;

	/** World XY of the first texel's outer corner, and the side length covered by the maps (cm). */
	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	FVector2D MapOrigin = FVector2D(-50450.0, -50450.0);

	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	double MapSizeCm = 100900.0;

	/** z = heightmap value (0..1) * HeightScale + HeightBias (+ component z). */
	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	float HeightScale = 25599.609375f;

	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	float HeightBias = -12800.f;

	/** Grass kind per texel (G8, value = kind index, 0 = none). [截帧: 513^2 R8_UINT kind map] */
	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	TObjectPtr<UTexture2D> KindMap;

	/** Grass height 0..1 (G8). [截帧: BC4 grass height map] */
	UPROPERTY(EditAnywhere, Category = "Grass|Terrain")
	TObjectPtr<UTexture2D> GrassHeightMap;

	/** Kind table: 59 floats (236-byte records) per kind, the captured table (resource 3558, 49 kinds). */
	UPROPERTY(EditAnywhere, Category = "Grass|Kinds")
	TArray<float> KindTable;

	/** 只覆盖具名字段，不写入基础 KindTable；默认空列表保留全部截帧值。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass|Kinds", meta = (DisplayName = "草种校准覆盖"))
	TArray<FGoTGrassKindOverride> KindOverrides;

	/** 与 GPU 上传使用同一生产函数，返回有效表；非法覆盖会报错并返回完整基础表。 */
	UFUNCTION(BlueprintPure, Category = "GoT|Grass")
	TArray<float> GetEffectiveKindTable() const;

	// ---------------- Generation [截帧 values] ----------------
	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "1"))
	float BaseCellCm = 9.765625f;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation")
	float JitterScale = 1.35f;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "0.00001"))
	float LodScale = 0.0004f;

	/** Distance fade = saturate(d * Mul + Add - 0.5 rand): grass ends at 200-210 m. */
	UPROPERTY(EditAnywhere, Category = "Grass|Generation")
	float DistFadeMul = -0.0005f;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation")
	float DistFadeAdd = 10.5f;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation")
	float BaseWidthScale = 1.f;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "0", ClampMax = "6"))
	int32 MaxTileLevel = 4;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "1", ClampMax = "1024"))
	int32 MaxTiles = 256;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "1024"))
	int32 NearCapacity = 262144;

	UPROPERTY(EditAnywhere, Category = "Grass|Generation", meta = (ClampMin = "1024"))
	int32 FarCapacity = 524288;

	/** Frustum test margin: blades lean up to their length out of the generated point. */
	UPROPERTY(EditAnywhere, Category = "Grass|Generation")
	float FrustumMarginCm = 200.f;

	// ---------------- Vertex shader [截帧 values] ----------------
	/** Near blades morph to the 7-vertex distribution: saturate((d + rand * Dither) * Mul + Add) -> 1 at ~13 m. */
	UPROPERTY(EditAnywhere, Category = "Grass|Vertex")
	FVector LodMorph = FVector(0.003748, -4.0, 250.0);

	/** Grazing-angle widening: saturate((d + rand * Dither) * Mul + Add). */
	UPROPERTY(EditAnywhere, Category = "Grass|Vertex")
	FVector Grazing = FVector(0.000468, -0.25, -1250.0);

	/** [适配] 共同簇法线开始混合的相机距离（cm），只影响照明。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass|Clump Normal", meta = (ClampMin = "0", DisplayName = "簇法线起始距离 (cm)"))
	float ClumpNormalStartCm = 1500.f;

	/** [适配] 共同簇法线达到最大权重的距离（cm），应大于起始距离。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass|Clump Normal", meta = (ClampMin = "1", DisplayName = "簇法线结束距离 (cm)"))
	float ClumpNormalEndCm = 6000.f;

	/** [适配] 最大混合权重，无单位。0 关闭照明混合；草叶曲线、密度和运动矢量不受影响。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Grass|Clump Normal", meta = (ClampMin = "0", ClampMax = "1", DisplayName = "簇法线强度"))
	float ClumpNormalStrength = 0.6f;

	// ---------------- Debug ----------------
	/** Draw the generation tiles of the first view (colour = level). */
	UPROPERTY(EditAnywhere, Category = "Grass|Debug")
	bool bShowTiles = false;

	/** On-screen blade counts (GPU readback). GPU time: "stat GPU" -> GoTGrass. */
	UPROPERTY(EditAnywhere, Category = "Grass|Debug")
	bool bShowStats = false;

	UFUNCTION(BlueprintPure, Category = "GoT|Grass")
	int32 GetNearBladeCount() const { return int32(Stats->Near.load()); }

	UFUNCTION(BlueprintPure, Category = "GoT|Grass")
	int32 GetFarBladeCount() const { return int32(Stats->Far.load()); }

	//~ UPrimitiveComponent
	virtual FPrimitiveSceneProxy* CreateSceneProxy() override;
	virtual FBoxSphereBounds CalcBounds(const FTransform& LocalToWorld) const override;
	virtual void GetUsedMaterials(TArray<UMaterialInterface*>& OutMaterials, bool bGetDebugMaterials = false) const override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
#if WITH_EDITOR
	virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif

	TSharedRef<FGoTGrassStats, ESPMode::ThreadSafe> Stats;
};

/** Level actor holding the GPU grass (one per level, always loaded: it generates around every camera). */
UCLASS(hidecategories = (Rendering, Replication, Collision, Input, LOD, Cooking, Physics, Networking, HLOD, DataLayers))
class GOTENVIRONMENT_API AGoTGrassActor : public AActor
{
	GENERATED_BODY()

public:
	AGoTGrassActor();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Grass")
	TObjectPtr<UGoTGrassComponent> Grass;
};
