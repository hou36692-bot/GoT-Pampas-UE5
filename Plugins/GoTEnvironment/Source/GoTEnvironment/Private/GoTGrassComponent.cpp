#include "GoTGrassComponent.h"
#include "GoTGrassVertexFactory.h"
#include "GoTWindRender.h"

#include "ConvexVolume.h"
#include "Engine/CollisionProfile.h"
#include "MaterialShared.h"
#include "DataDrivenShaderPlatformInfo.h"
#include "DrawDebugHelpers.h"
#include "Engine/Engine.h"
#include "Engine/Texture2D.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GlobalRenderResources.h"
#include "GlobalShader.h"
#include "MaterialDomain.h"
#include "Materials/Material.h"
#include "Materials/MaterialRenderProxy.h"
#include "MeshElementCollector.h"
#include "PrimitiveSceneProxy.h"
#include "PrimitiveViewRelevance.h"
#include "RHIGPUReadback.h"
#include "RHIResourceUtils.h"
#include "RHIStaticStates.h"
#include "RenderGraphBuilder.h"
#include "RenderGraphUtils.h"
#include "SceneInterface.h"
#include "SceneView.h"
#include "ShaderParameterStruct.h"
#include "TextureResource.h"

DECLARE_GPU_STAT(GoTGrass);

namespace GoTGrassKinds
{
	bool ApplyOverrides(const TArray<float>& BaseTable, const TArray<FGoTGrassKindOverride>& Overrides,
		TArray<float>& OutTable, FString& OutError)
	{
		OutTable = BaseTable;
		OutError.Reset();
		constexpr int32 FloatsPerKind = 59;
		if (BaseTable.Num() < FloatsPerKind || BaseTable.Num() % FloatsPerKind != 0)
		{
			OutError = TEXT("基础草种表必须包含完整的 59-float 记录，整批覆盖已取消。");
			return false;
		}
		const int32 NumKinds = BaseTable.Num() / FloatsPerKind;
		TSet<int32> Seen;
		for (const FGoTGrassKindOverride& Entry : Overrides)
		{
			if (Entry.KindIndex <= 0 || Entry.KindIndex >= NumKinds || Seen.Contains(Entry.KindIndex))
			{
				OutError = FString::Printf(TEXT("草种 %d 的索引非法或重复，整批覆盖已取消。"), Entry.KindIndex);
				return false;
			}
			Seen.Add(Entry.KindIndex);
			if (Entry.bEnabled && (!FMath::IsFinite(Entry.HeightWidthVariation) || Entry.HeightWidthVariation < 0.f
				|| !FMath::IsFinite(Entry.WindCoefficient) || Entry.WindCoefficient < 0.f))
			{
				OutError = FString::Printf(TEXT("草种 %d 的簇高宽或风系数必须有限且非负，整批覆盖已取消。"), Entry.KindIndex);
				return false;
			}
		}
		// 先验证全部条目，再写副本；失败时绝不留下部分覆盖。
		for (const FGoTGrassKindOverride& Entry : Overrides)
		{
			if (Entry.bEnabled)
			{
				const int32 Base = Entry.KindIndex * FloatsPerKind;
				OutTable[Base + 228 / 4] = Entry.HeightWidthVariation;
				OutTable[Base + 200 / 4] = Entry.WindCoefficient;
			}
		}
		return true;
	}
}

// ---------------------------------------------------------------- shaders

class FGoTGrassGenerateCS : public FGlobalShader
{
public:
	DECLARE_GLOBAL_SHADER(FGoTGrassGenerateCS);
	SHADER_USE_PARAMETER_STRUCT(FGoTGrassGenerateCS, FGlobalShader);

	BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
		SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float4>, TileFloats)
		SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<int4>, TileInts)
		SHADER_PARAMETER(uint32, NumTiles)
		SHADER_PARAMETER(FVector3f, ViewOrigin)
		SHADER_PARAMETER_ARRAY(FVector4f, FrustumPlanes, [6])
		SHADER_PARAMETER(uint32, NumFrustumPlanes)
		SHADER_PARAMETER(float, FrustumMargin)
		SHADER_PARAMETER(float, BaseCellCm)
		SHADER_PARAMETER(float, JitterScale)
		SHADER_PARAMETER(float, LodScale)
		SHADER_PARAMETER(float, DistFadeMul)
		SHADER_PARAMETER(float, DistFadeAdd)
		SHADER_PARAMETER(float, BaseWidthScale)
		SHADER_PARAMETER_TEXTURE(Texture2D<float>, HeightMap)
		SHADER_PARAMETER(FVector4f, HeightMapTransform)
		SHADER_PARAMETER(FVector2f, HeightScaleBias)
		SHADER_PARAMETER_TEXTURE(Texture2D<float>, KindMap)
		SHADER_PARAMETER(FVector4f, KindMapTransform)
		SHADER_PARAMETER_TEXTURE(Texture2D<float>, GrassHeightMap)
		SHADER_PARAMETER_SAMPLER(SamplerState, LinearClampSampler)
		SHADER_PARAMETER_SRV(StructuredBuffer<float>, Kinds)
		SHADER_PARAMETER(uint32, NumKinds)
		SHADER_PARAMETER(FVector4f, WindNoise)
		SHADER_PARAMETER(FVector4f, WindNoisePrev)
		SHADER_PARAMETER(FVector4f, WindShape)
		SHADER_PARAMETER(FVector4f, WindShapePrev)
		SHADER_PARAMETER(FVector4f, WindDetailNoise)
		SHADER_PARAMETER(FVector4f, WindDetailNoisePrev)
		SHADER_PARAMETER(float, DetailStrength)
		SHADER_PARAMETER(float, DetailStrengthPrev)
		SHADER_PARAMETER(FVector2f, WindDir)
		SHADER_PARAMETER(FVector2f, WindDirPrev)
		SHADER_PARAMETER(float, GustJitterCm)
		SHADER_PARAMETER(float, GustJitterCmPrev)
		SHADER_PARAMETER_TEXTURE(Texture2D<float4>, WindField)
		SHADER_PARAMETER_TEXTURE(Texture2D<float4>, WindFieldPrev)
		SHADER_PARAMETER(FVector4f, WindFieldTransform)
		SHADER_PARAMETER(FVector4f, WindFieldTransformPrev)
		SHADER_PARAMETER(float, VorticleForceScale)
		SHADER_PARAMETER(float, VorticleForceScalePrev)
		SHADER_PARAMETER_UAV(RWStructuredBuffer<float4>, RWBladesNear)
		SHADER_PARAMETER_UAV(RWStructuredBuffer<float4>, RWBladesFar)
		SHADER_PARAMETER_UAV(RWBuffer<uint>, RWCounters)
		SHADER_PARAMETER_RDG_BUFFER_UAV(RWBuffer<uint>, RWClumpNormalsNear)
		SHADER_PARAMETER_RDG_BUFFER_UAV(RWBuffer<uint>, RWClumpNormalsFar)
		SHADER_PARAMETER_RDG_BUFFER_UAV(RWBuffer<float4>, RWWindMotionNear)
		SHADER_PARAMETER_RDG_BUFFER_UAV(RWBuffer<float4>, RWWindMotionFar)
		SHADER_PARAMETER(uint32, CapacityNear)
		SHADER_PARAMETER(uint32, CapacityFar)
	END_SHADER_PARAMETER_STRUCT()

	static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& Parameters)
	{
		return IsFeatureLevelSupported(Parameters.Platform, ERHIFeatureLevel::SM5);
	}
};

IMPLEMENT_GLOBAL_SHADER(FGoTGrassGenerateCS, "/Plugin/GoTEnvironment/Private/GoTGrassGen.usf", "GenerateCS", SF_Compute);

class FGoTGrassFinalizeCS : public FGlobalShader
{
public:
	DECLARE_GLOBAL_SHADER(FGoTGrassFinalizeCS);
	SHADER_USE_PARAMETER_STRUCT(FGoTGrassFinalizeCS, FGlobalShader);

	BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
		SHADER_PARAMETER_UAV(RWBuffer<uint>, RWCounters)
		SHADER_PARAMETER_UAV(RWBuffer<uint>, RWIndirectArgs)
		SHADER_PARAMETER(uint32, IndicesPerInstanceNear)
		SHADER_PARAMETER(uint32, IndicesPerInstanceFar)
		SHADER_PARAMETER(uint32, BladesPerInstanceNear)
		SHADER_PARAMETER(uint32, BladesPerInstanceFar)
		SHADER_PARAMETER(uint32, CapacityNear)
		SHADER_PARAMETER(uint32, CapacityFar)
	END_SHADER_PARAMETER_STRUCT()

	static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& Parameters)
	{
		return IsFeatureLevelSupported(Parameters.Platform, ERHIFeatureLevel::SM5);
	}
};

IMPLEMENT_GLOBAL_SHADER(FGoTGrassFinalizeCS, "/Plugin/GoTEnvironment/Private/GoTGrassGen.usf", "FinalizeCS", SF_Compute);

// ---------------------------------------------------------------- tiles

namespace GoTGrassTiles
{
	static void Visit(const FVector& Origin, const FConvexVolume* Frustum, const FBox& Area, double BaseCell, double LodScale, double MaxDist,
		int32 Level, int64 Tx, int64 Ty, int32 MaxTiles, TArray<FGoTGrassTile>& Out)
	{
		if (Out.Num() >= MaxTiles)
		{
			return;
		}
		const double Size = 256.0 * double(1 << Level) * BaseCell;
		const FVector2D Min(Tx * Size, Ty * Size);
		const FVector2D Max = Min + FVector2D(Size, Size);
		if (Max.X < Area.Min.X || Min.X > Area.Max.X || Max.Y < Area.Min.Y || Min.Y > Area.Max.Y)
		{
			return;
		}
		const double Dx = FMath::Max3(Min.X - Origin.X, 0.0, Origin.X - Max.X);
		const double Dy = FMath::Max3(Min.Y - Origin.Y, 0.0, Origin.Y - Max.Y);
		const double DMin = FMath::Sqrt(Dx * Dx + Dy * Dy);
		if (DMin > MaxDist)
		{
			return;
		}
		if (Frustum && Frustum->Planes.Num() > 0)
		{
			const FVector Center((Min.X + Max.X) * 0.5, (Min.Y + Max.Y) * 0.5, (Area.Min.Z + Area.Max.Z) * 0.5);
			const FVector Extent(Size * 0.5 + 300.0, Size * 0.5 + 300.0, (Area.Max.Z - Area.Min.Z) * 0.5 + 300.0);
			if (!Frustum->IntersectBox(Center, Extent))
			{
				return;
			}
		}
		// Level L holds every 2^L-th cell: valid only where the shader keeps no finer cell (d > 2^(L-1) / LodScale).
		if (Level > 0 && DMin <= double(1 << (Level - 1)) / LodScale)
		{
			for (int32 j = 0; j < 2; ++j)
			{
				for (int32 i = 0; i < 2; ++i)
				{
					Visit(Origin, Frustum, Area, BaseCell, LodScale, MaxDist, Level - 1, Tx * 2 + i, Ty * 2 + j, MaxTiles, Out);
				}
			}
			return;
		}
		FGoTGrassTile& T = Out.AddDefaulted_GetRef();
		const int64 Cells = int64(256) << Level;
		T.CellOffset = FIntPoint(int32(Tx * Cells), int32(Ty * Cells));
		T.Level = Level;
	}

	void Select(const FVector& Origin, const FConvexVolume* Frustum, const FBox& Area, float BaseCellCm, float LodScale, float MaxDistanceCm,
		int32 MaxLevel, int32 MaxTiles, TArray<FGoTGrassTile>& Out)
	{
		Out.Reset();
		const double RootSize = 256.0 * double(1 << MaxLevel) * BaseCellCm;
		const int64 X0 = FMath::FloorToInt64((Origin.X - MaxDistanceCm) / RootSize);
		const int64 X1 = FMath::FloorToInt64((Origin.X + MaxDistanceCm) / RootSize);
		const int64 Y0 = FMath::FloorToInt64((Origin.Y - MaxDistanceCm) / RootSize);
		const int64 Y1 = FMath::FloorToInt64((Origin.Y + MaxDistanceCm) / RootSize);
		for (int64 Ty = Y0; Ty <= Y1; ++Ty)
		{
			for (int64 Tx = X0; Tx <= X1; ++Tx)
			{
				Visit(Origin, Frustum, Area, BaseCellCm, FMath::Max(LodScale, 1e-6f), MaxDistanceCm, MaxLevel, Tx, Ty, MaxTiles, Out);
			}
		}
	}
}

// ---------------------------------------------------------------- per-view buffers + frame hooks

namespace GoTGrass
{
	static constexpr uint32 NearVerts = 15;
	static constexpr uint32 FarVerts = 7;
	static constexpr uint32 NearBladesPerInstance = 124;   // [截帧] vs_HighLod: instance * 124
	static constexpr uint32 FarBladesPerInstance = 136;    // [截帧] vs_LowLod: instance * 136
	static constexpr uint32 ArgsStride = 5 * sizeof(uint32);

	struct FViewBuffers
	{
		FBufferRHIRef BladesNear, BladesFar, Counters, Args;
		FUnorderedAccessViewRHIRef BladesNearUAV, BladesFarUAV, CountersUAV, ArgsUAV;
		FShaderResourceViewRHIRef BladesNearSRV, BladesFarSRV, CountersSRV;
		FBufferRHIRef ClumpNormalsNear, ClumpNormalsFar;
		FShaderResourceViewRHIRef ClumpNormalsNearSRV, ClumpNormalsFarSRV;
		TRefCountPtr<FRDGPooledBuffer> ClumpNormalsNearPooled, ClumpNormalsFarPooled;
		FBufferRHIRef WindMotionNear, WindMotionFar;
		FShaderResourceViewRHIRef WindMotionNearSRV, WindMotionFarSRV;
		TRefCountPtr<FRDGPooledBuffer> WindMotionNearPooled, WindMotionFarPooled;
		uint32 NearCapacity = 0;
		uint32 FarCapacity = 0;
	};

	static void InitBuffers(FRHICommandListBase& RHICmdList, FViewBuffers& B, uint32 Near, uint32 Far)
	{
		auto Blades = [&RHICmdList](const TCHAR* Name, uint32 Count, FBufferRHIRef& Buf, FUnorderedAccessViewRHIRef& UAV, FShaderResourceViewRHIRef& SRV)
		{
			const FRHIBufferCreateDesc Desc = FRHIBufferCreateDesc::CreateStructured<FVector4f>(Name, Count * 4)
				.AddUsage(EBufferUsageFlags::UnorderedAccess | EBufferUsageFlags::ShaderResource)
				.SetInitialState(ERHIAccess::SRVMask);
			Buf = RHICmdList.CreateBuffer(Desc);
			UAV = RHICmdList.CreateUnorderedAccessView(Buf, FRHIViewDesc::CreateBufferUAV().SetTypeFromBuffer(Buf));
			SRV = RHICmdList.CreateShaderResourceView(Buf, FRHIViewDesc::CreateBufferSRV().SetTypeFromBuffer(Buf));
		};
		Blades(TEXT("GoT.GrassBladesNear"), Near, B.BladesNear, B.BladesNearUAV, B.BladesNearSRV);
		Blades(TEXT("GoT.GrassBladesFar"), Far, B.BladesFar, B.BladesFarUAV, B.BladesFarSRV);
		auto ClumpNormals = [&RHICmdList](const TCHAR* Name, uint32 Count, FBufferRHIRef& Buffer,
			FShaderResourceViewRHIRef& SRV, TRefCountPtr<FRDGPooledBuffer>& Pooled)
		{
			const FRDGBufferDesc Desc = FRDGBufferDesc::CreateBufferDesc(sizeof(uint32), Count);
			const FRHIBufferCreateDesc CreateDesc = FRHIBufferCreateDesc::CreateVertex<uint32>(Name, Count)
				.AddUsage(Desc.Usage).SetInitialState(ERHIAccess::SRVGraphics);
			Buffer = RHICmdList.CreateBuffer(CreateDesc);
			SRV = RHICmdList.CreateShaderResourceView(Buffer, FRHIViewDesc::CreateBufferSRV()
				.SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(PF_R32_UINT));
			// 包装同一持久 RHI buffer，交给 RDG 跟踪 UAV 写入及后续图形 SRV 读取。
			Pooled = new FRDGPooledBuffer(RHICmdList, Buffer, Desc, Count, Name);
		};
		ClumpNormals(TEXT("GoT.ClumpNormalsNear"), Near, B.ClumpNormalsNear, B.ClumpNormalsNearSRV, B.ClumpNormalsNearPooled);
		ClumpNormals(TEXT("GoT.ClumpNormalsFar"), Far, B.ClumpNormalsFar, B.ClumpNormalsFarSRV, B.ClumpNormalsFarPooled);
		auto WindMotion = [&RHICmdList](const TCHAR* Name, uint32 Count, FBufferRHIRef& Buffer,
			FShaderResourceViewRHIRef& SRV, TRefCountPtr<FRDGPooledBuffer>& Pooled)
		{
			const FRDGBufferDesc Desc = FRDGBufferDesc::CreateBufferDesc(sizeof(FVector4f), Count);
			const FRHIBufferCreateDesc CreateDesc = FRHIBufferCreateDesc::CreateVertex<FVector4f>(Name, Count)
				.AddUsage(Desc.Usage).SetInitialState(ERHIAccess::SRVGraphics);
			Buffer = RHICmdList.CreateBuffer(CreateDesc);
			SRV = RHICmdList.CreateShaderResourceView(Buffer, FRHIViewDesc::CreateBufferSRV()
				.SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(PF_A32B32G32R32F));
			Pooled = new FRDGPooledBuffer(RHICmdList, Buffer, Desc, Count, Name);
		};
		WindMotion(TEXT("GoT.WindMotionNear"), Near, B.WindMotionNear, B.WindMotionNearSRV, B.WindMotionNearPooled);
		WindMotion(TEXT("GoT.WindMotionFar"), Far, B.WindMotionFar, B.WindMotionFarSRV, B.WindMotionFarPooled);
		{
			const FRHIBufferCreateDesc Desc = FRHIBufferCreateDesc::CreateVertex<uint32>(TEXT("GoT.GrassCounters"), 4)
				.AddUsage(EBufferUsageFlags::UnorderedAccess | EBufferUsageFlags::ShaderResource | EBufferUsageFlags::SourceCopy)
				.SetInitialState(ERHIAccess::SRVMask)
				.SetInitActionZeroData();
			B.Counters = RHICmdList.CreateBuffer(Desc);
			B.CountersUAV = RHICmdList.CreateUnorderedAccessView(B.Counters, FRHIViewDesc::CreateBufferUAV().SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(PF_R32_UINT));
			B.CountersSRV = RHICmdList.CreateShaderResourceView(B.Counters, FRHIViewDesc::CreateBufferSRV().SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(PF_R32_UINT));
		}
		{
			const FRHIBufferCreateDesc Desc = FRHIBufferCreateDesc::CreateVertex<uint32>(TEXT("GoT.GrassIndirectArgs"), 10)
				.AddUsage(EBufferUsageFlags::UnorderedAccess | EBufferUsageFlags::DrawIndirect)
				.SetInitialState(ERHIAccess::IndirectArgs)
				.SetInitActionZeroData();
			B.Args = RHICmdList.CreateBuffer(Desc);
			B.ArgsUAV = RHICmdList.CreateUnorderedAccessView(B.Args, FRHIViewDesc::CreateBufferUAV().SetType(FRHIViewDesc::EBufferType::Typed).SetFormat(PF_R32_UINT));
		}
		B.NearCapacity = Near;
		B.FarCapacity = Far;
	}
}

class FGoTGrassSceneProxy;

/** Collects (proxy, view) work during mesh gathering and runs the generation passes at the start of the frame's graph. */
class FGoTGrassRendererExtension : public FRenderResource
{
public:
	void RegisterExtension()
	{
		static bool bRegistered = false;
		if (!bRegistered && GEngine)
		{
			GEngine->GetPreRenderDelegateEx().AddRaw(this, &FGoTGrassRendererExtension::BeginFrame);
			GEngine->GetPostRenderDelegateEx().AddRaw(this, &FGoTGrassRendererExtension::EndFrame);
			bRegistered = true;
		}
	}

	bool IsInFrame() const { return bInFrame; }

	GoTGrass::FViewBuffers AddWork(FRHICommandListBase& RHICmdList, const FGoTGrassSceneProxy* Proxy, const FSceneView* View);

	virtual void ReleaseRHI() override
	{
		Buffers.Empty();
		LastUsed.Empty();
	}

private:
	struct FWork
	{
		const FGoTGrassSceneProxy* Proxy;
		const FSceneView* View;
		int32 BufferIndex;
		FVector Origin;
		FConvexVolume Frustum;
	};

	void BeginFrame(FRDGBuilder& GraphBuilder);
	void EndFrame(FRDGBuilder& GraphBuilder);
	void Submit(FRDGBuilder& GraphBuilder, const FWork& Work);

	FCriticalSection Mutex;
	bool bInFrame = false;
	uint32 FrameId = 1;
	TArray<FWork> Works;
	TArray<GoTGrass::FViewBuffers> Buffers;
	TArray<uint32> LastUsed;
};

static TGlobalResource<FGoTGrassRendererExtension> GGoTGrassExtension;

// ---------------------------------------------------------------- scene proxy

class FGoTGrassSceneProxy final : public FPrimitiveSceneProxy
{
public:
	FGoTGrassSceneProxy(UGoTGrassComponent* C)
		: FPrimitiveSceneProxy(C, FName(TEXT("GoTGrass")))
		, Stats(C->Stats)
	{
		GGoTGrassExtension.RegisterExtension();
		bAlwaysHasVelocity = true;
		bCastDynamicShadow = false;

		UMaterialInterface* Mat = C->Material;
		const bool bValid = Mat && Mat->CheckMaterialUsage_Concurrent(MATUSAGE_VirtualHeightfieldMesh);
		if (Mat && !bValid)
		{
			UE_LOG(LogTemp, Warning, TEXT("GoTGrass: %s needs 'Used with Virtual Heightfield Mesh' (grass vertex factory usage)"), *Mat->GetName());
		}
		Material = bValid ? Mat->GetRenderProxy() : UMaterial::GetDefaultMaterial(MD_Surface)->GetRenderProxy();
		MaterialRelevance = Material->GetMaterialInterface()->GetRelevance_Concurrent(GetScene().GetShaderPlatform());

		// Stable RHI references: they follow texture rebuilds (format/settings changes) without recreating the proxy.
		HeightRes = C->HeightMap ? &C->HeightMap->TextureReference : nullptr;
		KindRes = C->KindMap ? &C->KindMap->TextureReference : nullptr;
		GrassHeightRes = C->GrassHeightMap ? &C->GrassHeightMap->TextureReference : nullptr;
		KindRes_Size = C->KindMap ? float(C->KindMap->GetSizeX()) : 1.f;
		HeightRes_Size = C->HeightMap ? float(C->HeightMap->GetSizeX()) : 1.f;
		KindTable = C->GetEffectiveKindTable();
		NumKinds = uint32(KindTable.Num() / 59);
		const float CompZ = float(C->GetComponentLocation().Z);
		MapOrigin = FVector2f(C->MapOrigin);
		MapSize = float(C->MapSizeCm);
		HeightScaleBias = FVector2f(C->HeightScale, C->HeightBias + CompZ);
		Area = FBox(FVector(C->MapOrigin.X, C->MapOrigin.Y, C->HeightBias + CompZ),
			FVector(C->MapOrigin.X + C->MapSizeCm, C->MapOrigin.Y + C->MapSizeCm, C->HeightBias + C->HeightScale + CompZ));
		BaseCellCm = C->BaseCellCm;
		JitterScale = C->JitterScale;
		LodScale = C->LodScale;
		DistFadeMul = C->DistFadeMul;
		DistFadeAdd = C->DistFadeAdd;
		BaseWidthScale = C->BaseWidthScale;
		MaxDistance = DistFadeMul < 0 ? (DistFadeAdd + 0.5f) / -DistFadeMul : 100000.f;
		MaxTileLevel = C->MaxTileLevel;
		MaxTiles = C->MaxTiles;
		NearCapacity = uint32(C->NearCapacity);
		FarCapacity = uint32(C->FarCapacity);
		FrustumMargin = C->FrustumMarginCm;
		LodMorph = FVector4f(C->LodMorph.X, C->LodMorph.Y, C->LodMorph.Z, 0.f);
		Grazing = FVector4f(C->Grazing.X, C->Grazing.Y, C->Grazing.Z, 0.f);
		ClumpNormalBlend = FVector3f(C->ClumpNormalStartCm, C->ClumpNormalEndCm, C->ClumpNormalStrength);
		bReadStats = C->bShowStats;
	}

	virtual SIZE_T GetTypeHash() const override
	{
		static size_t UniquePointer;
		return reinterpret_cast<size_t>(&UniquePointer);
	}

	virtual uint32 GetMemoryFootprint() const override { return sizeof(*this) + GetAllocatedSize(); }
	virtual bool CanBeOccluded() const override { return false; }

	static FRHITexture* Tex(const FTextureReference* Ref)
	{
		return (Ref && Ref->TextureReferenceRHI.IsValid()) ? Ref->TextureReferenceRHI.GetReference() : nullptr;
	}

	bool IsReady() const
	{
		const bool bReady = VertexFactory && KindsSRV && Tex(HeightRes) && Tex(KindRes) && Tex(GrassHeightRes) && NumKinds > 0;
		if (!bReady && !bLoggedNotReady)
		{
			bLoggedNotReady = true;
			UE_LOG(LogTemp, Warning, TEXT("GoTGrass: proxy not ready (VF %d kinds %d/%u height %d kind %d grassheight %d)"),
				VertexFactory != nullptr, KindsSRV.IsValid(), NumKinds, Tex(HeightRes) != nullptr, Tex(KindRes) != nullptr, Tex(GrassHeightRes) != nullptr);
		}
		return bReady;
	}

	virtual void CreateRenderThreadResources(FRHICommandListBase& RHICmdList) override
	{
		VertexFactory = new FGoTGrassVertexFactory(GetScene().GetFeatureLevel());
		VertexFactory->InitResource(RHICmdList);
		IndexNear = new FGoTGrassIndexBuffer(GoTGrass::NearVerts, GoTGrass::NearBladesPerInstance);
		IndexNear->InitResource(RHICmdList);
		IndexFar = new FGoTGrassIndexBuffer(GoTGrass::FarVerts, GoTGrass::FarBladesPerInstance);
		IndexFar->InitResource(RHICmdList);
		if (KindTable.Num() > 0)
		{
			KindsBuffer = UE::RHIResourceUtils::CreateBufferFromArray(RHICmdList, TEXT("GoT.GrassKinds"),
				EBufferUsageFlags::Static | EBufferUsageFlags::StructuredBuffer | EBufferUsageFlags::ShaderResource, sizeof(float), ERHIAccess::SRVMask,
				MakeConstArrayView(KindTable));
			KindsSRV = RHICmdList.CreateShaderResourceView(KindsBuffer, FRHIViewDesc::CreateBufferSRV().SetTypeFromBuffer(KindsBuffer));
		}
		Readback = MakeUnique<FRHIGPUBufferReadback>(TEXT("GoT.GrassCounters"));
	}

	virtual void DestroyRenderThreadResources() override
	{
		if (VertexFactory)
		{
			VertexFactory->ReleaseResource();
			delete VertexFactory;
			VertexFactory = nullptr;
		}
		for (FGoTGrassIndexBuffer** IB : { &IndexNear, &IndexFar })
		{
			if (*IB)
			{
				(*IB)->ReleaseResource();
				delete *IB;
				*IB = nullptr;
			}
		}
		KindsSRV.SafeRelease();
		KindsBuffer.SafeRelease();
		Readback.Reset();
	}

	virtual FPrimitiveViewRelevance GetViewRelevance(const FSceneView* View) const override
	{
		FPrimitiveViewRelevance Result;
		Result.bDrawRelevance = IsShown(View) && IsReady();
		Result.bShadowRelevance = false;              // [官方] grass is not in the shadow maps (screen-space / contact shadows)
		Result.bDynamicRelevance = true;
		Result.bStaticRelevance = false;
		Result.bRenderInMainPass = ShouldRenderInMainPass();
		Result.bRenderCustomDepth = ShouldRenderCustomDepth();
		Result.bUsesLightingChannels = GetLightingChannelMask() != GetDefaultLightingChannelMask();
		MaterialRelevance.SetPrimitiveViewRelevance(Result);
		Result.bVelocityRelevance = DrawsVelocity() && Result.bOpaque && Result.bRenderInMainPass;
		return Result;
	}

	virtual void GetDynamicMeshElements(const TArray<const FSceneView*>& Views, const FSceneViewFamily& ViewFamily, uint32 VisibilityMap, FMeshElementCollector& Collector) const override
	{
		if (!IsReady() || GGoTGrassExtension.IsInFrame())
		{
			return;    // work can only be added before the frame's generation pass (see FGoTGrassRendererExtension)
		}
		FGoTWindFrame Wind;
		GoTWindRender::GetFrame(&GetScene(), Wind);
		FRHITexture* FieldTexture = Wind.FieldTexture ? Wind.FieldTexture.GetReference() : GBlackTexture->TextureRHI.GetReference();
		FRHITexture* FieldTexturePrev = Wind.FieldTexturePrev ? Wind.FieldTexturePrev.GetReference() : GBlackTexture->TextureRHI.GetReference();
		const float FieldRes = (Wind.bFieldEnabled && FieldTexture) ? float(FieldTexture->GetDesc().Extent.X) : 256.f;
		const float FieldResPrev = (Wind.bFieldEnabledPrev && FieldTexturePrev) ? float(FieldTexturePrev->GetDesc().Extent.X) : 256.f;

		for (int32 ViewIndex = 0; ViewIndex < Views.Num(); ++ViewIndex)
		{
			if (!(VisibilityMap & (1 << ViewIndex)))
			{
				continue;
			}
			const FSceneView* View = Views[ViewIndex];
			if (View->bIsReflectionCapture)
			{
				continue;
			}
			const GoTGrass::FViewBuffers B = GGoTGrassExtension.AddWork(Collector.GetRHICommandList(), this, View);
			const FVector3f Origin = FVector3f(View->ViewMatrices.GetViewOrigin());

			for (uint32 Lod = 0; Lod < 2; ++Lod)
			{
				FGoTGrassVFParameters P;
				P.Blades = Lod == 0 ? B.BladesNearSRV : B.BladesFarSRV;
				P.Counters = B.CountersSRV;
				P.Kinds = KindsSRV;
				P.ClumpNormals = Lod == 0 ? B.ClumpNormalsNearSRV : B.ClumpNormalsFarSRV;
				P.WindMotion = Lod == 0 ? B.WindMotionNearSRV : B.WindMotionFarSRV;
				P.DispTexture = FieldTexture;
				P.DispTexturePrev = FieldTexturePrev;
				P.DispSampler = TStaticSamplerState<SF_Bilinear, AM_Clamp, AM_Clamp, AM_Clamp>::GetRHI();
				P.Origin = Origin;
				P.Capacity = Lod == 0 ? B.NearCapacity : B.FarCapacity;
				P.Layout = Lod == 0 ? FUintVector4(GoTGrass::NearVerts, GoTGrass::NearBladesPerInstance, 0, 0)
				                    : FUintVector4(GoTGrass::FarVerts, GoTGrass::FarBladesPerInstance, 1, 1);
				P.WindTime = FVector4f(Wind.Clock, Wind.ClockPrev, Wind.Shape.X, Wind.ShapePrev.X);
				P.FlutterStrength = FVector2f(Wind.GrassFlutterStrength, Wind.GrassFlutterStrengthPrev);
				P.WindDirAndDisp = FVector4f(Wind.Direction.X, Wind.Direction.Y, Wind.DisplacementScale, Wind.bFieldEnabled ? 1.f : 0.f);
				P.WindDirAndDispPrev = FVector4f(Wind.DirectionPrev.X, Wind.DirectionPrev.Y, Wind.DisplacementScalePrev, Wind.bFieldEnabledPrev ? 1.f : 0.f);
				P.LodMorph = LodMorph;
				P.Grazing = Grazing;
				P.ClumpNormalBlend = ClumpNormalBlend;
				P.DispCenterSize = FVector4f(Wind.FieldCenter.X - Origin.X, Wind.FieldCenter.Y - Origin.Y, 1.f / FMath::Max(Wind.FieldSize, 1.f), FieldRes);
				P.DispCenterSizePrev = FVector4f(Wind.FieldCenterPrev.X - Origin.X, Wind.FieldCenterPrev.Y - Origin.Y, 1.f / FMath::Max(Wind.FieldSizePrev, 1.f), FieldResPrev);
				P.Push = Wind.CameraPush;
				P.PushPrev = Wind.CameraPushPrev;
				P.PushZ = Wind.CameraPushZ;
				P.PushZPrev = Wind.CameraPushZPrev;

				FGoTGrassBatchUserData& UserData = Collector.AllocateOneFrameResource<FGoTGrassBatchUserData>();
				UserData.UniformBuffer = FGoTGrassVFBufferRef::CreateUniformBufferImmediate(P, UniformBuffer_SingleFrame);

				FMeshBatch& Mesh = Collector.AllocateMesh();
				Mesh.bWireframe = AllowDebugViewmodes() && ViewFamily.EngineShowFlags.Wireframe;
				Mesh.VertexFactory = VertexFactory;
				Mesh.MaterialRenderProxy = Material;
				Mesh.ReverseCulling = false;
				Mesh.Type = PT_TriangleList;
				Mesh.DepthPriorityGroup = SDPG_World;
				Mesh.bCanApplyViewModeOverrides = true;
				Mesh.bUseForMaterial = true;
				Mesh.CastShadow = false;
				Mesh.bUseForDepthPass = true;
				Mesh.Elements.SetNumZeroed(1);
				FMeshBatchElement& E = Mesh.Elements[0];
				E.IndexBuffer = Lod == 0 ? IndexNear : IndexFar;
				E.IndirectArgsBuffer = B.Args;
				E.IndirectArgsOffset = Lod * GoTGrass::ArgsStride;
				E.FirstIndex = 0;
				E.NumPrimitives = 0;
				E.MinVertexIndex = 0;
				E.MaxVertexIndex = (Lod == 0 ? GoTGrass::NearVerts * GoTGrass::NearBladesPerInstance : GoTGrass::FarVerts * GoTGrass::FarBladesPerInstance) - 1;
				E.PrimitiveIdMode = PrimID_ForceZero;
				E.PrimitiveUniformBuffer = GetUniformBuffer();
				E.UserData = &UserData;
				Collector.AddMesh(ViewIndex, Mesh);
			}
		}
	}

	// ---- data used by the generation pass (render thread) ----
	FMaterialRenderProxy* Material = nullptr;
	FMaterialRelevance MaterialRelevance;
	TSharedRef<FGoTGrassStats, ESPMode::ThreadSafe> Stats;
	const FTextureReference* HeightRes = nullptr;
	const FTextureReference* KindRes = nullptr;
	const FTextureReference* GrassHeightRes = nullptr;
	mutable bool bLoggedNotReady = false;
	mutable bool bLoggedFirstWork = false;
	float KindRes_Size = 1.f;
	float HeightRes_Size = 1.f;
	TArray<float> KindTable;
	uint32 NumKinds = 0;
	FVector2f MapOrigin;
	float MapSize = 1.f;
	FVector2f HeightScaleBias;
	FBox Area;
	float BaseCellCm = 9.765625f;
	float JitterScale = 1.35f;
	float LodScale = 0.0004f;
	float DistFadeMul = -0.0005f;
	float DistFadeAdd = 10.5f;
	float BaseWidthScale = 1.f;
	float MaxDistance = 21000.f;
	int32 MaxTileLevel = 4;
	int32 MaxTiles = 256;
	uint32 NearCapacity = 262144;
	uint32 FarCapacity = 524288;
	float FrustumMargin = 200.f;
	FVector4f LodMorph;
	FVector4f Grazing;
	FVector3f ClumpNormalBlend;
	bool bReadStats = false;

	FGoTGrassVertexFactory* VertexFactory = nullptr;
	FGoTGrassIndexBuffer* IndexNear = nullptr;
	FGoTGrassIndexBuffer* IndexFar = nullptr;
	FBufferRHIRef KindsBuffer;
	FShaderResourceViewRHIRef KindsSRV;
	mutable TUniquePtr<FRHIGPUBufferReadback> Readback;
	mutable bool bReadbackPending = false;
	mutable uint32 LastTileCount = 0;
};

// ---------------------------------------------------------------- extension implementation

GoTGrass::FViewBuffers FGoTGrassRendererExtension::AddWork(FRHICommandListBase& RHICmdList, const FGoTGrassSceneProxy* Proxy, const FSceneView* View)
{
	FScopeLock Lock(&Mutex);
	// 锁内复制 RHI 强引用，避免并行收集时 Buffers 扩容导致返回的数组引用悬空。
	for (const FWork& W : Works)
	{
		if (W.Proxy == Proxy && W.View == View)
		{
			return Buffers[W.BufferIndex];
		}
	}
	int32 Index = INDEX_NONE;
	for (int32 i = 0; i < Buffers.Num(); ++i)
	{
		if (LastUsed[i] < FrameId && Buffers[i].NearCapacity == Proxy->NearCapacity && Buffers[i].FarCapacity == Proxy->FarCapacity)
		{
			Index = i;
			break;
		}
	}
	if (Index == INDEX_NONE)
	{
		Index = Buffers.AddDefaulted();
		LastUsed.Add(0);
		GoTGrass::InitBuffers(RHICmdList, Buffers[Index], Proxy->NearCapacity, Proxy->FarCapacity);
	}
	LastUsed[Index] = FrameId;
	FWork& W = Works.AddDefaulted_GetRef();
	W.Proxy = Proxy;
	W.View = View;
	W.BufferIndex = Index;
	W.Origin = View->ViewMatrices.GetViewOrigin();
	W.Frustum = View->ViewFrustum;
	return Buffers[Index];
}

void FGoTGrassRendererExtension::BeginFrame(FRDGBuilder& GraphBuilder)
{
	FScopeLock Lock(&Mutex);
	bInFrame = true;
	if (Works.Num() == 0)
	{
		return;
	}
	RDG_EVENT_SCOPE_STAT(GraphBuilder, GoTGrass, "GoTGrass");
	for (const FWork& W : Works)
	{
		Submit(GraphBuilder, W);
	}
}

void FGoTGrassRendererExtension::EndFrame(FRDGBuilder& GraphBuilder)
{
	FScopeLock Lock(&Mutex);
	bInFrame = false;
	Works.Reset();
	++FrameId;
	for (int32 i = 0; i < Buffers.Num();)
	{
		if (FrameId - LastUsed[i] > 8u)
		{
			Buffers.RemoveAtSwap(i);
			LastUsed.RemoveAtSwap(i);
		}
		else
		{
			++i;
		}
	}
}

void FGoTGrassRendererExtension::Submit(FRDGBuilder& GraphBuilder, const FWork& W)
{
	const FGoTGrassSceneProxy* Proxy = W.Proxy;
	const GoTGrass::FViewBuffers B = Buffers[W.BufferIndex];

	// stats readback from an earlier frame
	if (Proxy->bReadbackPending && Proxy->Readback && Proxy->Readback->IsReady())
	{
		const uint32* Data = static_cast<const uint32*>(Proxy->Readback->Lock(4 * sizeof(uint32)));
		if (Data)
		{
			Proxy->Stats->Near = FMath::Min(Data[0], B.NearCapacity);
			Proxy->Stats->Far = FMath::Min(Data[1], B.FarCapacity);
		}
		Proxy->Readback->Unlock();
		Proxy->bReadbackPending = false;
	}

	FGoTWindFrame Wind;
	GoTWindRender::GetFrame(&Proxy->GetScene(), Wind);

	TArray<FGoTGrassTile> Tiles;
	GoTGrassTiles::Select(W.Origin, &W.Frustum, Proxy->Area, Proxy->BaseCellCm, Proxy->LodScale, Proxy->MaxDistance, Proxy->MaxTileLevel, Proxy->MaxTiles, Tiles);
	Proxy->LastTileCount = Tiles.Num();
	if (!Proxy->bLoggedFirstWork)
	{
		Proxy->bLoggedFirstWork = true;
		UE_LOG(LogTemp, Log, TEXT("GoTGrass: first generation at (%.0f, %.0f, %.0f): %d tiles, wind base %.0f"),
			W.Origin.X, W.Origin.Y, W.Origin.Z, Tiles.Num(), Wind.Shape.X);
	}
	Proxy->Stats->Tiles = Tiles.Num();

	TArray<FVector4f> TileFloats;
	TArray<FIntVector4> TileInts;
	for (const FGoTGrassTile& T : Tiles)
	{
		const float Mult = float(1 << T.Level);
		TileFloats.Add(FVector4f(float(double(T.CellOffset.X) * Proxy->BaseCellCm), float(double(T.CellOffset.Y) * Proxy->BaseCellCm), Proxy->BaseCellCm * Mult, 0.f));
		TileInts.Add(FIntVector4(T.CellOffset.X, T.CellOffset.Y, 1 << T.Level, T.Level == 0 ? 1 : 0));
	}
	const uint32 NumTiles = Tiles.Num();
	if (NumTiles == 0)
	{
		TileFloats.AddZeroed();
		TileInts.AddZeroed();
	}

	FGoTGrassGenerateCS::FParameters* G = GraphBuilder.AllocParameters<FGoTGrassGenerateCS::FParameters>();
	G->TileFloats = GraphBuilder.CreateSRV(CreateStructuredBuffer(GraphBuilder, TEXT("GoT.GrassTileFloats"), TileFloats));
	G->TileInts = GraphBuilder.CreateSRV(CreateStructuredBuffer(GraphBuilder, TEXT("GoT.GrassTileInts"), TileInts));
	G->NumTiles = NumTiles;
	G->ViewOrigin = FVector3f(W.Origin);
	const int32 NumPlanes = FMath::Min(W.Frustum.Planes.Num(), 6);
	for (int32 i = 0; i < 6; ++i)
	{
		const FPlane Pl = i < NumPlanes ? W.Frustum.Planes[i] : FPlane(0, 0, 0, 0);
		G->FrustumPlanes[i] = FVector4f(Pl.X, Pl.Y, Pl.Z, Pl.W);
	}
	G->NumFrustumPlanes = NumPlanes;
	G->FrustumMargin = Proxy->FrustumMargin;
	G->BaseCellCm = Proxy->BaseCellCm;
	G->JitterScale = Proxy->JitterScale;
	G->LodScale = Proxy->LodScale;
	G->DistFadeMul = Proxy->DistFadeMul;
	G->DistFadeAdd = Proxy->DistFadeAdd;
	G->BaseWidthScale = Proxy->BaseWidthScale;
	G->HeightMap = FGoTGrassSceneProxy::Tex(Proxy->HeightRes);
	G->HeightMapTransform = FVector4f(Proxy->MapOrigin.X, Proxy->MapOrigin.Y, 1.f / Proxy->MapSize, Proxy->MapSize / FMath::Max(Proxy->HeightRes_Size, 1.f));
	G->HeightScaleBias = Proxy->HeightScaleBias;
	G->KindMap = FGoTGrassSceneProxy::Tex(Proxy->KindRes);
	G->KindMapTransform = FVector4f(Proxy->MapOrigin.X, Proxy->MapOrigin.Y, 1.f / Proxy->MapSize, Proxy->KindRes_Size);
	G->GrassHeightMap = FGoTGrassSceneProxy::Tex(Proxy->GrassHeightRes);
	G->LinearClampSampler = TStaticSamplerState<SF_Bilinear, AM_Clamp, AM_Clamp, AM_Clamp>::GetRHI();
	G->Kinds = Proxy->KindsSRV;
	G->NumKinds = Proxy->NumKinds;
	G->WindNoise = Wind.Noise;
	G->WindNoisePrev = Wind.NoisePrev;
	G->WindShape = Wind.Shape;
	G->WindShapePrev = Wind.ShapePrev;
	G->WindDetailNoise = Wind.DetailNoise;
	G->WindDetailNoisePrev = Wind.DetailNoisePrev;
	G->DetailStrength = Wind.DetailStrength;
	G->DetailStrengthPrev = Wind.DetailStrengthPrev;
	G->WindDir = Wind.Direction;
	G->WindDirPrev = Wind.DirectionPrev;
	G->GustJitterCm = Wind.GustJitterCm;
	G->GustJitterCmPrev = Wind.GustJitterCmPrev;
	const bool bField = Wind.bFieldEnabled && Wind.FieldTexture.IsValid();
	G->WindField = Wind.FieldTexture ? Wind.FieldTexture.GetReference() : GBlackTexture->TextureRHI.GetReference();
	G->WindFieldPrev = Wind.FieldTexturePrev ? Wind.FieldTexturePrev.GetReference() : GBlackTexture->TextureRHI.GetReference();
	G->WindFieldTransform = FVector4f(Wind.FieldCenter.X, Wind.FieldCenter.Y, 1.f / FMath::Max(Wind.FieldSize, 1.f), bField ? 1.f : 0.f);
	G->WindFieldTransformPrev = FVector4f(Wind.FieldCenterPrev.X, Wind.FieldCenterPrev.Y, 1.f / FMath::Max(Wind.FieldSizePrev, 1.f), Wind.bFieldEnabledPrev ? 1.f : 0.f);
	G->VorticleForceScale = Wind.VorticleForceScale;
	G->VorticleForceScalePrev = Wind.VorticleForceScalePrev;
	G->RWBladesNear = B.BladesNearUAV;
	G->RWBladesFar = B.BladesFarUAV;
	G->RWCounters = B.CountersUAV;
	FRDGBufferRef ClumpNormalsNear = GraphBuilder.RegisterExternalBuffer(B.ClumpNormalsNearPooled);
	FRDGBufferRef ClumpNormalsFar = GraphBuilder.RegisterExternalBuffer(B.ClumpNormalsFarPooled);
	G->RWClumpNormalsNear = GraphBuilder.CreateUAV(FRDGBufferUAVDesc(ClumpNormalsNear, PF_R32_UINT));
	G->RWClumpNormalsFar = GraphBuilder.CreateUAV(FRDGBufferUAVDesc(ClumpNormalsFar, PF_R32_UINT));
	FRDGBufferRef WindMotionNear = GraphBuilder.RegisterExternalBuffer(B.WindMotionNearPooled);
	FRDGBufferRef WindMotionFar = GraphBuilder.RegisterExternalBuffer(B.WindMotionFarPooled);
	G->RWWindMotionNear = GraphBuilder.CreateUAV(FRDGBufferUAVDesc(WindMotionNear, PF_A32B32G32R32F));
	G->RWWindMotionFar = GraphBuilder.CreateUAV(FRDGBufferUAVDesc(WindMotionFar, PF_A32B32G32R32F));
	G->CapacityNear = B.NearCapacity;
	G->CapacityFar = B.FarCapacity;

	FGoTGrassFinalizeCS::FParameters* F = GraphBuilder.AllocParameters<FGoTGrassFinalizeCS::FParameters>();
	F->RWCounters = B.CountersUAV;
	F->RWIndirectArgs = B.ArgsUAV;
	F->IndicesPerInstanceNear = GoTGrass::NearBladesPerInstance * (GoTGrass::NearVerts - 2) * 3;
	F->IndicesPerInstanceFar = GoTGrass::FarBladesPerInstance * (GoTGrass::FarVerts - 2) * 3;
	F->BladesPerInstanceNear = GoTGrass::NearBladesPerInstance;
	F->BladesPerInstanceFar = GoTGrass::FarBladesPerInstance;
	F->CapacityNear = B.NearCapacity;
	F->CapacityFar = B.FarCapacity;

	FGlobalShaderMap* ShaderMap = GetGlobalShaderMap(GMaxRHIFeatureLevel);
	TShaderMapRef<FGoTGrassGenerateCS> GenShader(ShaderMap);
	TShaderMapRef<FGoTGrassFinalizeCS> FinShader(ShaderMap);

	// The output buffers are drawn by the mesh passes outside RDG's tracking: transitions are explicit (as Virtual Heightfield Mesh does).
	GraphBuilder.AddPass(RDG_EVENT_NAME("GoTGrass Generate %u tiles", NumTiles), G, ERDGPassFlags::Compute | ERDGPassFlags::NeverCull,
		[G, F, GenShader, FinShader, B, NumTiles, Wind](FRHIComputeCommandList& RHICmdList)
	{
		(void)Wind; // 生成期间保活当前/前帧局部纹理 RHI 引用。
		const FRHITransitionInfo ToWrite[] = {
			FRHITransitionInfo(B.BladesNear.GetReference(), ERHIAccess::SRVMask, ERHIAccess::UAVCompute),
			FRHITransitionInfo(B.BladesFar.GetReference(), ERHIAccess::SRVMask, ERHIAccess::UAVCompute),
			FRHITransitionInfo(B.Counters.GetReference(), ERHIAccess::SRVMask, ERHIAccess::UAVCompute),
			FRHITransitionInfo(B.Args.GetReference(), ERHIAccess::IndirectArgs, ERHIAccess::UAVCompute) };
		RHICmdList.Transition(MakeArrayView(ToWrite));
		RHICmdList.ClearUAVUint(B.CountersUAV, FUintVector4(0, 0, 0, 0));
		RHICmdList.Transition(FRHITransitionInfo(B.CountersUAV.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::UAVCompute));
		if (NumTiles > 0)
		{
			FComputeShaderUtils::Dispatch(RHICmdList, GenShader, *G, FIntVector(32, 32, int32(NumTiles)));
			RHICmdList.Transition(FRHITransitionInfo(B.CountersUAV.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::UAVCompute));
		}
		FComputeShaderUtils::Dispatch(RHICmdList, FinShader, *F, FIntVector(1, 1, 1));
		const FRHITransitionInfo ToRead[] = {
			FRHITransitionInfo(B.BladesNear.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::SRVMask),
			FRHITransitionInfo(B.BladesFar.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::SRVMask),
			FRHITransitionInfo(B.Counters.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::SRVMask),
			FRHITransitionInfo(B.Args.GetReference(), ERHIAccess::UAVCompute, ERHIAccess::IndirectArgs) };
		RHICmdList.Transition(MakeArrayView(ToRead));
	});

	// 法线 sidecar 后续由 VF 在 RDG 外部绑定；在绘制前完成 UAV -> SRVGraphics 屏障。
	GraphBuilder.UseExternalAccessMode(ClumpNormalsNear, ERHIAccess::SRVGraphics);
	GraphBuilder.UseExternalAccessMode(ClumpNormalsFar, ERHIAccess::SRVGraphics);
	GraphBuilder.UseExternalAccessMode(WindMotionNear, ERHIAccess::SRVGraphics);
	GraphBuilder.UseExternalAccessMode(WindMotionFar, ERHIAccess::SRVGraphics);

	if (Proxy->bReadStats && !Proxy->bReadbackPending && Proxy->Readback)
	{
		Proxy->bReadbackPending = true;
		FRHIGPUBufferReadback* Readback = Proxy->Readback.Get();
		AddPass(GraphBuilder, RDG_EVENT_NAME("GoTGrass Readback"), [Readback, Counters = B.Counters](FRHICommandList& RHICmdList)
		{
			RHICmdList.Transition(FRHITransitionInfo(Counters.GetReference(), ERHIAccess::SRVMask, ERHIAccess::CopySrc));
			Readback->EnqueueCopy(RHICmdList, Counters.GetReference(), 4 * sizeof(uint32));
			RHICmdList.Transition(FRHITransitionInfo(Counters.GetReference(), ERHIAccess::CopySrc, ERHIAccess::SRVMask));
		});
	}
}

// ---------------------------------------------------------------- component

TArray<float> UGoTGrassComponent::GetEffectiveKindTable() const
{
	TArray<float> Effective;
	FString Error;
	if (!GoTGrassKinds::ApplyOverrides(KindTable, KindOverrides, Effective, Error))
	{
		UE_LOG(LogTemp, Error, TEXT("GoTGrass: %s: %s"), *GetPathName(), *Error);
	}
	return Effective;
}

UGoTGrassComponent::UGoTGrassComponent()
	: Stats(MakeShared<FGoTGrassStats, ESPMode::ThreadSafe>())
{
	PrimaryComponentTick.bCanEverTick = true;
	bTickInEditor = true;
	Mobility = EComponentMobility::Movable;
	CastShadow = false;
	bCastDynamicShadow = false;
	bAffectDistanceFieldLighting = false;
	bAffectDynamicIndirectLighting = false;
	bVisibleInRayTracing = false;
	bUseAsOccluder = false;
	SetGenerateOverlapEvents(false);
	SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
}

FPrimitiveSceneProxy* UGoTGrassComponent::CreateSceneProxy()
{
	if (!HeightMap || !KindMap || !GrassHeightMap || KindTable.Num() < 59)
	{
		UE_LOG(LogTemp, Warning, TEXT("GoTGrass: %s has no maps or kind table, nothing to draw"), *GetPathName());
		return nullptr;
	}
	return new FGoTGrassSceneProxy(this);
}

FBoxSphereBounds UGoTGrassComponent::CalcBounds(const FTransform& LocalToWorld) const
{
	const double Z = LocalToWorld.GetLocation().Z;
	const FBox Box(FVector(MapOrigin.X, MapOrigin.Y, HeightBias + Z - 500.0),
		FVector(MapOrigin.X + MapSizeCm, MapOrigin.Y + MapSizeCm, HeightBias + HeightScale + Z + 500.0));
	return FBoxSphereBounds(Box);
}

void UGoTGrassComponent::GetUsedMaterials(TArray<UMaterialInterface*>& OutMaterials, bool bGetDebugMaterials) const
{
	if (Material)
	{
		OutMaterials.Add(Material);
	}
}

void UGoTGrassComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	UWorld* World = GetWorld();
	if (!World || (!bShowTiles && !bShowStats))
	{
		return;
	}
	FVector ViewOrigin = FVector::ZeroVector;
	if (World->IsGameWorld())
	{
		if (const APlayerController* PC = World->GetFirstPlayerController())
		{
			FRotator Rot;
			PC->GetPlayerViewPoint(ViewOrigin, Rot);
		}
	}
	else if (World->ViewLocationsRenderedLastFrame.Num() > 0)
	{
		ViewOrigin = World->ViewLocationsRenderedLastFrame[0];
	}
	if (bShowTiles)
	{
		const FBoxSphereBounds B = CalcBounds(GetComponentTransform());
		const float MaxDist = DistFadeMul < 0 ? (DistFadeAdd + 0.5f) / -DistFadeMul : 100000.f;
		TArray<FGoTGrassTile> Tiles;
		GoTGrassTiles::Select(ViewOrigin, nullptr, B.GetBox(), BaseCellCm, LodScale, MaxDist, MaxTileLevel, MaxTiles, Tiles);
		static const FColor LevelColors[] = { FColor(255, 60, 60), FColor(255, 170, 30), FColor(240, 240, 40), FColor(60, 230, 90), FColor(60, 160, 255), FColor(200, 90, 255), FColor::White };
		for (const FGoTGrassTile& T : Tiles)
		{
			const double Size = 256.0 * double(1 << T.Level) * BaseCellCm;
			const FVector2D Min(T.CellOffset.X * double(BaseCellCm), T.CellOffset.Y * double(BaseCellCm));
			const FVector2D C = Min + FVector2D(Size * 0.5, Size * 0.5);
			double Z = ViewOrigin.Z - 200.0;
			FHitResult Hit;
			if (World->LineTraceSingleByChannel(Hit, FVector(C, 40000.0), FVector(C, -40000.0), ECC_WorldStatic, FCollisionQueryParams(SCENE_QUERY_STAT(GoTGrassTiles), false)))
			{
				Z = Hit.ImpactPoint.Z;
			}
			DrawDebugBox(World, FVector(C, Z + 50.0), FVector(Size * 0.5 - 20.0, Size * 0.5 - 20.0, 50.0), LevelColors[FMath::Min(T.Level, 6)], false, -1.f, SDPG_World, 6.f + 4.f * T.Level);
		}
	}
	if (bShowStats && GEngine)
	{
		const uint32 Near = Stats->Near.load(), Far = Stats->Far.load();
		GEngine->AddOnScreenDebugMessage(uint64(reinterpret_cast<uintptr_t>(this)), 0.f, FColor(120, 255, 120),
			FString::Printf(TEXT("GoTGrass: %u blades (near 15-vert %u / %u, far 7-vert %u / %u), %u tiles. GPU time: stat GPU -> GoTGrass"),
				Near + Far, Near, uint32(NearCapacity), Far, uint32(FarCapacity), Stats->Tiles.load()));
	}
}

#if WITH_EDITOR
void UGoTGrassComponent::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);
	MarkRenderStateDirty();
	UpdateBounds();
}
#endif

AGoTGrassActor::AGoTGrassActor()
{
	Grass = CreateDefaultSubobject<UGoTGrassComponent>(TEXT("Grass"));
	RootComponent = Grass;
#if WITH_EDITORONLY_DATA
	bIsSpatiallyLoaded = false;   // generates around every camera, the whole map
#endif
}
