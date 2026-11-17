#include "GoTWindInteractorComponent.h"
#include "GoTWindSubsystem.h"
#include "Engine/World.h"

UGoTWindInteractorComponent::UGoTWindInteractorComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
}

void UGoTWindInteractorComponent::BeginPlay()
{
	Super::BeginPlay();
	if (UWorld* World = GetWorld())
	{
		if (UGoTWindSubsystem* Wind = World->GetSubsystem<UGoTWindSubsystem>())
		{
			Wind->RegisterInteractor(this);
		}
	}
}

void UGoTWindInteractorComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UWorld* World = GetWorld())
	{
		if (UGoTWindSubsystem* Wind = World->GetSubsystem<UGoTWindSubsystem>())
		{
			Wind->UnregisterInteractor(this);
		}
	}
	Super::EndPlay(EndPlayReason);
}
