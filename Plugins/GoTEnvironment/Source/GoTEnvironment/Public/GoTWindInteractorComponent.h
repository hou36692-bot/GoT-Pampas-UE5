#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "GoTWindInteractorComponent.generated.h"

/** Pushes grass and pampas apart around its owner (characters, horses). Registers with UGoTWindSubsystem. */
UCLASS(ClassGroup = (GoT), meta = (BlueprintSpawnableComponent))
class GOTENVIRONMENT_API UGoTWindInteractorComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UGoTWindInteractorComponent();

	/** Radius of the pushed area (a horse wants ~180). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT|Interaction", meta = (ClampMin = "10"))
	float RadiusCm = 95.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT|Interaction", meta = (ClampMin = "0"))
	float Strength = 1.f;

	/** Offset from the actor location to the stamped point (feet are usually below the capsule centre). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT|Interaction")
	FVector LocalOffset = FVector::ZeroVector;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "GoT|Interaction")
	bool bInteractionEnabled = true;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
};
