#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
APPDIR="$(pwd)"
DESKTOP="$HOME/.local/share/applications/apex-oled-studio.desktop"

mkdir -p "$HOME/.local/share/applications"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Apex OLED Studio
Comment=Edit the SteelSeries Apex OLED screen
Exec=$APPDIR/run.sh
Terminal=false
Categories=Utility;Settings;
EOF

chmod +x "$DESKTOP"
echo "Application launcher installed:"
echo "$DESKTOP"
