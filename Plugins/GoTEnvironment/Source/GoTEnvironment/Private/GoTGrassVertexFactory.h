#pragma once

#include "CoreMinimal.h"
#include "RenderResource.h"
#include "SceneManagement.h"
#include "ShaderParameterMacros.h"
#include "UniformBuffer.h"
#include "VertexFactory.h"

/** Per batch (view x near/far list) parameters of the grass vertex factory ("GoTGrassVF" in GoTGrassVertexFactory.ush). */
BEGIN_GLOBAL_SHADER_PARAMETER_STRUCT(FGoTGrassVFParameters, )
	SHADER_PARAMETER_SRV(StructuredBuffer<float4>, Blades)
	SHADER_PARAMETER_SRV(Buffer<uint>, Counters)
	SHADER_PARAMETER_SRV(StructuredBuffer<float>, Kinds)
	SHADER_PARAMETER_SRV(Buffer<uint>, ClumpNormals) // [适配] 同叶索引的 oct16x2 共同簇法线，只用于照明
	SHADER_PARAMETER_SRV(Buffer<float4>, WindMotion) // prevFacing.xy、当前/前帧局部风偏转角
	SHADER_PARAMETER_TEXTURE(Texture2D<float4>, DispTexture)
	SHADER_PARAMETER_TEXTURE(Texture2D<float4>, DispTexturePrev)
	SHADER_PARAMETER_SAMPLER(SamplerState, DispSampler)
	SHADER_PARAMETER(FVector3f, Origin)
	SHADER_PARAMETER(uint32, Capacity)
	SHADER_PARAMETER(FUintVector4, Layout)          // verts per blade, blades per instance, counter index, lod (0 near, 1 far)
	SHADER_PARAMETER(FVector4f, WindTime)           // clock, previous clock, base force, previous base force
	SHADER_PARAMETER(FVector2f, FlutterStrength)    // [适配] 当前/前帧逐叶颤动振幅倍数
	SHADER_PARAMETER(FVector4f, WindDirAndDisp)     // wind dir xy, displacement scale, displacement enabled
	SHADER_PARAMETER(FVector4f, WindDirAndDispPrev)
	SHADER_PARAMETER(FVector4f, LodMorph)           // mul, add, dither
	SHADER_PARAMETER(FVector4f, Grazing)            // mul, add, dither
	SHADER_PARAMETER(FVector3f, ClumpNormalBlend)   // 起始距离 cm、结束距离 cm、最大权重
	SHADER_PARAMETER(FVector4f, DispCenterSize)     // field centre relative to Origin xy, 1 / size, resolution
	SHADER_PARAMETER(FVector4f, DispCenterSizePrev)
	SHADER_PARAMETER(FVector4f, Push)               // camera push strength, exponent, falloff
	SHADER_PARAMETER(FVector4f, PushPrev)
	SHADER_PARAMETER(FVector2f, PushZ)
	SHADER_PARAMETER(FVector2f, PushZPrev)
END_GLOBAL_SHADER_PARAMETER_STRUCT()

typedef TUniformBufferRef<FGoTGrassVFParameters> FGoTGrassVFBufferRef;

/** Mesh batch user data: the per-batch uniform buffer. */
struct FGoTGrassBatchUserData : public FOneFrameResource
{
	FGoTGrassVFBufferRef UniformBuffer;
};

/** Triangle list for one draw instance: Blades x (Verts - 2) triangles of a per-blade strip (captured topology). */
class FGoTGrassIndexBuffer : public FIndexBuffer
{
public:
	FGoTGrassIndexBuffer(uint32 InVertsPerBlade, uint32 InBladesPerInstance)
		: VertsPerBlade(InVertsPerBlade), BladesPerInstance(InBladesPerInstance) {}

	virtual void InitRHI(FRHICommandListBase& RHICmdList) override;
	uint32 GetNumIndices() const { return BladesPerInstance * (VertsPerBlade - 2) * 3; }

	const uint32 VertsPerBlade;
	const uint32 BladesPerInstance;
};

/** No vertex streams: SV_VertexID / SV_InstanceID index into the blade buffer written by GoTGrassGen.usf. */
class FGoTGrassVertexFactory : public FVertexFactory
{
	DECLARE_VERTEX_FACTORY_TYPE(FGoTGrassVertexFactory);

public:
	explicit FGoTGrassVertexFactory(ERHIFeatureLevel::Type InFeatureLevel) : FVertexFactory(InFeatureLevel) {}

	virtual void InitRHI(FRHICommandListBase& RHICmdList) override;

	static bool ShouldCompilePermutation(const FVertexFactoryShaderPermutationParameters& Parameters);
	static void ModifyCompilationEnvironment(const FVertexFactoryShaderPermutationParameters& Parameters, FShaderCompilerEnvironment& OutEnvironment);
	static void ValidateCompiledResult(const FVertexFactoryType* Type, EShaderPlatform Platform, const FShaderParameterMap& ParameterMap, TArray<FString>& OutErrors) {}
};
