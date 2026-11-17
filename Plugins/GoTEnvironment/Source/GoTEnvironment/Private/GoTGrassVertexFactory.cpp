#include "GoTGrassVertexFactory.h"

#include "DataDrivenShaderPlatformInfo.h"
#include "MaterialDomain.h"
#include "MeshDrawShaderBindings.h"
#include "MeshMaterialShader.h"
#include "RHIResourceUtils.h"

IMPLEMENT_GLOBAL_SHADER_PARAMETER_STRUCT(FGoTGrassVFParameters, "GoTGrassVF");

void FGoTGrassIndexBuffer::InitRHI(FRHICommandListBase& RHICmdList)
{
	// Each blade is a strip 0..N-1 (pairs left/right, tip last), emitted as a list.
	TArray<uint16> Indices;
	Indices.Reserve(GetNumIndices());
	for (uint32 Blade = 0; Blade < BladesPerInstance; ++Blade)
	{
		const uint32 Base = Blade * VertsPerBlade;
		for (uint32 I = 0; I + 2 < VertsPerBlade; ++I)
		{
			if (I & 1)
			{
				Indices.Add(uint16(Base + I + 1)); Indices.Add(uint16(Base + I)); Indices.Add(uint16(Base + I + 2));
			}
			else
			{
				Indices.Add(uint16(Base + I)); Indices.Add(uint16(Base + I + 1)); Indices.Add(uint16(Base + I + 2));
			}
		}
	}
	IndexBufferRHI = UE::RHIResourceUtils::CreateIndexBufferFromArray(RHICmdList, TEXT("GoT.GrassIndexBuffer"), EBufferUsageFlags::Static, MakeConstArrayView(Indices));
}

class FGoTGrassVertexFactoryShaderParameters : public FVertexFactoryShaderParameters
{
	DECLARE_TYPE_LAYOUT(FGoTGrassVertexFactoryShaderParameters, NonVirtual);

public:
	void Bind(const FShaderParameterMap& ParameterMap) {}

	void GetElementShaderBindings(
		const class FSceneInterface* Scene,
		const class FSceneView* View,
		const class FMeshMaterialShader* Shader,
		const EVertexInputStreamType InputStreamType,
		ERHIFeatureLevel::Type FeatureLevel,
		const class FVertexFactory* InVertexFactory,
		const struct FMeshBatchElement& BatchElement,
		class FMeshDrawSingleShaderBindings& ShaderBindings,
		FVertexInputStreamArray& VertexStreams) const
	{
		const FGoTGrassBatchUserData* UserData = static_cast<const FGoTGrassBatchUserData*>(BatchElement.UserData);
		if (UserData)
		{
			ShaderBindings.Add(Shader->GetUniformBufferParameter<FGoTGrassVFParameters>(), UserData->UniformBuffer);
		}
	}
};

IMPLEMENT_TYPE_LAYOUT(FGoTGrassVertexFactoryShaderParameters);
IMPLEMENT_VERTEX_FACTORY_PARAMETER_TYPE(FGoTGrassVertexFactory, SF_Vertex, FGoTGrassVertexFactoryShaderParameters);

void FGoTGrassVertexFactory::InitRHI(FRHICommandListBase& RHICmdList)
{
	FVertexStream NullStream;
	NullStream.VertexBuffer = nullptr;
	NullStream.Stride = 0;
	NullStream.Offset = 0;
	NullStream.VertexStreamUsage = EVertexStreamUsage::ManualFetch;
	check(Streams.Num() == 0);
	Streams.Add(NullStream);
	FVertexDeclarationElementList Elements;
	InitDeclaration(Elements);
}

bool FGoTGrassVertexFactory::ShouldCompilePermutation(const FVertexFactoryShaderPermutationParameters& Parameters)
{
	if (!IsFeatureLevelSupported(Parameters.Platform, ERHIFeatureLevel::SM5))
	{
		return false;
	}
	// [适配] UE has no material usage flag for plugin vertex factories. The grass material sets the (otherwise unused in
	// this project) "Used with Virtual Heightfield Mesh" flag, so only it compiles this vertex factory.
	return (Parameters.MaterialParameters.MaterialDomain == MD_Surface && Parameters.MaterialParameters.bIsUsedWithVirtualHeightfieldMesh)
		|| Parameters.MaterialParameters.bIsSpecialEngineMaterial;
}

void FGoTGrassVertexFactory::ModifyCompilationEnvironment(const FVertexFactoryShaderPermutationParameters& Parameters, FShaderCompilerEnvironment& OutEnvironment)
{
	OutEnvironment.SetDefine(TEXT("GOT_GRASS_VERTEX_FACTORY"), 1);
}

IMPLEMENT_VERTEX_FACTORY_TYPE(FGoTGrassVertexFactory, "/Plugin/GoTEnvironment/Private/GoTGrassVertexFactory.ush",
	EVertexFactoryFlags::UsedWithMaterials | EVertexFactoryFlags::SupportsDynamicLighting);
