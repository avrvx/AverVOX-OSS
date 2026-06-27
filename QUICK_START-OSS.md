# AverVOX OSS - Quick Start User Guide
Website Edition
version: 0.3.7

AverVOX OSS is a desktop app which runs in the Task Bar. Unless specified otherwise for particular operations described elsewhere in the documentation, we recommend starting the program by clicking the desktop launcher added by the installer to the desktop menu.

The app shows a microphone icon in the system tray (Task Bar); there is no main window.

---

## Step 1 - Open Settings

At first launch, click the microphone icon in the Task Bar and select **Settings...**

---

## Using the Settings window

Clicking **Settings...** opens a window with several tabs across its top. Each tab presents its own group of settings.

- OSS uses **Save** and **Cancel** buttons (not Save/Close). **Save** writes settings to disk and closes the dialog.
- Changes under each tab are preserved in memory as they are made, so one can freely navigate between tabs to make adjustments prior to clicking **Save** to write one's changes to disk.
- On the **LLM** tab, switching profiles in the dropdown saves that profile's fields in memory before loading the next one.

An info bar at the top links to AverVOX Pro for additional features (wake word, Kokoro TTS, session memory, LAN server, etc.).

---

## Settings tabs

### Hotkeys

| Setting | Description |
|---------|-------------|
| **Dictate** | Start or stop dictation. Default: `<ctrl>+<alt>+space`. |
| **Speak selection** | Read selected text aloud. Default: `<ctrl>+<alt>+s`. |
| **Converse** | Voice conversation with your LLM. Default: `<ctrl>+<alt>+c`. |

Use pynput format with angle brackets for modifiers (e.g. `<ctrl>+<alt>+c`).

---

### LLM

| Setting | Description |
|---------|-------------|
| **Profile dropdown** | Select, add (**+**), or delete (**-**) LLM connection profiles. |
| **Label** | Name shown in the tray menu. |
| **URL** | OpenAI-compatible API base URL. |
| **Reload (Test connection)** | Lists models from `/v1/models`. |
| **Enable switch** | Enable or disable this profile's URL. |
| **API Key** | Optional bearer token (masked). |
| **Model** | Model ID for chat requests. |
| **Session header** | Header **name only** for session-aware backends (e.g. `X-Hermes-Session-Id`). Session values apply for the current app run; persistent session memory is a Pro feature. |

---

### Text-to-Speech

| Setting | Description |
|---------|-------------|
| **Piper voice model** | Path to the Piper `.onnx` voice file. |

OSS uses Piper only (no Kokoro engine or speed control in Settings).

---

### Dictate

| Setting | Description |
|---------|-------------|
| **Speech model** | Whisper size: Tiny through Large v3. |
| **Language** | Language code (e.g. `en`). |
| **Interim pause (ms)** | Silence before interim dictation insert or Converse end-of-turn. |
| **Pause sensitivity (0-3)** | VAD aggressiveness for pause detection. |

---

### Converse

| Setting | Description |
|---------|-------------|
| **Silence timeout (sec)** | Silence before the conversation ends. |
| **Re-arm delay (ms)** | Delay after TTS before the mic reopens. |
| **Goodbye phrases** | Comma-separated phrases that end the session. |
| **Voice interrupt (barge-in)** | Speak during assistant playback to interrupt. **Requires headphones** - OSS shows a warning and confirmation checkbox because microphone feedback can cause false interrupts without them. |

---

### Advanced

| Setting | Description |
|---------|-------------|
| **Text inserter** | `xdotool` (X11) or `ydotool` (Wayland). |
| **Selection provider** | `xclip`, `xsel`, or `wl-paste`. |

---

### About

Version, description, GitHub link, and MIT license notice. Tray **About AverVOX OSS** opens Settings on this tab.

---

## Next steps

- Configure an **LLM** profile and test the connection.
- Try the three hotkeys: Dictate, Speak selection, and Converse.
- See [DOCS.md](DOCS.md) for configuration file details and [README.md](README.md) for install and troubleshooting.
