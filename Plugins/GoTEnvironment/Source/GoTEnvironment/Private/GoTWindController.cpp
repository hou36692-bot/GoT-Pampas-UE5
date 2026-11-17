#include "GoTWindController.h"
#include "GoTWindSettings.h"

#include "Components/ArrowComponent.h"
#include "Components/BillboardComponent.h"
#include "Components/TextRenderComponent.h"

AGoTWindController::AGoTWindController()
{
	PrimaryActorTick.bCanEverTick = false;
	Params = GetDefault<UGoTWindSettings>()->Params;

	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Arrow = CreateDefaultSubobject<UArrowComponent>(TEXT("WindArrow"));
	Arrow->SetupAttachment(Root);
	Arrow->ArrowSize = 4.f;
	Arrow->ArrowLength = 120.f;
	Arrow->ArrowColor = FColor(80, 200, 255);
	Arrow->SetUsingAbsoluteRotation(true);
	Arrow->bIsScreenSizeScaled = true;
	Arrow->SetHiddenInGame(false);

	InfoText = CreateDefaultSubobject<UTextRenderComponent>(TEXT("InfoText"));
	InfoText->SetupAttachment(Root);
	InfoText->SetRelativeLocation(FVector(0.f, 0.f, 120.f));
	InfoText->SetUsingAbsoluteRotation(true);
	InfoText->SetHorizontalAlignment(EHTA_Center);
	InfoText->SetVerticalAlignment(EVRTA_TextBottom);
	InfoText->SetWorldSize(22.f);
	InfoText->SetTextRenderColor(FColor(120, 230, 255));
	InfoText->SetCastShadow(false);
	InfoText->SetHiddenInGame(false);
	InfoText->SetText(FText::FromString(TEXT("GoT Wind")));

#if WITH_EDITORONLY_DATA
	Sprite = CreateEditorOnlyDefaultSubobject<UBillboardComponent>(TEXT("Sprite"));
	if (Sprite)
	{
		Sprite->SetupAttachment(Root);
		Sprite->bIsScreenSizeScaled = true;
	}
	bIsSpatiallyLoaded = false;   // the wind must exist wherever the player is
#endif
}

void AGoTWindController::ShowDirection(float YawDegrees)
{
	if (Arrow)
	{
		Arrow->SetWorldRotation(FRotator(0.f, YawDegrees, 0.f));
	}
}

void AGoTWindController::ShowInfo(const FString& Text, const FVector& ViewLocation)
{
	if (!InfoText)
	{
		return;
	}
	InfoText->SetVisibility(bShowInfoText);
	if (!bShowInfoText)
	{
		return;
	}
	InfoText->SetText(FText::FromString(Text));
	// Face the view (yaw only) and keep a roughly constant on-screen size.
	const FVector ToView = ViewLocation - InfoText->GetComponentLocation();
	InfoText->SetWorldRotation(FRotator(0.f, ToView.Rotation().Yaw, 0.f));
	InfoText->SetWorldSize(FMath::Clamp(float(ToView.Size()) * 0.012f, 12.f, 600.f));
}

void AGoTWindController::SaveAsProjectDefaults()
{
	UGoTWindSettings* Settings = GetMutableDefault<UGoTWindSettings>();
	Settings->Params = Params;
#if WITH_EDITOR
	Settings->TryUpdateDefaultConfigFile();
#endif
}

void AGoTWindController::LoadProjectDefaults()
{
	Modify();
	Params = GetDefault<UGoTWindSettings>()->Params;
}
