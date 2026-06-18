#!/usr/bin/env bash
# AverVOX — LLM Speech Bridge installer
# Add voice to any LLM using an OpenAI-compatible endpoint.
# Target: Linux Mint 22.x / Ubuntu 24.04
# Usage: bash install.sh

set -euo pipefail

AVOX_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/avervox"
AVOX_VENV="$AVOX_DATA/venv"
AVOX_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/avervox"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== AverVOX — LLM Speech Bridge Installer ==="
echo "Add voice to any LLM using an OpenAI-compatible endpoint."
echo ""
echo "Script dir : $SCRIPT_DIR"
echo "Venv       : $AVOX_VENV"
echo "Config dir : $AVOX_CONFIG"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/6] Installing system packages…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-glib-2.0 \
    gir1.2-appindicator3-0.1 \
    libgirepository1.0-dev \
    portaudio19-dev libportaudio2 libportaudiocpp0 \
    xdotool xclip \
    --no-install-recommends

echo "  ✓ System packages installed"

# ── 2. Create venv ─────────────────────────────────────────────────────────────
echo "[2/6] Creating Python 3 venv at $AVOX_VENV…"
mkdir -p "$AVOX_DATA"
if [ ! -d "$AVOX_VENV" ]; then
    python3 -m venv --system-site-packages "$AVOX_VENV"
    echo "  ✓ Venv created (--system-site-packages to reuse PyGObject)"
else
    echo "  ✓ Venv already exists — skipping creation"
fi

# ── 3. Install pip packages ──────────────────────────────────────────────────
echo "[3/6] Installing pip dependencies…"
"$AVOX_VENV/bin/pip" install --upgrade pip --quiet
"$AVOX_VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
"$AVOX_VENV/bin/pip" install "piper-tts>=1.2.0" --quiet
echo "  ✓ Piper TTS installed"

SITE_PKGS="$("$AVOX_VENV/bin/python" -c "import sysconfig; print(sysconfig.get_path('purelib'))")"
echo "$SCRIPT_DIR/src" > "$SITE_PKGS/avervox-src.pth"
echo "  ✓ Source path registered in venv (avervox-src.pth)"

# ── 4. Download Piper voice model ────────────────────────────────────────────
echo "[4/6] Downloading Piper voice model…"

PIPER_VOICE_DIR="$HOME/.local/share/piper-tts/voices"
PIPER_VOICE_PATH="$PIPER_VOICE_DIR/en_US-lessac-high.onnx"

if [ -f "$PIPER_VOICE_PATH" ]; then
    echo "  ✓ Piper voice already downloaded"
else
    mkdir -p "$PIPER_VOICE_DIR"
    echo "  Downloading Piper voice (en_US-lessac-high, ~16 MB)…"
    wget -q --show-progress -O "$PIPER_VOICE_PATH" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx"
    wget -q -O "${PIPER_VOICE_PATH}.json" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/high/en_US-lessac-high.onnx.json"
    echo "  ✓ Piper voice downloaded to $PIPER_VOICE_DIR"
fi

# ── 5. Write initial config (if none exists) ─────────────────────────────────
echo "[5/6] Checking configuration…"
CONFIG_FILE="$AVOX_CONFIG/config.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    mkdir -p "$AVOX_CONFIG"
    cat > "$CONFIG_FILE" << CFGEOF
hotkeys:
  listen: "<ctrl>+<alt>+space"
  speak_selection: "<ctrl>+<alt>+s"
  converse: "<ctrl>+<alt>+c"

stt:
  model: base
  language: en

tts:
  voice_model: "$PIPER_VOICE_PATH"

audio:
  vad_aggressiveness: 2
  silence_duration_ms: 1000  # Dictate interim + Converse (Settings → Dictate)

backends:
  text_inserter: xdotool
  selection_provider: xclip
CFGEOF
    echo "  ✓ Config written to $CONFIG_FILE"
else
    echo "  ✓ Config already exists — not overwriting"
fi

# ── 6. Copy icon assets + write launcher ─────────────────────────────────────
echo "[6/6] Installing icons, launcher, and autostart entry…"

ICON_DEST="$AVOX_DATA/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DEST"
if ls "$SCRIPT_DIR/assets/icons/"*.svg 1>/dev/null 2>&1; then
    for svg in "$SCRIPT_DIR/assets/icons/"*.svg; do
        cp "$svg" "$ICON_DEST/"
    done
    echo "  ✓ Icons installed to $ICON_DEST"
else
    echo "  ⚠ No SVG icons found in assets/icons/ — using system fallback"
fi

BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
LAUNCHER="$BIN_DIR/avrvx"
cat > "$LAUNCHER" << EOF
#!/usr/bin/env bash
# AverVOX launcher — runs inside the dedicated venv
export PYTHONPATH="$SCRIPT_DIR/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$AVOX_VENV/bin/python" -m avervox "\$@"
EOF
chmod +x "$LAUNCHER"
echo "  ✓ Launcher written to $LAUNCHER"

AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/avervox.desktop" << EOF
[Desktop Entry]
Type=Application
Name=AverVOX
Comment=Add voice to any LLM using an OpenAI-compatible endpoint.
Exec=$LAUNCHER
Icon=audio-input-microphone
Terminal=false
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF
echo "  ✓ Autostart entry written to $AUTOSTART_DIR/avervox.desktop"

APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$AUTOSTART_DIR/avervox.desktop" "$APPS_DIR/avervox.desktop"
echo "  ✓ Application menu entry written"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Run AverVOX:       avrvx"
echo "  or:              $AVOX_VENV/bin/python -m avervox"
echo ""
echo "CLI modes:         avrvx --listen        (VAD auto-stop → stdout)"
echo "                   avrvx --speak 'text'  (TTS playback)"
echo "                   echo text | avrvx --speak"
echo ""
echo "Config:            $AVOX_CONFIG/config.yaml"
echo "Log:               $AVOX_DATA/avervox.log"
echo "Settings:          Right-click tray icon → Settings…"
echo ""
echo "Hotkeys:"
echo "  Ctrl+Alt+Space    — record → transcribe → insert (Dictate; press again to stop)"
echo "  Ctrl+Alt+S        — speak selected text (Speak)"
echo "  Ctrl+Alt+C        — voice conversation with LLM (Converse)"
echo ""
echo "End conversation:  say \"goodbye\" / \"talk to you later\", 7 s silence, or hotkey"
echo ""
echo "For natural-sounding TTS, wake word, session memory, and more:"
echo "  [Pro purchase page]"
echo ""
echo "See README.md for details."
