# AverVOX OSS - Documentation
Technical reference for AverVOX OSS (free).
Website Edition
version: 0.3.7

For a quick overview and install, see
[README.md](README.md).

**New users:** [QUICK_START-OSS.md](QUICK_START-OSS.md) walks through the tray app and every Settings tab.

## Edition matrix

| Feature | Free | Pro |
|---------|:----:|:---:|
| Dictate (`Ctrl+Alt+Space`) | Yes | Yes |
| Speak selection (`Ctrl+Alt+S`) | Yes | Yes |
| Converse (`Ctrl+Alt+C`) | Yes | Yes |
| CLI (`avrvx --listen`, `--speak`) | Yes | Yes |
| Piper TTS | Yes | Yes |
| faster-whisper STT | Yes | Yes |
| Voice interrupt | Yes | Yes |
| Conversation HUD | Yes | Yes |
| Streaming TTS | Yes | Yes |
| Kokoro TTS | | Yes |
| TTS speed control | | Yes |
| Custom wake word | | Yes |
| System prompts (per profile) | | Yes |
| Session memory (survives restart) | | Yes |
| LAN client/server (`avrvx --serve`) | | Yes |

Pro-only features (Kokoro TTS, wake word, session memory, LAN, and more) are
listed in the edition matrix above. AverVOX Pro is distributed separately - not
on GitHub or PyPI. See `[Pro purchase page]`. URL placeholders: [LINKS.md](LINKS.md).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Activation                                                      │
│    Hotkeys (pynput)                                              │
│                                                                  │
│    Ctrl+Alt+Space  ->  record -> STT -> insert_text()   (Dictate; press to stop)│
│    Ctrl+Alt+S      ->  get_selection() -> TTS -> play   (Speak)   │
│    Ctrl+Alt+C      ->  listen -> STT -> LLM -> TTS <-     (Converse)│
└──────────────────────────────────────────────────────────────────┘
│ Services layer (SpeechService, InsertService, LLMService)        │
│   STT: faster-whisper, TTS: piper, LLM: httpx -> OpenAI API      │
├──────────────────────────────────────────────────────────────────┤
│ STT: faster-whisper (local, CPU, int8)                           │
│ TTS: piper-tts (local ONNX voices, ~16 MB)                      │
│ Audio: parec (capture) + sounddevice (playback) + webrtcvad      │
│ Insert: xdotool type / clipboard fallback                        │
│ Selection: xclip (X11 primary/clipboard)                         │
│ LLM: httpx -> any OpenAI-compatible API (streaming SSE)           │
└──────────────────────────────────────────────────────────────────┘
```

## Installation details

The installer creates a Python venv at `~/.local/share/avervox/venv`, downloads
the Piper voice model, and writes an `avrvx` launcher to `~/.local/bin/`.

Alternatively, `pip install avervox` installs the package; you still need
system dependencies (GTK, xdotool, xclip, portaudio) - see `install.sh` for the
full list.

## GUI usage

```bash
avrvx
```

Starts the system tray icon with hotkeys active. A desktop notification
confirms "AverVOX OSS - Ready - hotkeys active". No window - just the tray.

Right-click the tray icon for:

- **LLM: (active profile)** - switch between LLM profiles
- **Reload config** - re-read `config.yaml` without restarting
- **Settings...** - open the full settings dialog
- **Copy Last Response** - copy the most recent LLM response to the clipboard
- **Open Log** - open `avervox.log` in your default text viewer
- **About AverVOX OSS** - version, tagline, and links
- **Quit AverVOX OSS**

## Converse mode

### Ending a conversation

- Say a **goodbye phrase** - "talk to you later", "goodbye", "that's all", etc.
  (customisable in Settings or `converse.goodbye_phrases` in config)
- Stay silent for the **silence timeout** (default 7 s, configurable in Settings
  or `converse.silence_timeout_ms` in config)
- Press **Ctrl+Alt+C** again

### Voice interrupt (barge-in)

When enabled in Settings, you can interrupt the assistant mid-response simply by
speaking. AverVOX OSS stops playback immediately and listens for your next turn.
This requires headphones - without them, the TTS audio feeds back into the
microphone and triggers false interrupts.

### Markdown stripping

LLM responses are automatically cleaned of markdown formatting (headings, bold,
code blocks, links, etc.) before being spoken, so you hear natural sentences
rather than markup syntax.

### Session tracking

If your LLM endpoint supports session-aware conversations (e.g. Hermes Agent,
Open Claw), set the **Session header** field in your LLM profile to the
appropriate HTTP header name (e.g. `X-Hermes-Session-Id`). AverVOX OSS sends a
UUID in that header with every request. If the server returns a different
session ID in the same header, AverVOX OSS adopts it for all subsequent requests and
logs the change. Free supports custom session headers during the current app
session; for persistent sessions that survive restarts, see AverVOX Pro.

### Echo prevention

The microphone is muted while TTS is playing and a configurable delay (default
250 ms, `converse.rearm_delay_ms`) is applied before re-arming after playback
finishes.

### HUD pill

A colour-coded pill appears at the bottom-right of the screen during Converse
mode so you always know whose turn it is (recording, processing, speaking).

### State machine

```
IDLE -> LISTENING <-> TRANSCRIBING -> CONVERSING -> SPEAKING -> (rearm delay) <-
       └─ silence timeout or goodbye phrase -> IDLE
```

The loop continues until explicitly ended. The mic is off during the entire
STT -> LLM -> TTS pipeline and the configurable rearm delay (default 250 ms)
is inserted before re-arming to prevent speaker-to-mic feedback.

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
  vad_aggressiveness: 2      # 0-3 (higher = more aggressive silence detection)
  silence_duration_ms: 1000  # Dictate interim + Converse (Settings -> Dictate)

backends:
  text_inserter: xdotool     # xdotool | ydotool - Settings -> Advanced
  selection_provider: xclip  # xclip | xsel | wl-paste

# Converse mode options
converse:
  silence_timeout_ms: 7000         # silence before ending conversation (ms)
  rearm_delay_ms: 250              # pause after TTS before mic reopens (ms)
  goodbye_phrases:                 # phrases that end the conversation
    - "talk to you later"
    - "goodbye"
    - "bye bye"
    - "see you later"
    - "that's all"
    - "good night"
    - "i'm done"
  interrupt_enabled: false          # voice interrupt (barge-in) - requires headphones
  interrupt_headphones_confirmed: false

# LLM profiles (for Converse mode) - manage via Settings or edit directly
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

Most users only need to configure the `llm` section (via the Settings dialog)
to enable Converse mode. You can add multiple profiles and switch between them
from the tray menu.

**Backward compatibility:** Old flat-format `llm:` configs (with `api_base`
directly under `llm:`) are automatically migrated to a single profile on first
load.

API keys are masked in Settings and stored encrypted in `config.yaml`. Plaintext
keys from older configs still load until you save settings again.

## Source layout

```
src/avervox/
├── __init__.py          # package metadata
├── __main__.py          # CLI entry point (--listen, --speak, --version, or GUI)
├── main.py              # GUI controller (state machine, hotkey handlers, notifications)
├── config.py            # configuration loading, LLM profiles, dataclasses
├── audio.py             # microphone capture + VAD/recorder + interrupt monitor
├── stt.py               # speech-to-text (faster-whisper)
├── tts.py               # text-to-speech engine (Piper), markdown stripping
├── inserter.py          # text insertion + selection grabbing
├── hotkeys.py           # global hotkey manager (pynput)
├── tray.py              # system tray icon, profile submenu, copy/log/about menu items
├── logger.py            # logging setup
├── settings.py          # GTK settings dialog (tabbed: hotkeys, LLM, TTS, dictate, converse, advanced)
├── hud.py               # conversation-mode HUD overlay
├── llm.py               # OpenAI-compatible HTTP client (streaming SSE)
└── services/
    ├── __init__.py      # service factory (create_services)
    ├── base.py          # Protocol definitions (SpeechService, InsertService, LLMService)
    ├── local.py         # local implementations wrapping existing modules
    └── direct.py        # DirectLLMService (calls LLM API directly, with streaming)
```

## Audio hardware and environment

Like any speech application, AverVOX OSS depends on the microphone and acoustic
environment you use. Recognition quality varies with hardware and room conditions
- software tuning can help, but it cannot fully compensate for a poor signal at
the source.

- **Microphone quality** - built-in laptop mics and basic consumer headsets are
  often fine in quiet rooms; a dedicated USB microphone or a headset with a boom
  mic usually improves Dictate and Converse accuracy.
- **Background noise** - fans, traffic, open windows, and nearby conversations
  increase transcription errors and can cause premature end-of-turn detection.
  A quieter space, or a noise-isolating headset, makes a noticeable difference.
- **Room acoustics** - hard, echoey surfaces (tile, bare walls, large empty
  rooms) blur speech and confuse voice-activity detection. Soft furnishings and
  closer mic placement help.
- **Input level and distance** - speak at a steady distance; avoid clipping
  (input too loud) or levels so low that speech falls below VAD thresholds.

Adjust **Settings -> Dictate** (VAD sensitivity, interim pause) and
**Settings -> Converse** (silence timeout, re-arm delay) to match your setup.
For persistent difficulty in noisy conditions, try a larger STT model
(`small` or `medium` in `config.yaml` -> `stt.model`).

## Performance tuning

Converse mode latency comes from several stages. The table below shows the
defaults and conservative alternatives if the defaults feel too aggressive.
Dictate interim inserts and Converse end-of-turn both use `silence_duration_ms`
(configurable in **Settings -> Dictate**).

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
- For the fastest possible turns at the cost of some accuracy, use `stt.model: tiny`
  with `beam_size: 1`.

## Troubleshooting

- **Logs**: `~/.local/share/avervox/avervox.log`
- **No audio**: Run `avrvx --listen` to test capture in isolation
- **Hotkey not working**: Check `journalctl --user -f` for pynput/X11 errors
- **ALSA errors**: AverVOX OSS auto-detects PulseAudio; ensure `pulseaudio` or
  `pipewire-pulse` is running
- **Converse not working**: Open Settings, verify the test button shows a green
  checkmark and models are listed. Check the log for `LLM error` entries.
- **Garbled or incomplete transcription**: Reduce background noise, move closer
  to the mic, or try a better microphone; lower VAD sensitivity or increase
  interim pause in **Settings -> Dictate**; consider `stt.model: small` or
  `medium` for difficult audio.
- **Converse ends too soon or misses speech in noise**: Increase
  `silence_duration_ms` and/or `silence_timeout_ms`; use headphones to limit
  speaker bleed in loud environments.
