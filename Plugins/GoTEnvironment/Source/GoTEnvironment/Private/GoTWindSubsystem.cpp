#include "GoTWindSubsystem.h"
#include "GoTWindController.h"
#include "GoTWindInteractorComponent.h"
#include "GoTWindRender.h"
#include "GoTWindSettings.h"

#include "Camera/PlayerCameraManager.h"
#include "DrawDebugHelpers.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
#include "SceneInterface.h"

namespace GoTWind
{
	static const FName WindDir(TEXT("WindDir"));
	static const FName GustNoise(TEXT("GustNoise"));
	static const FName GustShape(TEXT("GustShape"));
	static const FName WindDetailNoise(TEXT("WindDetailNoise"));
	static const FName WindResponse(TEXT("WindResponse"));
	static const FName WindTime(TEXT("WindTime"));
	static const FName Interact(TEXT("Interact"));
	static const FName Pampas(TEXT("Pampas"));
	static const FName Tree(TEXT("Tree"));
	static const FName ConsumerPush(TEXT("ConsumerPush"));
	static const FName WindDebug(TEXT("WindDebug"));
	static const FName WindDirPrev(TEXT("WindDirPrev"));
	static const FName GustNoisePrev(TEXT("GustNoisePrev"));
	static const FName GustShapePrev(TEXT("GustShapePrev"));
	static const FName WindDetailNoisePrev(TEXT("WindDetailNoisePrev"));
	static const FName WindResponsePrev(TEXT("WindResponsePrev"));
	static const FName WindTimePrev(TEXT("WindTimePrev"));
	static const FName InteractPrev(TEXT("InteractPrev"));
	static const FName PampasPrev(TEXT("PampasPrev"));
	static const FName TreePrev(TEXT("TreePrev"));
	static const FName ConsumerPushPrev(TEXT("ConsumerPushPrev"));

	/** The Perlin lattice repeats every 256 units: keep offsets small for float precision. */
	static float Wrap256(float V)
	{
		return V - 256.f * FMath::FloorToFloat(V / 256.f);
	}

	static float Wrap(float V, float Period)
	{
		return V - Period * FMath::FloorToFloat(V / Period);
	}
}

bool UGoTWindSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	if (!World || IsRunningCommandlet())
	{
		return false;
	}
	const EWorldType::Type Type = World->WorldType;
	return Type == EWorldType::Game || Type == EWorldType::PIE || Type == EWorldType::Editor;
}

void UGoTWindSubsystem::Initialize(FSubsystemCollectionBase& Collection_)
{
	Super::Initialize(Collection_);
	const UGoTWindSettings* Settings = GetDefault<UGoTWindSettings>();
	Collection = Settings->WindCollection.LoadSynchronous();
	Target = Settings->InteractionTarget.LoadSynchronous();
	PreviousTarget = Settings->PreviousInteractionTarget.LoadSynchronous();
	if (Target && (Target->SizeX != Target->SizeY || Target->GetFormat() != PF_FloatRGBA))
	{
		UE_LOG(LogTemp, Error, TEXT("GoTWind: 当前交互场必须为正方形 RGBA16F。"));
		Target = nullptr;
	}
	if (PreviousTarget && (!Target || PreviousTarget == Target || PreviousTarget->SizeX != Target->SizeX
		|| PreviousTarget->SizeY != Target->SizeY || PreviousTarget->GetFormat() != Target->GetFormat()))
	{
		UE_LOG(LogTemp, Error, TEXT("GoTWind: 前帧交互场必须为独立、同尺寸 RGBA16F 纹理。"));
		PreviousTarget = nullptr;
	}
	for (UTextureRenderTarget2D* FieldTarget : { Target.Get(), PreviousTarget.Get() })
	{
		if (FieldTarget && !FieldTarget->bCanCreateUAV)
		{
			FieldTarget->bCanCreateUAV = true;
			FieldTarget->UpdateResourceImmediate(true);
		}
	}
	UE_LOG(LogTemp, Log, TEXT("GoTWind: subsystem for %s (MPC %s, field %s)"), *GetWorld()->GetName(),
		Collection ? *Collection->GetName() : TEXT("none"), Target ? *Target->GetName() : TEXT("none"));
}

void UGoTWindSubsystem::Deinitialize()
{
	if (UWorld* World = GetWorld())
	{
		GoTWindRender::RemoveScene_GameThread(World->Scene);
	}
	Interactors.Reset();
	RegisteredComponents.Reset();
	Trail.Reset();
	Vorticles.Reset();
	Super::Deinitialize();
}

TStatId UGoTWindSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UGoTWindSubsystem, STATGROUP_Tickables);
}

const FGoTWindParams& UGoTWindSubsystem::GetParams() const
{
	if (const AGoTWindController* C = Controller.Get())
	{
		return C->Params;
	}
	return GetDefault<UGoTWindSettings>()->Params;
}

void UGoTWindSubsystem::FindController()
{
	if (Controller.IsValid() || RealTime < NextControllerSearch)
	{
		return;
	}
	NextControllerSearch = RealTime + 1.0;
	for (TActorIterator<AGoTWindController> It(GetWorld()); It; ++It)
	{
		Controller = *It;
		break;
	}
}

float UGoTWindSubsystem::ForceAt(const FVector2f& P) const
{
	return GoTWindNoise::GustForce(P, Frame.Noise, Frame.Shape);
}

float UGoTWindSubsystem::GustAt(const FVector2f& P) const
{
	return GoTWindNoise::GustAmount(P, Frame.Noise, Frame.Shape);
}

FVector2f UGoTWindSubsystem::CombinedAt(const FVector2f& P, float DetailWeight) const
{
	const float Force = GoTWindNoise::GrassGustForce(P, Frame.Noise, Frame.Shape, Frame.DetailNoise,
		Frame.DetailStrength * FMath::Max(0.f, DetailWeight));
	const FVector2f Local = GoTWindField::SampleLocalWind(P, FieldSnapshot);
	float Speed, Angle;
	return GoTWindNoise::ComposeWind(Frame.Direction, Force, Local, Frame.VorticleForceScale, Speed, Angle);
}

void UGoTWindSubsystem::Tick(float DeltaTime)
{
	const float Dt = FMath::IsFinite(DeltaTime) && DeltaTime > 0.f ? DeltaTime : 0.f;
	RealTime += Dt;
	FindController();
	Frame.CapturePrevious();
	UpdateWindState(Dt);
	UWorld* World = GetWorld();
	if (World && World->IsGameWorld())
	{
		UpdateInteraction();
	}
	else
	{
		bInteractActive = false;
		FieldSnapshot.bEnabled = false;
	}
	Frame.FieldCenter = InteractCenter;
	Frame.FieldSize = GetDefault<UGoTWindSettings>()->InteractionWorldSizeCm;
	Frame.bFieldEnabled = bInteractActive && Target != nullptr;
	Frame.FieldResource = Target ? Target->GameThread_GetRenderTargetResource() : nullptr;
	Frame.FieldResourcePrev = PreviousTarget ? PreviousTarget->GameThread_GetRenderTargetResource() : nullptr;
	if (!bHasWindState)
	{
		Frame.CapturePrevious();
		Frame.bFieldEnabledPrev = false; // 全局首帧复制当前；局部前帧无效，两 RT 已清零。
		bHasWindState = true;
	}
	Frame.bFieldEnabledPrev = Frame.bFieldEnabledPrev && PreviousTarget != nullptr;
	WriteCollection();
	if (World && World->Scene)
	{
		GoTWindRender::SetFrame_GameThread(World->Scene, Frame);
	}

	AGoTWindController* C = Controller.Get();
	WriteDebugParams(C);
	if (C)
	{
		DrawDebug(C);
	}
}

void UGoTWindSubsystem::UpdateWindState(float Dt)
{
	const FGoTWindParams& P = GetParams();
	const float WindDt = P.bFreeze ? 0.f : Dt * P.TimeScale;
	WindTime += WindDt;
	CurrentYaw = P.WindYawDegrees;
	const float Yaw = FMath::DegreesToRadians(CurrentYaw);
	WindDirection = FVector2f(FMath::Cos(Yaw), FMath::Sin(Yaw));

	// [适配] 主层按独立传播速度积分；捕获样本的基础风力与传播速度数值曾相同。
	FVector4f N = Frame.Noise;
	N.X = GoTWind::Wrap256(N.X - WindDirection.X * P.GustTravelSpeedCmPerSec * P.GustNoiseScale * WindDt);
	N.Y = GoTWind::Wrap256(N.Y - WindDirection.Y * P.GustTravelSpeedCmPerSec * P.GustNoiseScale * WindDt);
	N.Z = GoTWind::Wrap256(N.Z + P.GustEvolvePerSec * WindDt);
	N.W = P.GustNoiseScale;
	Frame.Noise = N;
	Frame.Shape = FVector4f(P.WindSpeedCmPerSec, P.GustGain, P.GustNoiseMul, P.GustNoiseAdd);
	Frame.Direction = WindDirection;
	// [适配] 细节层按自己的频率和独立传播速度积分；z 共享演化速度但使用不同种子。
	FVector4f Detail = Frame.DetailNoise;
	Detail.X = GoTWind::Wrap256(Detail.X - WindDirection.X * P.DetailTravelSpeedCmPerSec * P.DetailNoiseScale * WindDt);
	Detail.Y = GoTWind::Wrap256(Detail.Y - WindDirection.Y * P.DetailTravelSpeedCmPerSec * P.DetailNoiseScale * WindDt);
	Detail.Z = GoTWind::Wrap256(N.Z + 17.f);
	Detail.W = P.DetailNoiseScale;
	Frame.DetailNoise = Detail;
	Frame.DetailStrength = P.DetailStrength;
	Frame.GrassFlutterStrength = P.GrassFlutterStrength;
	// Flutter clock: sin(clock * 22 * kind freq) repeats every 2 pi / 22, wrap after 1000 periods.
	const float ClockPeriod = 1000.f * UE_TWO_PI / 22.f;
	const float NewClock = GoTWind::Wrap(Frame.Clock + P.WindClockPerSec * WindDt, ClockPeriod);
	// 保留 CapturePrevious 保存的真实前帧 clock，不因周期等价改写历史。
	Frame.Clock = NewClock;
	Frame.GustJitterCm = P.GustJitterCm;
	Frame.VorticleForceScale = P.VorticleForceScale;
	const FLinearColor PampasPack = P.Pampas.Pack(), TreePack = P.Trees.Pack();
	Frame.Pampas = FVector4f(PampasPack.R, PampasPack.G, PampasPack.B, PampasPack.A);
	Frame.Tree = FVector4f(TreePack.R, TreePack.G, TreePack.B, TreePack.A);
	Frame.Response = FVector4f(P.GrassFlutterStrength, P.Pampas.FlutterStrength, P.Trees.FlutterStrength, P.DetailStrength);
	Frame.ConsumerPush = FVector4f(FMath::DegreesToRadians(P.Pampas.PushDegrees), FMath::DegreesToRadians(P.Trees.PushDegrees), 0.f, 0.f);
	Frame.DisplacementScale = P.DisplacementScale;
	Frame.CameraPush = FVector4f(P.CameraPushStrength, P.CameraPushExponent, P.CameraPushFalloff, 0.f);
	Frame.CameraPushZ = FVector2f(P.CameraPushZBelow, P.CameraPushZAbove);

	if (const AGoTWindController* DC = Controller.Get())
	{
		// Heatmap stripes travel downwind at the wind speed (direction + front speed).
		StripePhase = GoTWind::Wrap(StripePhase + P.GustTravelSpeedCmPerSec * WindDt, FMath::Max(DC->HeatmapStripeSpacingCm, 1.f));
	}
	if (AGoTWindController* C = Controller.Get())
	{
		C->ShowDirection(CurrentYaw);
	}
}

void UGoTWindSubsystem::WriteCollection()
{
	if (!Collection || !GetWorld())
	{
		return;
	}
	UMaterialParameterCollectionInstance* Inst = GetWorld()->GetParameterCollectionInstance(Collection);
	if (!Inst)
	{
		return;
	}
	auto Pair = [Inst](FName Current, FName Previous, const FVector4f& C, const FVector4f& V)
	{
		Inst->SetVectorParameterValue(Current, FLinearColor(C.X, C.Y, C.Z, C.W));
		Inst->SetVectorParameterValue(Previous, FLinearColor(V.X, V.Y, V.Z, V.W));
	};
	Pair(GoTWind::WindDir, GoTWind::WindDirPrev, FVector4f(Frame.Direction.X, Frame.Direction.Y, Frame.Shape.X, Frame.VorticleForceScale),
		FVector4f(Frame.DirectionPrev.X, Frame.DirectionPrev.Y, Frame.ShapePrev.X, Frame.VorticleForceScalePrev));
	Pair(GoTWind::GustNoise, GoTWind::GustNoisePrev, Frame.Noise, Frame.NoisePrev);
	Pair(GoTWind::GustShape, GoTWind::GustShapePrev, Frame.Shape, Frame.ShapePrev);
	Pair(GoTWind::WindDetailNoise, GoTWind::WindDetailNoisePrev, Frame.DetailNoise, Frame.DetailNoisePrev);
	Pair(GoTWind::WindResponse, GoTWind::WindResponsePrev, Frame.Response, Frame.ResponsePrev);
	Pair(GoTWind::WindTime, GoTWind::WindTimePrev, FVector4f(Frame.Clock, 0, 0, 0), FVector4f(Frame.ClockPrev, 0, 0, 0));
	Pair(GoTWind::Interact, GoTWind::InteractPrev,
		FVector4f(Frame.FieldCenter.X, Frame.FieldCenter.Y, 1.f / Frame.FieldSize, Frame.bFieldEnabled ? 1.f : 0.f),
		FVector4f(Frame.FieldCenterPrev.X, Frame.FieldCenterPrev.Y, 1.f / Frame.FieldSizePrev, Frame.bFieldEnabledPrev ? 1.f : 0.f));
	Pair(GoTWind::Pampas, GoTWind::PampasPrev, Frame.Pampas, Frame.PampasPrev);
	Pair(GoTWind::Tree, GoTWind::TreePrev, Frame.Tree, Frame.TreePrev);
	Pair(GoTWind::ConsumerPush, GoTWind::ConsumerPushPrev, Frame.ConsumerPush, Frame.ConsumerPushPrev);
}

void UGoTWindSubsystem::WriteDebugParams(const AGoTWindController* C)
{
	if (!Collection || !GetWorld())
	{
		return;
	}
	if (UMaterialParameterCollectionInstance* Inst = GetWorld()->GetParameterCollectionInstance(Collection))
	{
		const bool bOn = C && C->bShowHeatmap;
		const float Mode = !bOn ? 0.f : float(uint8(C->HeatmapStyle) + 1);
		Inst->SetVectorParameterValue(GoTWind::WindDebug, FLinearColor(Mode, C ? C->HeatmapOpacity : 0.f,
			C && uint8(C->HeatmapStyle) < 2 ? C->HeatmapStripeSpacingCm : 0.f, StripePhase));
	}
}

FVector UGoTWindSubsystem::DebugFocus(const AGoTWindController* C) const
{
	UWorld* World = GetWorld();
	if (World->IsGameWorld())
	{
		if (const APawn* Pawn = UGameplayStatics::GetPlayerPawn(World, 0))
		{
			return Pawn->GetActorLocation();
		}
	}
	if (World->ViewLocationsRenderedLastFrame.Num() > 0)
	{
		return World->ViewLocationsRenderedLastFrame[0];
	}
	return C->GetActorLocation();
}

float UGoTWindSubsystem::GroundZ(const FVector2f& P, float FallbackZ)
{
	const float Cell = FMath::Max(GroundCacheSpacing, 50.f);
	const FIntPoint Key(FMath::RoundToInt(P.X / Cell), FMath::RoundToInt(P.Y / Cell));
	if (const float* Z = GroundCache.Find(Key))
	{
		return *Z;
	}
	float Z = FallbackZ;
	FHitResult Hit;
	FCollisionQueryParams Query(SCENE_QUERY_STAT(GoTWindDebug), false);
	const FVector2f Snapped(Key.X * Cell, Key.Y * Cell);
	if (GetWorld()->LineTraceSingleByChannel(Hit, FVector(Snapped.X, Snapped.Y, 40000.f), FVector(Snapped.X, Snapped.Y, -40000.f), ECC_WorldStatic, Query))
	{
		Z = Hit.ImpactPoint.Z;
	}
	if (GroundCache.Num() > 200000)
	{
		GroundCache.Reset();
	}
	GroundCache.Add(Key, Z);
	return Z;
}

void UGoTWindSubsystem::DrawDebug(AGoTWindController* C)
{
	const FVector Focus = DebugFocus(C);
	const float Spacing = C->DebugSpacingCm * 0.5f;
	if (!FMath::IsNearlyEqual(Spacing, GroundCacheSpacing))
	{
		GroundCache.Reset();
		GroundCacheSpacing = Spacing;
	}
	if (C->bShowArrows)
	{
		DrawArrows(C, Focus);
	}
	if (C->bShowGustEdges)
	{
		DrawGustEdges(C, Focus);
	}
	if (C->bShowInteraction && GetWorld()->IsGameWorld())
	{
		DrawInteraction();
	}
	if (C->bShowInfoText)
	{
		const FGoTWindParams& P = GetParams();
		const FVector2f View(Focus.X, Focus.Y);
		const float Gust = GustAt(View);
		const float Force = ForceAt(View);
		const float GrassW = 0.65f * Force / 6600.f;
		const FString Text = FString::Printf(
			TEXT("WIND yaw %.0f deg  base %.0f cm/s (macro travels %.1f m/s, detail %.1f m/s)\n")
			TEXT("gust: Perlin 3D, cell %.0f m, evolve %.3f /s, gain %.2f mul %.2f add %.2f\n")
			TEXT("at view (macro): gust %.2f  force %.0f  reference grass w %.2f (kind 1)  pampas w %.2f%s"),
			CurrentYaw, P.WindSpeedCmPerSec, P.GustTravelSpeedCmPerSec / 100.f, P.DetailTravelSpeedCmPerSec / 100.f,
			1.f / FMath::Max(P.GustNoiseScale, 1e-6f) / 100.f, P.GustEvolvePerSec, P.GustGain, P.GustNoiseMul, P.GustNoiseAdd,
			Gust, Force, GrassW, P.Pampas.WindCoefficient * Force / 6600.f, P.bFreeze ? TEXT("   [FROZEN]") : TEXT(""));
		C->ShowInfo(Text, Focus);
	}
	else
	{
		C->ShowInfo(FString(), Focus);
	}
}

void UGoTWindSubsystem::DrawArrows(const AGoTWindController* C, const FVector& Focus)
{
	UWorld* World = GetWorld();
	const int32 N = C->DebugGridCount;
	const float S = C->DebugSpacingCm;
	const float Half = 0.5f * (N - 1) * S;
	const float Ox = FMath::GridSnap(float(Focus.X), S) - Half;
	const float Oy = FMath::GridSnap(float(Focus.Y), S) - Half;
	for (int32 Y = 0; Y < N; ++Y)
	{
		for (int32 X = 0; X < N; ++X)
		{
			const FVector2f Pt(Ox + X * S, Oy + Y * S);
			const float Z = GroundZ(Pt, Focus.Z) + C->DebugHeightCm;
			float Gust = GustAt(Pt);
			FVector2f Wind = Frame.Direction * ForceAt(Pt);
			if (C->HeatmapStyle == EGoTHeatmapStyle::DetailNoise)
			{
				const float DetailNoiseValue = GoTWindNoise::Perlin3D(FVector3f(Pt.X * Frame.DetailNoise.W + Frame.DetailNoise.X,
					Pt.Y * Frame.DetailNoise.W + Frame.DetailNoise.Y, Frame.DetailNoise.Z));
				Wind = Frame.Direction * (Frame.Shape.X * Frame.DetailStrength * DetailNoiseValue);
				Gust = FMath::Clamp(0.5f + 0.5f * DetailNoiseValue, 0.f, 1.f);
			}
			else if (C->HeatmapStyle == EGoTHeatmapStyle::CombinedWind || C->HeatmapStyle == EGoTHeatmapStyle::BladeResponse)
			{
				Wind = CombinedAt(Pt, 1.f);
				Gust = FMath::Clamp(Wind.Size() / FMath::Max(Frame.Shape.X * (1.f + Frame.Shape.Y + Frame.DetailStrength), 1.f), 0.f, 1.f);
			}
			const FVector2f Tip = Pt + Wind * (0.01f * C->DebugArrowScale);
			const FColor Color = FLinearColor::LerpUsingHSV(FLinearColor(0.1f, 0.35f, 1.f), FLinearColor(1.f, 0.1f, 0.05f), Gust).ToFColor(true);
			if (Wind.SizeSquared() <= 1e-8f) DrawDebugPoint(World, FVector(Pt.X, Pt.Y, Z), 4.f, Color, false, -1.f);
			else DrawDebugDirectionalArrow(World, FVector(Pt.X, Pt.Y, Z), FVector(Tip.X, Tip.Y, Z), 20.f, Color, false, -1.f, SDPG_World, 2.f);
		}
	}
}

void UGoTWindSubsystem::DrawGustEdges(const AGoTWindController* C, const FVector& Focus)
{
	// Marching squares on the gust amount: cyan = 0.25, red = 0.75.
	UWorld* World = GetWorld();
	const int32 N = C->DebugGridCount * 2 + 1;
	const float S = C->DebugSpacingCm * 0.5f;
	const float Half = 0.5f * (N - 1) * S;
	const float Ox = FMath::GridSnap(float(Focus.X), S) - Half;
	const float Oy = FMath::GridSnap(float(Focus.Y), S) - Half;
	TArray<float> Raw;
	TArray<float> Z;
	Raw.SetNumUninitialized(N * N);
	Z.SetNumUninitialized(N * N);
	for (int32 Y = 0; Y < N; ++Y)
	{
		for (int32 X = 0; X < N; ++X)
		{
			const FVector2f Pt(Ox + X * S, Oy + Y * S);
			Raw[Y * N + X] = GustAt(Pt);
			Z[Y * N + X] = GroundZ(Pt, Focus.Z) + C->DebugHeightCm;
		}
	}
	auto Contour = [&](float Level, const FColor& Color)
	{
		auto Corner = [&](int32 X, int32 Y) { return FVector(Ox + X * S, Oy + Y * S, Z[Y * N + X]); };
		auto Cross = [&](int32 Xa, int32 Ya, int32 Xb, int32 Yb)
		{
			const float A = Raw[Ya * N + Xa] - Level;
			const float B = Raw[Yb * N + Xb] - Level;
			const float T = A / (A - B);
			return FMath::Lerp(Corner(Xa, Ya), Corner(Xb, Yb), T);
		};
		for (int32 Y = 0; Y < N - 1; ++Y)
		{
			for (int32 X = 0; X < N - 1; ++X)
			{
				TArray<FVector, TInlineAllocator<4>> Pts;
				const bool b00 = Raw[Y * N + X] > Level, b10 = Raw[Y * N + X + 1] > Level;
				const bool b01 = Raw[(Y + 1) * N + X] > Level, b11 = Raw[(Y + 1) * N + X + 1] > Level;
				if (b00 != b10) Pts.Add(Cross(X, Y, X + 1, Y));
				if (b10 != b11) Pts.Add(Cross(X + 1, Y, X + 1, Y + 1));
				if (b11 != b01) Pts.Add(Cross(X + 1, Y + 1, X, Y + 1));
				if (b01 != b00) Pts.Add(Cross(X, Y + 1, X, Y));
				for (int32 i = 0; i + 1 < Pts.Num(); i += 2)
				{
					DrawDebugLine(World, Pts[i], Pts[i + 1], Color, false, -1.f, SDPG_World, 6.f);
				}
			}
		}
	};
	Contour(0.25f, FColor(40, 230, 255));
	Contour(0.75f, FColor(255, 40, 30));
}

void UGoTWindSubsystem::DrawInteraction() const
{
	UWorld* World = GetWorld();
	const FGoTWindParams& P = GetParams();
	const float Size = GetDefault<UGoTWindSettings>()->InteractionWorldSizeCm;
	const APawn* Pawn = UGameplayStatics::GetPlayerPawn(World, 0);
	const float Zp = Pawn ? Pawn->GetActorLocation().Z : 0.f;
	const FVector Center(InteractCenter.X, InteractCenter.Y, Zp);
	DrawDebugBox(World, Center, FVector(Size * 0.5f, Size * 0.5f, 50.f), FColor(255, 0, 255), false, -1.f, SDPG_World, 8.f);
	for (const FInteractorState& I : Interactors)
	{
		const UGoTWindInteractorComponent* Comp = I.Component.Get();
		const float R = Comp ? Comp->RadiusCm : P.PlayerRadiusCm;
		DrawDebugCircle(World, FVector(I.LastPosition.X, I.LastPosition.Y, Zp - 80.f), R, 32, FColor(255, 0, 255), false, -1.f, SDPG_World, 4.f,
			FVector(1, 0, 0), FVector(0, 1, 0), false);
	}
	const float Now = float(RealTime);
	for (const FTrailPoint& T : Trail)
	{
		const float Age = Now - T.BirthTime;
		const float Wave = FMath::Exp(-P.WaveDecay * Age) * FMath::Cos(P.WaveFrequency * Age);
		const FColor Color = Wave >= 0.f ? FColor(40, 255, 60) : FColor(255, 40, 40);   // official debug: green push, red swing back
		DrawDebugPoint(World, FVector(T.Position.X, T.Position.Y, Zp - 60.f), 4.f + 14.f * FMath::Abs(Wave), Color, false, -1.f, SDPG_World);
	}
}

void UGoTWindSubsystem::RegisterInteractor(UGoTWindInteractorComponent* Component)
{
	if (Component)
	{
		RegisteredComponents.AddUnique(Component);
	}
}

void UGoTWindSubsystem::UnregisterInteractor(UGoTWindInteractorComponent* Component)
{
	RegisteredComponents.Remove(Component);
}

void UGoTWindSubsystem::AddVorticle(const UObject* WorldContextObject, FVector Location, float RadiusCm, FVector WindCmPerSec, float LifetimeSeconds)
{
	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull) : nullptr;
	UGoTWindSubsystem* Self = World ? World->GetSubsystem<UGoTWindSubsystem>() : nullptr;
	if (!Self)
	{
		return;
	}
	if (!FMath::IsFinite(Location.X) || !FMath::IsFinite(Location.Y) || !FMath::IsFinite(Location.Z)
		|| !FMath::IsFinite(WindCmPerSec.X) || !FMath::IsFinite(WindCmPerSec.Y) || !FMath::IsFinite(WindCmPerSec.Z)
		|| !FMath::IsFinite(RadiusCm) || !FMath::IsFinite(LifetimeSeconds))
	{
		UE_LOG(LogTemp, Error, TEXT("GoTWind: 局部风位置、半径、速度和寿命必须有限。"));
		return;
	}
	FVorticle V;
	V.Position = FVector2f(Location.X, Location.Y);
	V.Wind = FVector2f(WindCmPerSec.X, WindCmPerSec.Y);
	V.Radius = FMath::Max(RadiusCm, 10.f);
	V.BirthTime = float(Self->RealTime);
	V.Lifetime = FMath::Max(LifetimeSeconds, 0.05f);
	Self->Vorticles.Add(V);
}

FVector UGoTWindSubsystem::GetWindAtLocation(const UObject* WorldContextObject, FVector Location, float& OutGust)
{
	OutGust = 0.f;
	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull) : nullptr;
	const UGoTWindSubsystem* Self = World ? World->GetSubsystem<UGoTWindSubsystem>() : nullptr;
	if (!Self)
	{
		return FVector::ZeroVector;
	}
	const FVector2f P(Location.X, Location.Y);
	OutGust = Self->GustAt(P);
	return FVector(Self->WindDirection.X, Self->WindDirection.Y, 0.f) * Self->ForceAt(P);
}

FVector UGoTWindSubsystem::GetCombinedWindAtLocation(const UObject* WorldContextObject, FVector Location, float DetailWeight)
{
	UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::LogAndReturnNull) : nullptr;
	const UGoTWindSubsystem* Self = World ? World->GetSubsystem<UGoTWindSubsystem>() : nullptr;
	if (!Self || !FMath::IsFinite(Location.X) || !FMath::IsFinite(Location.Y) || !FMath::IsFinite(DetailWeight)) return FVector::ZeroVector;
	const FVector2f Wind = Self->CombinedAt(FVector2f(Location.X, Location.Y), DetailWeight);
	return FVector(Wind.X, Wind.Y, 0.f);
}

void UGoTWindSubsystem::GatherInteractors()
{
	const UGoTWindSettings* S = GetDefault<UGoTWindSettings>();
	RegisteredComponents.RemoveAll([](const TWeakObjectPtr<UGoTWindInteractorComponent>& C) { return !C.IsValid(); });
	Interactors.RemoveAll([](const FInteractorState& I) { return !I.Actor.IsValid(); });

	auto Track = [this](AActor* Actor, UGoTWindInteractorComponent* Component)
	{
		for (FInteractorState& I : Interactors)
		{
			if (I.Actor.Get() == Actor)
			{
				I.Component = Component;
				return;
			}
		}
		FInteractorState New;
		New.Actor = Actor;
		New.Component = Component;
		Interactors.Add(New);
	};

	for (const TWeakObjectPtr<UGoTWindInteractorComponent>& C : RegisteredComponents)
	{
		if (C->bInteractionEnabled && C->GetOwner())
		{
			Track(C->GetOwner(), C.Get());
		}
	}
	if (S->bAutoRegisterPlayerPawn)
	{
		if (APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0))
		{
			if (!Pawn->FindComponentByClass<UGoTWindInteractorComponent>())
			{
				Track(Pawn, nullptr);
			}
		}
	}
}

void UGoTWindSubsystem::UpdateInteraction()
{
	const FGoTWindParams& P = GetParams();
	const float Now = float(RealTime);
	GatherInteractors();

	// Trail particles: emitted every TrailSpacing along each interactor's path [官方 W3: particle driven].
	for (FInteractorState& I : Interactors)
	{
		const AActor* Actor = I.Actor.Get();
		const UGoTWindInteractorComponent* C = I.Component.Get();
		const FVector Loc = Actor->GetActorLocation() + (C ? Actor->GetActorRotation().RotateVector(C->LocalOffset) : FVector::ZeroVector);
		const FVector2f Pos(Loc.X, Loc.Y);
		if (!I.bHasStamp)
		{
			I.LastStamp = I.LastPosition = Pos;
			I.bHasStamp = true;
		}
		I.LastPosition = Pos;
		const float Spacing = P.TrailSpacingCm;
		float Travel = FVector2f::Distance(Pos, I.LastStamp);
		while (Travel >= Spacing)
		{
			const FVector2f StepDir = (Pos - I.LastStamp).GetSafeNormal();
			I.LastStamp += StepDir * Spacing;
			FTrailPoint T;
			T.Position = I.LastStamp;
			T.BirthTime = Now;
			T.Radius = C ? C->RadiusCm : P.PlayerRadiusCm;
			T.Strength = C ? C->Strength : P.PlayerStrength;
			Trail.Add(T);
			Travel -= Spacing;
		}
	}
	Trail.RemoveAll([&](const FTrailPoint& T) { return Now - T.BirthTime > P.TrailLifetimeSeconds; });
	Vorticles.RemoveAll([&](const FVorticle& V) { return Now - V.BirthTime > V.Lifetime; });
	if (Trail.Num() > 4096)
	{
		Trail.RemoveAt(0, Trail.Num() - 4096);
	}

	// Field centred on the player pawn (camera when there is none), snapped to texels so it does not swim.
	FVector CenterWorld = FVector::ZeroVector;
	if (const APawn* Pawn = UGameplayStatics::GetPlayerPawn(GetWorld(), 0))
	{
		CenterWorld = Pawn->GetActorLocation();
	}
	else if (const APlayerCameraManager* Cam = UGameplayStatics::GetPlayerCameraManager(GetWorld(), 0))
	{
		CenterWorld = Cam->GetCameraLocation();
	}
	const float Size = GetDefault<UGoTWindSettings>()->InteractionWorldSizeCm;
	const int32 Res = Target ? FMath::Max(Target->SizeX, 1) : 256;
	const float Texel = Size / Res;
	InteractCenter = FVector2f(FMath::FloorToFloat(CenterWorld.X / Texel) * Texel, FMath::FloorToFloat(CenterWorld.Y / Texel) * Texel);
	bInteractActive = Target != nullptr;
	if (!Target)
	{
		return;
	}

	TArray<GoTWindField::FParticle> Particles;
	Particles.Reserve(Trail.Num() + Interactors.Num());
	for (const FTrailPoint& T : Trail)
	{
		GoTWindField::FParticle& Pa = Particles.AddDefaulted_GetRef();
		Pa.Position = T.Position;
		Pa.Age = Now - T.BirthTime;
		Pa.Radius = T.Radius;
		// overlapping particles along a straight trail sum to ~1: integral of (1 - x^2)^2 over the radius = 16/15
		Pa.Strength = T.Strength * P.TrailSpacingCm / (1.0667f * T.Radius);
	}
	TArray<GoTWindField::FVorticle> GpuVorticles;
	for (const FInteractorState& I : Interactors)
	{
		// live footprint: full push wherever an interactor stands right now (age 0, also when it stops)
		const UGoTWindInteractorComponent* C = I.Component.Get();
		GoTWindField::FParticle& Pa = Particles.AddDefaulted_GetRef();
		Pa.Position = I.LastPosition;
		Pa.Age = 0.f;
		Pa.Radius = C ? C->RadiusCm : P.PlayerRadiusCm;
		Pa.Strength = C ? C->Strength : P.PlayerStrength;
		if (P.PlayerVorticleCmPerSec > 0.f && !C)
		{
			// outward wind around the player: approximated by four vorticles pushing away from the centre
			for (int32 k = 0; k < 4; ++k)
			{
				const float A = k * UE_HALF_PI;
				const FVector2f D(FMath::Cos(A), FMath::Sin(A));
				GoTWindField::FVorticle& V = GpuVorticles.AddDefaulted_GetRef();
				V.Position = I.LastPosition + D * (P.PlayerVorticleRadiusCm * 0.5f);
				V.Radius = P.PlayerVorticleRadiusCm * 0.6f;
				V.Fade = 1.f;
				V.Wind = D * P.PlayerVorticleCmPerSec;
			}
		}
	}
	for (const FVorticle& V : Vorticles)
	{
		const float T = (Now - V.BirthTime) / V.Lifetime;
		GoTWindField::FVorticle& G = GpuVorticles.AddDefaulted_GetRef();
		G.Position = V.Position;
		G.Radius = V.Radius;
		G.Fade = FMath::Sin(UE_PI * FMath::Clamp(T, 0.f, 1.f));
		G.Wind = V.Wind;
	}
	FieldSnapshot.Center = InteractCenter;
	FieldSnapshot.Size = Size;
	FieldSnapshot.Resolution = Res;
	FieldSnapshot.bEnabled = bInteractActive;
	FieldSnapshot.WaveDecay = P.WaveDecay;
	FieldSnapshot.WaveFrequency = P.WaveFrequency;
	FieldSnapshot.Particles = MoveTemp(Particles);
	FieldSnapshot.Vorticles = MoveTemp(GpuVorticles);
	GoTWindField::Update_GameThread(Target, PreviousTarget, FieldSnapshot, bClearFieldHistory);
	bClearFieldHistory = false;
}
