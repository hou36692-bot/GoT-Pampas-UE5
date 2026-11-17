#!/usr/bin/env bash
# Build World Partition HLODs for a map with the HLOD builder commandlet.
# If the editor is open, first switch it to a blank map (Tools/mcp/ue_editor_blank.py),
# then reload the map afterwards (Tools/mcp/ue_editor_open_pampas.py).
# Usage: bash Tools/ue_build_hlod.sh [/Game/GoT/Maps/L_Pampas]
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'   # Git Bash would rewrite /Game/... into a Windows path
MAP="${1:-/Game/GoT/Maps/L_Pampas}"
UE="D:/UE/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
PROJ="D:/UE_Project/GhostOfTsushima_/GhostOfTsushima_.uproject"
LOG="HLOD_$(basename "$MAP").log"
"$UE" "$PROJ" -run=WorldPartitionBuilderCommandlet "$MAP" -Builder=WorldPartitionHLODsBuilder \
  -AllowCommandletRendering -unattended -nop4 -nosplash -NoShaderDistrib -log="$LOG"
echo "exit=$? log=D:/UE_Project/GhostOfTsushima_/Saved/Logs/$LOG"
