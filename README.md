# AverVOX OSS - Give your LLMs a voice.
Website Edition
version: 0.3.7

Add voice to any OpenAI-compatible endpoint, local or remote. Any app with focus can receive your speech as text. Select text to have it read aloud. Hold free-form voice conversations with Large Language Models (LLMs) on Linux.

## Key Features

- **Local-only voice processing** - Both Speech-to-Text (STT) and Text-to-Speech (TTS) run on your own machine. The only network traffic is to the LLM endpoints you configure, which may be:
  - Hosted locally (on the same computer or another device on your LAN), **or**
  - Accessed remotely via any inference provider you choose (OpenAI, LocalAI, vLLM, SGLang, LM Studio, Ollama, Hermes Agent, OpenClaw, etc.).
- **Tray app + command-line interface** - A system-tray GUI for everyday use and a CLI tool (`avrvx`) for scripting and automation.
- **Piper TTS** - Fast, low-resource local speech synthesis.
- **Multiple LLM profiles** - Define named endpoints and switch between them instantly via the tray menu.
- **XDG-compliant configuration** - All settings are stored in YAML files under `~/.config/avervox/`; no extra dotfiles clutter your home directory.

## Free vs Pro

| Feature | Free | Pro |
|---------|:----:|:---:|
| Speech-to-Text (`Ctrl+Alt+Space`) | Yes | Yes |
| Text-to-Speech (`Ctrl+Alt+S`) | Yes | Yes |
| Converse (`Ctrl+Alt+C`) | Yes | Yes |
| CLI (`avrvx --listen`, `--speak`) | Yes | Yes |
| Piper TTS | Yes | Yes |
| faster-whisper STT | Yes | Yes |
| Voice interrupt | Yes | Yes |
| Conversation HUD | Yes | Yes |
| Streaming TTS | Yes | Yes |
| Kokoro TTS | | Yes |
| TTS speed control | | Yes |
| [Custom wake word](https://openwakeword.com/) | | Yes |
| System prompts (per profile) | | Yes |
| Session memory (survives restart) | | Yes |
| LAN client/server (`avrvx --serve`) | | Yes |

AverVOX OSS is free and open-source. For issues and questions, please open an issue on the project repository. If you want the Pro-only features above (Kokoro TTS, wake word, session memory, LAN, and more), see [AverVOX Pro](https://avervoxpro.com/) - a one-time, no-subscription companion app, distributed separately (not on GitHub or PyPI).

---

## Installation

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

Alternatively, `pip install avervox` installs the package; you still need the system dependencies (GTK, xdotool, xclip, portaudio) - see `install.sh` for the full list.

**New to AverVOX OSS?** See [QUICK_START.md](QUICK_START.md) for a guided tour of the tray app and every Settings tab.

---

## Interaction Modes

| Mode | Shortcut / Command | What it does |
|------|-------------------|--------------|
| **Speech-to-Text** | `Ctrl+Alt+Space` | Press once to start dictation, speak naturally, press again to stop. Text is inserted as you pause. |
| **Text-to-Speech** | `Ctrl+Alt+S` | Select any text, hit the shortcut, and AverVOX OSS reads it aloud using Piper. |
| **Converse** | `Ctrl+Alt+C` | Hold a conversation with your chosen LLM. |
| **CLI** | `avrvx ...` | Headless commands for scripting (see below). |

---

## Setup

1. Local: Start an OpenAI-compatible LLM server such as LM Studio or Ollama and confirm its API base URL.
2. Remote: Can be used with any inference provider using an OpenAI-compatible API.
3. Right-click the AverVOX OSS tray icon and open **Settings...**
4. Add a profile with a **Label** and **API base URL**; click the circular Test Connection button and select a **Model**.
5. Optionally set a **Session header** if the endpoint supports session-aware conversations.
6. Save, then press `Ctrl+Alt+C`.

---

## Usage

### GUI (system-tray) mode
```bash
avrvx
```
- Starts a tray icon with hotkeys active.
- A desktop notification confirms the app is ready ("AverVOX OSS - Ready - hotkeys active").
- No main window appears; all interaction is via shortcuts or the tray menu.

**Tray-icon right-click menu**

- **LLM:** Shows the active profile; click to switch profiles.
- **Reload config:** Re-reads `config.yaml` without restarting.
- **Settings...** Opens the full settings dialog.
- **Copy Last Response** Copies the most recent LLM reply to the clipboard.
- **Open Log** Opens `avervox.log` in your default viewer.
- **About AverVOX OSS** Shows version, tagline, and links.
- **Quit AverVOX OSS** Exits the program.

### CLI
```bash
# Record speech (VAD auto-stop) and print transcript
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

### Scripting your assistant
AverVOX OSS is built for terminal pipelines. Example workflows:

```bash
echo "Build succeeded" | avrvx --speak
avrvx --speak "Deployment complete"
avrvx --listen                             # capture speech, output transcript
avrvx --listen | my-tool | avrvx --speak   # pipe through an LLM or other processor
```
Running `avrvx` with no flags launches the system-tray app described above.

---

## Converse

- **How to start** - Press **Ctrl+Alt+C**.
- **HUD pill** - A colour-coded pill indicator shows the current state:
  - **Red** = Listening
  - **Orange** = Processing
  - **Green** = Streaming response
- **Interaction flow** - Speech -> STT -> LLM -> streaming TTS. Playback begins as soon as the first sentence is ready and continues with minimal gaps while the model finishes generating. After each reply AverVOX OSS automatically listens for the next turn.
- **Ending a conversation** - any of these will stop the loop:
  1. Say a goodbye phrase (e.g., "talk to you later", "goodbye", "that's all"). Customisable in Settings or `converse.goodbye_phrases`.
  2. Remain silent for the configured *silence timeout* (default 7 s, `converse.silence_timeout_ms`).
  3. Press **Ctrl+Alt+C** again.
- **Voice interrupt (barge-in)** - When enabled in Settings, you can interrupt the assistant mid-response simply by speaking; AverVOX OSS stops playback immediately and listens for your next turn. This requires headphones - without them, the TTS audio feeds back into the microphone and triggers false interrupts.
- **Markdown stripping** - LLM output is cleaned of markup (headings, bold, code blocks, links, etc.) before it is spoken, so the audio sounds natural rather than reading out syntax.
- **Echo prevention** - The microphone is muted while TTS is playing, and a configurable re-arm delay (default 250 ms, `converse.rearm_delay_ms`) is applied before the mic reopens. Headphones are recommended.
- **Session tracking** - If your LLM endpoint supports session-aware conversations, set the *Session header* field in the LLM profile (e.g., `X-Hermes-Session-Id`). AverVOX OSS sends a UUID with each request; if the server returns a different ID it adopts that for the rest of the app session. OSS supports session headers for the current app session; persistent sessions that survive restarts are a Pro feature.
- **State machine**

```
IDLE -> LISTENING <-> TRANSCRIBING -> CONVERSING -> SPEAKING -> (rearm delay) (loop)
       `- silence timeout or goodbye phrase -> IDLE
```

The microphone stays off during the entire STT -> LLM -> TTS pipeline; the configurable re-arm delay reduces speaker-to-mic feedback before listening resumes.

---

## How It Works

AverVOX OSS is built around a simple pipeline: your voice goes in, text comes out (or vice versa), with an LLM in the middle if you want one. Here's what's doing the work under the hood.

**Voice I/O** uses `parec` + `sounddevice` for audio capture and playback, with `webrtcvad` handling voice activity detection. STT is handled by `faster-whisper`; TTS by Piper (an ONNX model, ~16 MB, very fast). Sentences are streamed to the TTS engine as they arrive from the LLM, so playback starts almost immediately rather than waiting for a full response.

**LLM connectivity** goes through `httpx` to any `/v1`-compatible endpoint - LM Studio, Ollama, Hermes Agent, OpenClaw, OpenAI, whatever you're running. Responses stream via SSE. Markdown is stripped before speech so you don't hear "asterisk asterisk bold asterisk asterisk."

**Activation** is handled by `pynput` for global hotkeys. Both X11 and Wayland (via XWayland) are supported. Text selection uses `xclip`; text injection uses `xdotool` or the clipboard depending on the target app.

### Architecture

```
Activation layer
  `- Hotkeys (pynput)   -> Ctrl+Alt+Space  = Speech-to-Text
                        -> Ctrl+Alt+S      = Text-to-Speech
                        -> Ctrl+Alt+C      = Converse

Services layer
  - SpeechService   - STT (faster-whisper)
  - InsertService   - xdotool / clipboard text injection
  - LLMService      - httpx -> any OpenAI-compatible API (streaming SSE)

Core components
  - TTS engine: Piper (ONNX, ~16 MB)
  - Audio I/O: parec + sounddevice + webrtcvad
  - Selection provider: xclip
```

### Source layout

```
src/avervox/
|-- __init__.py          # package metadata
|-- __main__.py          # CLI entry point (--listen, --speak, --version, or GUI)
|-- main.py              # GUI controller (state machine, hotkey handlers, notifications)
|-- config.py            # configuration loading, LLM profiles, dataclasses
|-- audio.py             # microphone capture + VAD/recorder + interrupt monitor
|-- stt.py               # speech-to-text (faster-whisper)
|-- tts.py               # text-to-speech engine (Piper), markdown stripping
|-- inserter.py          # text insertion + selection grabbing
|-- hotkeys.py           # global hotkey manager (pynput)
|-- tray.py              # system tray icon, profile submenu, copy/log/about menu items
|-- logger.py            # logging setup
|-- settings.py          # GTK settings dialog (tabbed: hotkeys, LLM, TTS, dictate, converse, advanced)
|-- hud.py               # conversation-mode HUD overlay
|-- llm.py               # OpenAI-compatible HTTP client (streaming SSE)
`-- services/
    |-- __init__.py      # service factory (create_services)
    |-- base.py          # Protocol definitions (SpeechService, InsertService, LLMService)
    |-- local.py         # local implementations wrapping existing modules
    `-- direct.py        # DirectLLMService (calls LLM API directly, with streaming)
```

---

## Configuration

`~/.config/avervox/config.yaml` (created on first run):

```yaml
hotkeys:
  listen: "<ctrl>+<alt>+space"       # Settings -> Hotkeys
  speak_selection: "<ctrl>+<alt>+s"
  converse: "<ctrl>+<alt>+c"

stt:
  model: base        # tiny, base, small, medium, large-v3
  language: en

tts:
  voice_model: ~/.local/share/piper-tts/voices/en_US-lessac-high.onnx

audio:
  vad_aggressiveness: 2       # 0-3 (higher = more aggressive silence detection)
  silence_duration_ms: 1000   # pause before inserting dictation text (Settings -> Dictate)

backends:
  text_inserter: xdotool      # xdotool | ydotool - Settings -> Advanced
  selection_provider: xclip   # xclip | xsel | wl-paste

converse:
  silence_timeout_ms: 7000          # silence before ending conversation (ms)
  rearm_delay_ms: 250               # pause after TTS before mic reopens (ms)
  goodbye_phrases:                  # phrases that end the conversation
    - "talk to you later"
    - "goodbye"
    - "bye bye"
    - "see you later"
    - "that's all"
    - "good night"
    - "i'm done"
  interrupt_enabled: false          # voice interrupt (barge-in) - requires headphones
  interrupt_headphones_confirmed: false

llm:
  active: my-server
  profiles:
    my-server:
      label: "LM Studio (local)"
      api_base: "http://localhost:1234/v1"
      api_key: ""              # leave blank for local models
      default_model: ""        # model name returned by /v1/models
      session_header: ""       # HTTP header for session tracking (e.g. X-Hermes-Session-Id)
```

Most users only need to edit the **llm** section, and the Settings dialog handles that. Everything else has sensible defaults. You can add multiple profiles and switch between them from the tray menu.

**Backward compatibility:** Old flat-format `llm:` configs (with `api_base` directly under `llm:`) are automatically migrated to a single profile on first load.

**Secrets:** API keys are masked in Settings (show/hide toggle) and stored encrypted in `config.yaml` as `enc:...` values, bound to your machine. Existing plaintext keys still load until the next save.

---

## System Requirements

- Linux Mint 21/22 or Ubuntu 22.04/24.04 (X11 or XWayland)
- PulseAudio **or** PipeWire
- Python 3.12+

---

## Audio Hardware & Environment Tips

| Factor | Recommendation |
|--------|----------------|
| Microphone | USB mic or boom headset for best accuracy |
| Background noise | Reduce fans, traffic, conversations; use a quieter room |
| Room acoustics | Avoid echoey spaces; consider soft furnishings |
| Mic distance/level | Keep a steady distance and avoid clipping |

Adjust **Settings -> Dictate** and **Settings -> Converse** to match your conditions. For noisy environments, try a larger STT model (e.g., `small`).

---

## Performance Tuning

| Setting | Default | Conservative | Where | Effect |
|---------|---------|-------------|-------|--------|
| `silence_duration_ms` | **1000** | 1500 | Settings -> Dictate, or `config.yaml` -> `audio` | Dictate: pause before typing an interim chunk. Converse / `avrvx --listen`: end-of-turn delay. |
| `rearm_delay_ms` | **250** | 500 | `config.yaml` -> `converse` | Pause after TTS finishes before the mic reopens. Prevents echo/feedback. Increase if you hear the speaker feeding back into the mic. |
| `silence_timeout_ms` | **7000** | 10000 | `config.yaml` -> `converse` | How long to wait with no speech before ending the conversation. |
| STT `beam_size` | **1** | 5 | `stt.py` | Greedy (1) is faster; beam search (5) is more accurate for mumbled or technical speech. |
| STT model | **base** | tiny / small | `config.yaml` -> `stt.model` | `tiny` is fastest, `small`/`medium` more accurate. `base` is a good middle ground. |

**Tips:**

- If Converse turns get clipped (cut off mid-sentence), increase `silence_duration_ms`.
- If you hear echo (AverVOX OSS responding to its own TTS), increase `rearm_delay_ms`.
- For the fastest possible turns at the cost of some accuracy, use `stt.model: tiny` with `beam_size: 1`.

---

## Troubleshooting

| Symptom | Check / Fix |
|---------|-------------|
| No audio output | Run `avrvx --listen` to verify capture and playback. |
| Hotkeys don't work | Check `journalctl --user -f` for pynput/X11 errors. |
| ALSA/Pulse errors | Make sure PulseAudio or PipeWire is running. |
| Converse fails | Open Settings, verify the test button shows a green checkmark and models are listed; check the log for `LLM error` entries. |
| Bad transcription | Reduce background noise, move closer to the mic, or switch to a larger STT model (`small`/`medium`). |
| Conversation ends too early | Increase `silence_duration_ms` or `silence_timeout_ms`; use headphones to limit speaker bleed in loud environments. |

Log file: `~/.local/share/avervox/avervox.log`

---

## License

AverVOX OSS is free and open-source software. See the `LICENSE` file for full terms.
