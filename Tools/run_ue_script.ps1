# Run one UE Python script in a full rendering editor; the script quits the editor itself.
# Usage: powershell -File Tools/run_ue_script.ps1 <script file name in Tools> <log name>
param([Parameter(Mandatory)][string]$Script, [Parameter(Mandatory)][string]$LogName)
$ErrorActionPreference = 'Stop'
$root = 'D:/HOU/Ghost of Tsushima'
if (Get-Process UnrealEditor -ErrorAction SilentlyContinue) { throw 'UnrealEditor is running: close it before running scripts' }
$env:UE_SKIP_UBT_SDK_SETUP = '1'
$p = Start-Process -FilePath 'D:/UE/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe' -PassThru -ArgumentList @(
  '"D:/UE_Project/GhostOfTsushima_/GhostOfTsushima_.uproject"',
  "-ExecutePythonScript=`"$root/Tools/$Script`"",
  '-unattended', '-nosplash', '-NoSound', '-DisableLiveCoding', '-RenderOffscreen', "-abslog=`"$root/Tools/state/$LogName.log`"")
$p.WaitForExit()
"exit $($p.ExitCode)"
