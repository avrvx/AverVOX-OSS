# AverVOX OSS — Give your LLMs a voice.

Add voice to any OpenAI-compatible endpoint, local or remote. Dictate into any app. Select text to have it read aloud. Hold free-form voice conversations with Large Language Models (LLMs) on Linux.

**Key Features of AverVOX OSS**

- **Local‑only voice processing** – Both Speech‑to‑Text (STT) and Text‑to‑Speech (TTS) run on your own machine. The only network traffic is to the LLM endpoints you configure, which may be:
  - Hosted locally (on the same computer or another device on your LAN), **or**
  - Accessed remotely via any inference provider you choose (OpenAI, LocalAI, vLLM, SGLang, LM Studio, Ollama, Hermes Agent, OpenClaw, etc.).

- **Tray app + command‑line interface** – A system‑tray GUI for everyday use and a CLI tool (`avrvx`) for scripting and automation.

- **Piper TTS** – Fast, low‑resource local speech synthesis.

- **Multiple LLM profiles** – Define named endpoints and switch between them instantly via the tray menu.

- **XDG‑compliant configuration** – All settings are stored in YAML files under `~/.config/avervox/`; no extra dotfiles clutter your home directory.

**Support**

AverVOX OSS is free and open-source. For issues and questions, please open an issue on the project repository.

---

### Installation

```bash
git clone https://github.com/avrvx/AverVOX-OSS.git
cd AverVOX-OSS
bash install.sh
```

This will:

- Install the required system packages (PyGObject, PortAudio, xdotool, xclip)
- Create a Python virtual environment under `~/.local/share/avervox/`
- Install all required Python packages
- Download the Piper voice model
- Write an `avrvx` launcher to `~/.local/bin/`
- Add desktop menu and autostart entries

---

## Interaction Modes (three)

| Mode | Shortcut / Command | What it does |
|------|-------------------|--------------|
| **Speech‑to‑Text** | `Ctrl+Alt+Space` | Press once to start dictation, speak naturally, press again to stop. Text is inserted as you pause. |
| **Oration** | `Ctrl+Alt+S` | Select any text, hit the shortcut, and AverVOX reads it aloud using Piper. |
| **Converse** | `Ctrl+Alt+C` | Hold a conversation with your chosen LLM. |
| **CLI** | `avrvx …` | Headless commands for scripting (see below). |

---

## Setup

1. Local: Start an OpenAI-compatible LLM server such as LM Studio or Ollama and confirm its API base URL.
2. Remote: Can be used with any inference provider using an OpenAI-compatible API.
3. Right-click the AverVOX OSS tray icon and open **Settings…**
4. Add a profile with a **Label** and **API base URL**; click the circular Test Connection button and select a **Model**.
5. Optionally set a **Session header** if the endpoint supports session-aware conversations.
6. Save, then press `Ctrl+Alt+C`.

## Usage

### GUI (system‑tray) Mode
```bash
avrvx
```
- Starts a tray icon with hotkeys active.
- A desktop notification confirms the app is ready.
- No main window appears; all interaction is via shortcuts or the tray menu.

**Tray‑icon right‑click menu**

- **LLM:** Shows the active profile; click to switch profiles.
- **Reload config:** Re‑reads `config.yaml` without restarting.
- **Settings…** Opens the full settings dialog.
- **Copy Last Response** Copies the most recent LLM reply to the clipboard.
- **Open Log** Opens `avervox.log` in your default viewer.
- **About AverVOX OSS** Shows version, tagline, and links.
- **Quit AverVOX OSS** Exits the program.

### CLI Modes
```bash
# Record speech (VAD auto‑stop) and print transcript
avrvx --listen

# Speak literal text
avrvx --speak "Hello world"

# Pipe text from another command
echo "The quick brown fox" | avrvx --speak

# Show version and exit
avrvx --version

# Combine with any tool
avrvx --listen | my-llm-tool | avrvx --speak
```

### Scripting Your Assistant
AverVOX OSS is built for terminal pipelines. Example workflows:

```bash
echo "Build succeeded" | avrvx --speak
avrvx --speak "Deployment complete"
avrvx --listen                             # capture speech, output transcript
avrvx --listen | my-tool | avrvx --speak   # pipe through an LLM or other processor
```
Running `avrvx` with no flags launches the system‑tray app as described above.

### Conversations

- **How to start** – Press **Ctrl + Alt + C**.
- **Visual cue** – A pill‑shaped indicator shows the current state:
  - **Red** = Listening
  - **Orange** = Processing
  - **Green** = Streaming response

  The microphone is muted during TTS to avoid echo; headphones are recommended.

- **Interaction flow** – Speech → STT → LLM → streaming TTS. Playback begins as soon as the first sentence is ready and continues with minimal gaps while the model finishes generating. After each reply AverVOX automatically listens for the next turn.

- **Ending a conversation** – any of these will stop the loop:
  1. Say a goodbye phrase (e.g., "talk to you later", "goodbye", "that's all").
  2. Remain silent for the configured *silence timeout*.
  3. Press **Ctrl + Alt + C** again.

- **Markdown stripping** – LLM output is cleaned of markup before it is spoken so the audio sounds natural.

- **Session tracking** – If your LLM endpoint supports session‑aware conversations, set the *Session header* field in the LLM profile (e.g., `X-Hermes-Session-Id`). AverVOX sends a UUID with each request; if the server returns a different ID it adopts that for the rest of the app session.

- **State machine**

```
IDLE → LISTENING ⇄ TRANSCRIBING → CONVERSING → SPEAKING
       └─ (silence timeout or goodbye) → IDLE
```

The microphone stays off during the STT → LLM → TTS pipeline, and a configurable re‑arm delay reduces speaker‑to‑mic feedback before listening resumes.

---

### How It Works

AverVOX OSS is built around a simple pipeline: your voice goes in, text comes out (or vice versa), with an LLM in the middle if you want one. Here's what's doing the work under the hood.

**Voice I/O** uses `parec` + `sounddevice` for audio capture and playback, with `webrtcvad` handling voice activity detection. STT is handled by `faster-whisper`; TTS by Piper (an ONNX model, ~16 MB, very fast). Sentences are streamed to the TTS engine as they arrive from the LLM, so playback starts almost immediately rather than waiting for a full response.

**LLM connectivity** goes through `httpx` to any `/v1`-compatible endpoint — LM Studio, Ollama, Hermes Agent, OpenClaw, OpenAI, whatever you're running. Responses stream via SSE. Markdown is stripped before speech so you don't hear "asterisk asterisk bold asterisk asterisk."

**Activation** is handled by `pynput` for global hotkeys. Both X11 and Wayland (via XWayland) are supported. Text selection uses `xclip`; text injection uses `xdotool` or the clipboard depending on the target app.

---

### Architecture Overview

```
Activation layer
  └─ Hotkeys (pynput)                     → Ctrl+Alt+Space  = Dictate
                                            → Ctrl+Alt+S      = Oration
                                            → Ctrl+Alt+C      = Converse

Services layer
  • SpeechService   – STT (faster‑whisper)
  • InsertService   – xdotool / clipboard text injection
  • LLMService      – httpx → any OpenAI‑compatible API (streaming SSE)

Core components
  • TTS engine: Piper (ONNX, ~16 MB)
  • Audio I/O: parec + sounddevice + webrtcvad
  • Selection provider: xclip
```

---

### Configuration (`~/.config/avervox/config.yaml`)

```yaml
hotkeys:
  listen: "<ctrl>+<alt>+space"
  speak_selection: "<ctrl>+<alt>+s"
  converse: "<ctrl>+<alt>+c"

stt:
  model: base          # tiny / small / medium also available
  language: en

audio:
  vad_aggressiveness: 2
  silence_duration_ms: 1000   # pause before inserting dictation text

converse:
  silence_timeout_ms: 7000
  rearm_delay_ms: 250
  goodbye_phrases:
    - "talk to you later"
    - "goodbye"
    - "bye bye"
    - "see you later"
    - "that's all"
    - "good night"
    - "i'm done"
  interrupt_enabled: false

llm:
  active: my-server
  profiles:
    my-server:
      label: "LM Studio (local)"
      api_base: "http://localhost:1234/v1"
      api_key: ""
      default_model: ""
      session_header: ""          # e.g. X-Hermes-Session-Id
```

Most users only need to edit the **llm** section, and the Settings dialog handles that. Everything else has sensible defaults.

---

### Files & Packages

```
src/avervox/
├─ __init__.py, __main__.py, main.py
├─ config.py, audio.py, stt.py, tts.py
├─ inserter.py, hotkeys.py, tray.py, logger.py
├─ settings.py, hud.py, llm.py
└─ services/
    ├─ __init__.py, base.py, local.py, direct.py
```

---

### System Requirements

- Linux Mint 21/22 or Ubuntu 22.04/24.04 (X11 or XWayland)
- PulseAudio **or** PipeWire
- Python 3.12+

---

### Audio Hardware & Environment Tips

| Factor | Recommendation |
|--------|----------------|
| Microphone | USB mic or boom headset for best accuracy |
| Background noise | Reduce fans, traffic, conversations; use a quieter room |
| Room acoustics | Avoid echoey spaces; consider soft furnishings |
| Mic distance/level | Keep a steady distance and avoid clipping |

Adjust **Settings → Dictate** and **Settings → Converse** to match your conditions. For noisy environments, try a larger STT model (e.g., `small`).

---

### Performance Tuning

| Setting | Default | Typical tweak | Effect |
|---------|---------|---------------|--------|
| `silence_duration_ms` | 1000 ms | ↑ to 1500 ms | Longer pause before inserting dictation text; also affects end‑of‑turn timing in Converse. |
| `rearm_delay_ms` | 250 ms | ↑ to 500 ms | More time after TTS before the mic reopens; reduces feedback if you're not using headphones. |
| `silence_timeout_ms` | 7000 ms | ↑ to 10000 ms | Extends how long Converse waits before deciding you're done. |
| STT `beam_size` | 1 | ↑ to 5 | Higher beam sizes are slower but can improve transcription accuracy. |
| STT model | base | tiny / small | Tiny is fastest with the lowest accuracy; larger models trade speed for quality. |

---

### Troubleshooting

| Symptom | Check / Fix |
|---------|-------------|
| No audio output | Run `avrvx --listen` to verify capture and playback. |
| Hotkeys don't work | Check `journalctl --user -f` for pynput/X11 errors. |
| ALSA/Pulse errors | Make sure PulseAudio or PipeWire is running. |
| Converse fails | Verify the LLM endpoint passes the connection test and lists available models. |
| Bad transcription | Reduce background noise, move closer to the mic, or switch to a larger STT model. |
| Conversation ends too early | Increase `silence_duration_ms` or `silence_timeout_ms`. |

Log file: `~/.local/share/avervox/avervox.log`

---

### License

AverVOX OSS is free and open-source software. See the `LICENSE` file for full terms.
