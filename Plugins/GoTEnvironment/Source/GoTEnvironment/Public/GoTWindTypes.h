#pragma once

#include "CoreMinimal.h"
#include "RHIResources.h"
#include "GoTWindTypes.generated.h"

/**
 * 建模植被通过 MF_GoTWind 读取共享 MPC；草叶仍从草种表读取各自系数。
 * [截帧] w = WindCoefficient * force / 6600；颤动强度单独写入 WindResponse。
 * [适配] 芒草采用圆弧中心线与旋转横截面，BendDegrees 控制总弯角，法线使用变形的逆转置。
 * 树保留角度随高度平方增长的根部旋转。现有网格缺少原版枝级枢轴，二者都不是完整原版植被实现。
 */
USTRUCT(BlueprintType)
struct GOTENVIRONMENT_API FGoTWindConsumer
{
	GENERATED_BODY()

	FGoTWindConsumer() = default;
	FGoTWindConsumer(float InHeight, float InCoef, float InBend, float InFlutterFreq, float InPush, float InFlutterStrength)
		: HeightCm(InHeight), WindCoefficient(InCoef), BendDegrees(InBend), FlutterFrequency(InFlutterFreq),
		  FlutterStrength(InFlutterStrength), PushDegrees(InPush) {}

	/** 响应高度（cm）：圆弧芒草按实例 Z 缩放，旧树模式使用世界高度。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "1", UIMin = "10", UIMax = "2000"))
	float HeightCm = 120.f;

	/** Like grass kind[200]: w = coefficient * force / 6600 (calm force 1500 -> 0.23 at coefficient 1). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "2"))
	float WindCoefficient = 0.65f;

	/** 响应值为 1 时的弯角（度）；芒草是圆弧总转角，树是根部旋转角。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "90"))
	float BendDegrees = 40.f;

	/** Like grass kind[208]: flutter phase speed = clock * 22 * this. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "4"))
	float FlutterFrequency = 1.f;

	/** [适配] 逐实例正弦颤动的振幅倍数，无单位。0 关闭颤动，1 恢复原振幅；不影响阵风弯曲。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "1", DisplayName = "颤动强度"))
	float FlutterStrength = 0.2f;

	/** Rotation (degrees) at full interaction displacement (player walking through). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "90"))
	float PushDegrees = 45.f;

	FLinearColor Pack() const { return FLinearColor(HeightCm, WindCoefficient, FMath::DegreesToRadians(BendDegrees), FlutterFrequency); }
};

/**
 * Every tunable of the unified wind. Edited live on AGoTWindController (Details panel, editor or PIE);
 * UGoTWindSettings holds the project fallback used when the level has no controller.
 *
 * Official model (GDC 2021 "Blowing from the West" + grass talk, captured frame 02):
 *   wind force  = base + base * gain * saturate((perlin3D(xy * scale + offset, z) * 0.5 + 0.5) * mul + add)   [截帧]
 *   offset      -= direction * layerTravelSpeed * scale * dt, z += evolve * dt [适配: 各层独立速度，捕获样本数值曾相同]
 *   grass blade = Bezier control points moved by w = kind[200] * force / 6600 + flutter sine                 [截帧]
 *   interaction = trail particles x damped wave written to a 100 m displacement field                     [官方 W3 + 截帧 VS]
 *   vorticles   = local wind sources summed by every consumer                                             [官方 W1]
 */
USTRUCT(BlueprintType)
struct GOTENVIRONMENT_API FGoTWindParams
{
	GENERATED_BODY()

	// ---------------- Global ----------------
	/** 冻结主阵风、细节风和颤动时钟；交互缓冲仍按自己的生命期更新。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "1 Global")
	bool bFreeze = false;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "1 Global", meta = (ClampMin = "0", UIMin = "0", UIMax = "4"))
	float TimeScale = 1.f;

	// ---------------- Wind vector ----------------
	/** Direction the wind blows towards (UE yaw, degrees). 200 matches the pampas lean placed by PCG. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "2 Wind", meta = (UIMin = "0", UIMax = "360"))
	float WindYawDegrees = 200.f;

	/** 基础风力（cm/s），只控制响应强度；两层传播速度独立设置。[截帧] 默认值 1500。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "2 Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "4000"))
	float WindSpeedCmPerSec = 1500.f;

	/** [适配] 主阵风图案沿作者风向传播的速度（cm/s）；0 停止平移，不关闭风力。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "2 Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "4000", DisplayName = "主阵风传播速度 (cm/s)"))
	float GustTravelSpeedCmPerSec = 1500.f;

	/** [适配] 细节图案传播速度（cm/s），与主层独立；0 停止细节平移。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "2 Wind", meta = (ClampMin = "0", UIMin = "0", UIMax = "4000", DisplayName = "细节风传播速度 (cm/s)"))
	float DetailTravelSpeedCmPerSec = 1500.f;

	// ---------------- Gust noise (3D Perlin) ----------------
	/** [截帧] Noise frequency (1/cm). 0.0004 = one noise cell per 25 m. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0.00001", UIMin = "0.0001", UIMax = "0.002"))
	float GustNoiseScale = 0.0004f;

	/** [推断] Noise z (shape change) per second: 0.049 measured from two consecutive frames at 30 fps (~20 s per new pattern). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0", UIMin = "0", UIMax = "0.5"))
	float GustEvolvePerSec = 0.049f;

	/** [截帧] force = base * (1 + Gain * saturate(noise01 * Mul + Add)). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0", UIMin = "0", UIMax = "4"))
	float GustGain = 1.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (UIMin = "0", UIMax = "4"))
	float GustNoiseMul = 1.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (UIMin = "-2", UIMax = "2"))
	float GustNoiseAdd = 0.f;

	/** [截帧] Each blade samples the noise at its position + random * 100 cm. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0", UIMax = "500"))
	float GustJitterCm = 100.f;

	// [官方] 草地演讲 12:40 提到额外 Perlin 细节；以下尺度和有符号加法是 UE 适配，不是原版已恢复参数。
	/** [适配] 草和芒草共享细节噪声的空间频率，单位 1/cm。0.002 对应 5 m 晶格；随主风速度平移。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0.00001", UIMin = "0.0001", UIMax = "0.01", DisplayName = "细节噪声频率 (1/cm)"))
	float DetailNoiseScale = 0.002f;

	/** [适配] 细节振幅相对基础风力的比例，无单位：force = max(0, 主风 + base * strength * Perlin)。0 恢复单层主风；树不使用细节层。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "3 Gust", meta = (ClampMin = "0", UIMin = "0", UIMax = "1", DisplayName = "草地细节风强度"))
	float DetailStrength = 0.25f;

	// ---------------- Flutter ----------------
	/** [推断] Wind clock units per second (captured +0.003727 per frame at 30 fps); flutter phase = clock * 22 * kind freq. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "4 Flutter", meta = (ClampMin = "0", UIMin = "0", UIMax = "1"))
	float WindClockPerSec = 0.112f;

	/** [适配] GPU 草逐叶正弦颤动的振幅倍数，无单位。0 关闭颤动，1 恢复原振幅；不影响两层风场。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "4 Flutter", meta = (ClampMin = "0", UIMin = "0", UIMax = "1", DisplayName = "GPU 草颤动强度"))
	float GrassFlutterStrength = 0.2f;

	// ---------------- Modelled vegetation ----------------
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "5 Consumers")
	FGoTWindConsumer Pampas = FGoTWindConsumer(120.f, 0.65f, 38.f, 1.f, 50.f, 0.2f);

	/** Trees use the same rotation about the trunk base (small angles). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "5 Consumers")
	FGoTWindConsumer Trees = FGoTWindConsumer(1300.f, 0.3f, 4.f, 1.6f, 0.f, 1.f);

	// ---------------- Interaction ----------------
	/** Distance between trail particles left by an interactor. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "5", UIMin = "10", UIMax = "100"))
	float TrailSpacingCm = 30.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0.1", UIMin = "0.5", UIMax = "8"))
	float TrailLifetimeSeconds = 3.2f;

	/** [官方 W3] displacement = A e^(-Decay t) cos(Frequency t). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMin = "0", UIMax = "6"))
	float WaveDecay = 1.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMin = "0", UIMax = "20"))
	float WaveFrequency = 6.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "10", UIMin = "30", UIMax = "300"))
	float PlayerRadiusCm = 95.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMin = "0", UIMax = "3"))
	float PlayerStrength = 1.f;

	/** [截帧 VS interaction block +96 = 6.5] Displacement multiplier in the grass vertex shader. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMin = "0", UIMax = "20"))
	float DisplacementScale = 6.5f;

	/**
	 * [截帧 interaction block +100..+116] Grass is pushed away from the camera so blades do not cover the lens:
	 * push = Strength * p * (|p|^2 + 100)^Exponent * saturate(1 - |p|^4 * Falloff), p.z scaled by ZBelow / ZAbove.
	 * Captured: 70092.8, -1.5, 0, 1.5, 0.1.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMin = "0", UIMax = "200000"))
	float CameraPushStrength = 70092.8f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (UIMin = "-3", UIMax = "0"))
	float CameraPushExponent = -1.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0"))
	float CameraPushFalloff = 0.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMax = "4"))
	float CameraPushZBelow = 1.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "6 Interaction", meta = (ClampMin = "0", UIMax = "4"))
	float CameraPushZAbove = 0.1f;

	// ---------------- Vorticles ----------------
	/** Weak outward wind (cm/s) around the player so particles/grass sense it. 0 = off. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "7 Vorticles", meta = (ClampMin = "0", UIMin = "0", UIMax = "3000"))
	float PlayerVorticleCmPerSec = 0.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "7 Vorticles", meta = (ClampMin = "10", UIMin = "50", UIMax = "800"))
	float PlayerVorticleRadiusCm = 250.f;

	/** [适配] 局部风向量的共享权重，无单位；0 关闭局部风合成，主风及角色位移不受影响。 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "7 Vorticles", meta = (ClampMin = "0", UIMin = "0", UIMax = "2"))
	float VorticleForceScale = 1.f;
};

/** One frame of wind state, produced by UGoTWindSubsystem and consumed on the render thread (grass). */
struct FGoTWindFrame
{
	FVector2f Direction = FVector2f(1.f, 0.f);
	FVector2f DirectionPrev = FVector2f(1.f, 0.f);
	FVector4f Noise = FVector4f(0, 0, 0, 0.0004f);          // offset xy, z, scale
	FVector4f NoisePrev = FVector4f(0, 0, 0, 0.0004f);
	FVector4f DetailNoise = FVector4f(37.f, 91.f, 17.f, 0.002f);  // [适配] 独立位置细节层：offset xy、z、1/cm
	FVector4f DetailNoisePrev = FVector4f(37.f, 91.f, 17.f, 0.002f);
	float DetailStrength = 0.25f;
	float DetailStrengthPrev = 0.25f;
	float GrassFlutterStrength = 0.2f;
	float GrassFlutterStrengthPrev = 0.2f;
	FVector4f Shape = FVector4f(1500.f, 1.f, 1.f, 0.f);     // base, gain, mul, add
	FVector4f ShapePrev = FVector4f(1500.f, 1.f, 1.f, 0.f);
	float Clock = 0.f;
	float ClockPrev = 0.f;
	float GustJitterCm = 100.f;
	float GustJitterCmPrev = 100.f;
	float VorticleForceScale = 1.f;
	float VorticleForceScalePrev = 1.f;
	FVector2f FieldCenter = FVector2f::ZeroVector;
	FVector2f FieldCenterPrev = FVector2f::ZeroVector;
	float FieldSize = 10000.f;
	float FieldSizePrev = 10000.f;
	bool bFieldEnabled = false;
	bool bFieldEnabledPrev = false;
	float DisplacementScale = 6.5f;
	float DisplacementScalePrev = 6.5f;
	FVector4f CameraPush = FVector4f(70092.8f, -1.5f, 0.f, 0.f);   // strength, exponent, falloff, 0
	FVector2f CameraPushZ = FVector2f(1.5f, 0.1f);                 // z scale below / above the camera
	FVector4f CameraPushPrev = FVector4f(70092.8f, -1.5f, 0.f, 0.f);
	FVector2f CameraPushZPrev = FVector2f(1.5f, 0.1f);
	FVector4f Pampas = FVector4f(120.f, 0.65f, 0.663225f, 1.f), PampasPrev = Pampas;
	FVector4f Tree = FVector4f(1300.f, 0.3f, 0.0698132f, 1.6f), TreePrev = Tree;
	FVector4f Response = FVector4f(0.2f, 0.2f, 1.f, 0.25f), ResponsePrev = Response;
	FVector4f ConsumerPush = FVector4f(0.872665f, 0.f, 0.f, 0.f), ConsumerPushPrev = ConsumerPush;
	class FTextureResource* FieldResource = nullptr;
	class FTextureResource* FieldResourcePrev = nullptr;
	FTextureRHIRef FieldTexture, FieldTexturePrev; // 渲染线程解析并保留 RHI 强引用

	/** 同一处保存全部已发布输入，避免前帧材质和草帧各自采集。 */
	void CapturePrevious()
	{
		DirectionPrev = Direction;
		NoisePrev = Noise;
		ShapePrev = Shape;
		DetailNoisePrev = DetailNoise;
		DetailStrengthPrev = DetailStrength;
		GrassFlutterStrengthPrev = GrassFlutterStrength;
		ClockPrev = Clock;
		GustJitterCmPrev = GustJitterCm;
		VorticleForceScalePrev = VorticleForceScale;
		FieldCenterPrev = FieldCenter;
		FieldSizePrev = FieldSize;
		bFieldEnabledPrev = bFieldEnabled;
		DisplacementScalePrev = DisplacementScale;
		CameraPushPrev = CameraPush;
		CameraPushZPrev = CameraPushZ;
		PampasPrev = Pampas;
		TreePrev = Tree;
		ResponsePrev = Response;
		ConsumerPushPrev = ConsumerPush;
	}
};
