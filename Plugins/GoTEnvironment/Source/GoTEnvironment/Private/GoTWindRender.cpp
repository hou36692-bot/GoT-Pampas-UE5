#include "GoTWindRender.h"

#include "DataDrivenShaderPlatformInfo.h"
#include "Engine/TextureRenderTarget2D.h"
#include "GlobalShader.h"
#include "Misc/ScopeRWLock.h"
#include "RenderGraphBuilder.h"
#include "RenderGraphUtils.h"
#include "RenderingThread.h"
#include "RenderTargetPool.h"
#include "ShaderParameterStruct.h"
#include "TextureResource.h"
#include "Math/Float16.h"

#include "GoTPerlinTables.inl"

// ---------------------------------------------------------------- CPU noise (mirror of GoTWindCommon.ush)

namespace GoTWindNoise
{
	static FORCEINLINE int32 Perm(int32 I)
	{
		return GGoTPerlinPerm[I & 255];
	}

	static FORCEINLINE float GradDot(int32 Hash, float X, float Y, float Z)
	{
		const float* G = GGoTPerlinGrad[Hash & 31];
		return G[0] * X + G[1] * Y + G[2] * Z;
	}

	float Perlin3D(const FVector3f& P)
	{
		const float Fx = FMath::FloorToFloat(P.X), Fy = FMath::FloorToFloat(P.Y), Fz = FMath::FloorToFloat(P.Z);
		const int32 X = (int32)Fx, Y = (int32)Fy, Z = (int32)Fz;
		const float x = P.X - Fx, y = P.Y - Fy, z = P.Z - Fz;
		auto Fade = [](float T) { return T * T * T * (T * (T * 6.f - 15.f) + 10.f); };
		const float U = Fade(x), V = Fade(y), W = Fade(z);
		const int32 A = Perm(X) + Y, B = Perm(X + 1) + Y;
		const int32 AA = Perm(A) + Z, AB = Perm(A + 1) + Z, BA = Perm(B) + Z, BB = Perm(B + 1) + Z;
		const float G000 = GradDot(Perm(AA), x, y, z);
		const float G100 = GradDot(Perm(BA), x - 1, y, z);
		const float G010 = GradDot(Perm(AB), x, y - 1, z);
		const float G110 = GradDot(Perm(BB), x - 1, y - 1, z);
		const float G001 = GradDot(Perm(AA + 1), x, y, z - 1);
		const float G101 = GradDot(Perm(BA + 1), x - 1, y, z - 1);
		const float G011 = GradDot(Perm(AB + 1), x, y - 1, z - 1);
		const float G111 = GradDot(Perm(BB + 1), x - 1, y - 1, z - 1);
		const float X00 = FMath::Lerp(G000, G100, U), X10 = FMath::Lerp(G010, G110, U);
		const float X01 = FMath::Lerp(G001, G101, U), X11 = FMath::Lerp(G011, G111, U);
		return FMath::Lerp(FMath::Lerp(X00, X10, V), FMath::Lerp(X01, X11, V), W);
	}

	float GustAmount(const FVector2f& WorldXY, const FVector4f& Noise, const FVector4f& Shape)
	{
		const float N = Perlin3D(FVector3f(WorldXY.X * Noise.W + Noise.X, WorldXY.Y * Noise.W + Noise.Y, Noise.Z));
		return FMath::Clamp((N * 0.5f + 0.5f) * Shape.Z + Shape.W, 0.f, 1.f);
	}

	float GustForce(const FVector2f& WorldXY, const FVector4f& Noise, const FVector4f& Shape)
	{
		return Shape.X + Shape.X * GustAmount(WorldXY, Noise, Shape) * Shape.Y;
	}

	float GrassGustForce(const FVector2f& WorldXY, const FVector4f& MacroNoise, const FVector4f& MacroShape,
		const FVector4f& DetailNoise, float DetailStrength)
	{
		const float Force = GustForce(WorldXY, MacroNoise, MacroShape);
		if (DetailStrength <= 0.f)
		{
			return Force;
		}
		const float Detail = Perlin3D(FVector3f(WorldXY.X * DetailNoise.W + DetailNoise.X,
			WorldXY.Y * DetailNoise.W + DetailNoise.Y, DetailNoise.Z));
		return FMath::Max(0.f, Force + MacroShape.X * DetailStrength * Detail);
	}

	FVector2f ComposeWind(const FVector2f& MainDir, float Force, const FVector2f& LocalVelocity,
		float LocalScale, float& Speed, float& DeflectionAngle)
	{
		const FVector2f Local = LocalVelocity * LocalScale;
		if (Local.X == 0.f && Local.Y == 0.f)
		{
			Speed = Force;
			DeflectionAngle = 0.f;
			return MainDir * Force;
		}
		const FVector2f Net = MainDir * Force + Local;
		Speed = Net.Size();
		DeflectionAngle = 0.f;
		if (Speed <= 1e-4f)
		{
			Speed = 0.f;
			return FVector2f::ZeroVector;
		}
		DeflectionAngle = FMath::Atan2(MainDir.X * Net.Y - MainDir.Y * Net.X, FVector2f::DotProduct(MainDir, Net));
		return Net;
	}

	FVector3f BuildWindBend(const FVector2f& Facing, float Idle, float WindValue, float DeflectionAngle)
	{
		const float Total = Idle + WindValue;
		const float W = FMath::Clamp(Total, 0.f, 1.f);
		if (DeflectionAngle == 0.f) return FVector3f(Facing.X * W, Facing.Y * W, W);
		if (Total <= 0.f) return FVector3f::ZeroVector;
		const float C = FMath::Cos(DeflectionAngle), S = FMath::Sin(DeflectionAngle);
		const FVector2f Rotated(Facing.X * C - Facing.Y * S, Facing.X * S + Facing.Y * C);
		const FVector2f Bend = (Facing * Idle + Rotated * WindValue) * (W / Total);
		return FVector3f(Bend.X, Bend.Y, W);
	}
}

// ---------------------------------------------------------------- per-scene frames for the render thread

namespace GoTWindRender
{
	static FRWLock GFramesLock;
	static TMap<const FSceneInterface*, FGoTWindFrame> GFrames;

	void SetFrame_GameThread(const FSceneInterface* Scene, const FGoTWindFrame& Frame)
	{
		ENQUEUE_RENDER_COMMAND(GoTWindSetFrame)([Scene, Frame](FRHICommandListImmediate&)
		{
			FGoTWindFrame Resolved = Frame;
			if (Frame.bFieldEnabled && Frame.FieldResource) Resolved.FieldTexture = Frame.FieldResource->TextureRHI;
			else Resolved.FieldTexture.SafeRelease();
			if (Frame.bFieldEnabledPrev && Frame.FieldResourcePrev) Resolved.FieldTexturePrev = Frame.FieldResourcePrev->TextureRHI;
			else Resolved.FieldTexturePrev.SafeRelease();
			FWriteScopeLock Lock(GFramesLock);
			GFrames.Add(Scene, MoveTemp(Resolved));
		});
	}

	void RemoveScene_GameThread(const FSceneInterface* Scene)
	{
		ENQUEUE_RENDER_COMMAND(GoTWindRemoveScene)([Scene](FRHICommandListImmediate&)
		{
			FWriteScopeLock Lock(GFramesLock);
			GFrames.Remove(Scene);
		});
	}

	bool GetFrame(const FSceneInterface* Scene, FGoTWindFrame& OutFrame)
	{
		FReadScopeLock Lock(GFramesLock);
		if (const FGoTWindFrame* F = GFrames.Find(Scene))
		{
			OutFrame = *F;
			return true;
		}
		return false;
	}
}

// ---------------------------------------------------------------- interaction / vorticle field

class FGoTWindFieldCS : public FGlobalShader
{
public:
	DECLARE_GLOBAL_SHADER(FGoTWindFieldCS);
	SHADER_USE_PARAMETER_STRUCT(FGoTWindFieldCS, FGlobalShader);

	BEGIN_SHADER_PARAMETER_STRUCT(FParameters, )
		SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float4>, Particles)
		SHADER_PARAMETER(uint32, NumParticles)
		SHADER_PARAMETER_RDG_BUFFER_SRV(StructuredBuffer<float4>, Vorticles)
		SHADER_PARAMETER(uint32, NumVorticles)
		SHADER_PARAMETER(FVector4f, FieldCenterSize)
		SHADER_PARAMETER(FVector4f, Wave)
		SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D<float4>, RWField)
	END_SHADER_PARAMETER_STRUCT()

	static bool ShouldCompilePermutation(const FGlobalShaderPermutationParameters& Parameters)
	{
		return IsFeatureLevelSupported(Parameters.Platform, ERHIFeatureLevel::SM5);
	}
};

IMPLEMENT_GLOBAL_SHADER(FGoTWindFieldCS, "/Plugin/GoTEnvironment/Private/GoTWindField.usf", "FieldCS", SF_Compute);

namespace GoTWindField
{
	FVector2f SampleLocalWind(const FVector2f& WorldXY, const FSnapshot& Snapshot)
	{
		if (!Snapshot.bEnabled || Snapshot.Size <= 0.f || Snapshot.Resolution <= 0) return FVector2f::ZeroVector;
		const FVector2f UV = (WorldXY - Snapshot.Center) * (1.f / Snapshot.Size) + FVector2f(0.5f, 0.5f);
		const float EdgeX = FMath::Clamp((0.5f - FMath::Abs(UV.X - 0.5f)) * 16.f, 0.f, 1.f);
		const float EdgeY = FMath::Clamp((0.5f - FMath::Abs(UV.Y - 0.5f)) * 16.f, 0.f, 1.f);
		if (EdgeX * EdgeY <= 0.f) return FVector2f::ZeroVector;
		const float Res = float(Snapshot.Resolution), Texel = Snapshot.Size / Res;
		const FVector2f TC = UV * Res - FVector2f(0.5f, 0.5f);
		const int32 X0 = FMath::FloorToInt(TC.X), Y0 = FMath::FloorToInt(TC.Y);
		const float Fx = TC.X - X0, Fy = TC.Y - Y0;
		auto AtTexel = [&](int32 X, int32 Y)
		{
			X = FMath::Clamp(X, 0, Snapshot.Resolution - 1);
			Y = FMath::Clamp(Y, 0, Snapshot.Resolution - 1);
			const FVector2f P = Snapshot.Center + FVector2f(float(X) + 0.5f - Res * 0.5f, float(Y) + 0.5f - Res * 0.5f) * Texel;
			FVector2f Wind = FVector2f::ZeroVector;
			for (const FVorticle& V : Snapshot.Vorticles)
			{
				const float R2 = (P - V.Position).SizeSquared() / (V.Radius * V.Radius);
				if (R2 < 1.f)
				{
					const float T = 1.f - R2;
					Wind += V.Wind * (V.Fade * (T * T));
				}
			}
			return FVector2f(FFloat16(FMath::Clamp(Wind.X, -60000.f, 60000.f)).GetFloat(),
				FFloat16(FMath::Clamp(Wind.Y, -60000.f, 60000.f)).GetFloat());
		};
		const FVector2f A = FMath::Lerp(AtTexel(X0, Y0), AtTexel(X0 + 1, Y0), Fx);
		const FVector2f B = FMath::Lerp(AtTexel(X0, Y0 + 1), AtTexel(X0 + 1, Y0 + 1), Fx);
		return FMath::Lerp(A, B, Fy) * (EdgeX * EdgeY);
	}

	void Update_GameThread(UTextureRenderTarget2D* Target, UTextureRenderTarget2D* PreviousTarget,
		const FSnapshot& Snapshot, bool bClearHistory)
	{
		FTextureRenderTargetResource* Resource = Target ? Target->GameThread_GetRenderTargetResource() : nullptr;
		FTextureRenderTargetResource* PreviousResource = PreviousTarget ? PreviousTarget->GameThread_GetRenderTargetResource() : nullptr;
		if (!Resource || !Target->bCanCreateUAV)
		{
			static bool bWarned = false;
			if (!bWarned && Target)
			{
				UE_LOG(LogTemp, Warning, TEXT("GoTWind: %s needs bCanCreateUAV for the GPU interaction field"), *Target->GetName());
				bWarned = true;
			}
			return;
		}
		TArray<FVector4f> P;
		P.Reserve(FMath::Max(Snapshot.Particles.Num(), 1) * 2);
		for (const FParticle& Pa : Snapshot.Particles)
		{
			P.Add(FVector4f(Pa.Position.X, Pa.Position.Y, Pa.Age, Pa.Radius));
			P.Add(FVector4f(Pa.Strength, 0.f, 0.f, 0.f));
		}
		TArray<FVector4f> V;
		V.Reserve(FMath::Max(Snapshot.Vorticles.Num(), 1) * 2);
		for (const FVorticle& Vo : Snapshot.Vorticles)
		{
			V.Add(FVector4f(Vo.Position.X, Vo.Position.Y, Vo.Radius, Vo.Fade));
			V.Add(FVector4f(Vo.Wind.X, Vo.Wind.Y, 0.f, 0.f));
		}
		const uint32 NumParticles = Snapshot.Particles.Num();
		const uint32 NumVorticles = Snapshot.Vorticles.Num();
		if (P.Num() == 0) { P.AddZeroed(2); }
		if (V.Num() == 0) { V.AddZeroed(2); }
		const int32 Res = Target->SizeX;
		const FVector4f CenterSize(Snapshot.Center.X, Snapshot.Center.Y, Snapshot.Size, float(Res));
		const FVector4f Wave(Snapshot.WaveDecay, Snapshot.WaveFrequency, 0.f, 0.f);

		ENQUEUE_RENDER_COMMAND(GoTWindField)([Resource, PreviousResource, bClearHistory, P = MoveTemp(P), V = MoveTemp(V), NumParticles, NumVorticles, CenterSize, Wave, Res](FRHICommandListImmediate& RHICmdList)
		{
			const FTextureRHIRef Texture(Resource->GetRenderTargetTexture());
			if (!Texture || !EnumHasAnyFlags(Texture->GetFlags(), TexCreate_UAV))
			{
				return;
			}
			FRDGBuilder GraphBuilder(RHICmdList, RDG_EVENT_NAME("GoTWindField"));
			FRDGTextureRef Field = GraphBuilder.RegisterExternalTexture(CreateRenderTarget(Texture, TEXT("GoT.InteractionField")));
			FRDGTextureRef PreviousField = nullptr;
			if (PreviousResource)
			{
				const FTextureRHIRef PreviousTexture(PreviousResource->GetRenderTargetTexture());
				if (PreviousTexture && PreviousTexture != Texture)
				{
					PreviousField = GraphBuilder.RegisterExternalTexture(CreateRenderTarget(PreviousTexture, TEXT("GoT.InteractionFieldPrev")));
				}
			}
			if (bClearHistory)
			{
				AddClearUAVPass(GraphBuilder, GraphBuilder.CreateUAV(Field), FVector4f(0, 0, 0, 0));
				if (PreviousField) AddClearUAVPass(GraphBuilder, GraphBuilder.CreateUAV(PreviousField), FVector4f(0, 0, 0, 0));
			}
			if (PreviousField) AddCopyTexturePass(GraphBuilder, Field, PreviousField);
			FRDGBufferRef Particles = CreateStructuredBuffer(GraphBuilder, TEXT("GoT.WindParticles"), sizeof(FVector4f), P.Num(), P.GetData(), P.Num() * sizeof(FVector4f));
			FRDGBufferRef Vorts = CreateStructuredBuffer(GraphBuilder, TEXT("GoT.Vorticles"), sizeof(FVector4f), V.Num(), V.GetData(), V.Num() * sizeof(FVector4f));

			FGoTWindFieldCS::FParameters* Params = GraphBuilder.AllocParameters<FGoTWindFieldCS::FParameters>();
			Params->Particles = GraphBuilder.CreateSRV(Particles);
			Params->NumParticles = NumParticles;
			Params->Vorticles = GraphBuilder.CreateSRV(Vorts);
			Params->NumVorticles = NumVorticles;
			Params->FieldCenterSize = CenterSize;
			Params->Wave = Wave;
			Params->RWField = GraphBuilder.CreateUAV(Field);
			TShaderMapRef<FGoTWindFieldCS> Shader(GetGlobalShaderMap(GMaxRHIFeatureLevel));
			FComputeShaderUtils::AddPass(GraphBuilder, RDG_EVENT_NAME("GoTWindField %dx%d", Res, Res), Shader, Params,
				FComputeShaderUtils::GetGroupCount(FIntPoint(Res, Res), 8));
			GraphBuilder.SetTextureAccessFinal(Field, ERHIAccess::SRVMask);
			if (PreviousField) GraphBuilder.SetTextureAccessFinal(PreviousField, ERHIAccess::SRVMask);
			GraphBuilder.Execute();
		});
	}
}
