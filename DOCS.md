# AverVOX OSS - Documentation
Technical reference for AverVOX OSS (free).
Website Edition
version: 0.5.5

For a quick overview and install, see
[README.md](README.md).

**New users:** [QUICK_START-OSS.md](QUICK_START-OSS.md) walks through the tray app and every Settings tab.

> **Naming note:** the product is **AverVOX**; the Python package and command are **`avrvx`** (`pip install avrvx`). Starting with 0.5.5, the `avervox` command is installed as an alias, and `pip install avervox` resolves to `avrvx` via an alias package.

## Edition matrix

| Feature | Free | Pro |
|---------|:----:|:---:|
| Dictate (`Ctrl+Alt+Space`) | Yes | Yes |
| Speak selection (`Ctrl+Alt+S`) | Yes | Yes |
| Converse (`Ctrl+Alt+C`) | Yes | Yes |
| CLI (`avrvx --listen`, `--speak`) | Yes | Yes |
| Bridge CLI (`--synthesize`, `--transcribe`, `--capabilities`) | Yes | Yes |
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
| Dashboard (endpoints, models, profiles) | | Yes |

Pro-only features (Kokoro TTS, wake word, session memory, LAN, and more) are
listed in the edition matrix above. AverVOX Pro is distributed separately - not
on GitHub or PyPI. See [avervoxpro.com](https://avervoxpro.com/).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Activation                                                      │
│    Hotkeys (pynput)                                              │
│                                                                  │
│    Ctrl+Alt+Space  ->  record -> STT -> insert_text()   (Dictate)│
│    Ctrl+Alt+S      ->  get_selection() -> TTS -> play   (Speak)  │
│    Ctrl+Alt+C      ->  listen -> STT -> LLM -> TTS <-   (Converse)│
└──────────────────────────────────────────────────────────────────┘
│ Services layer (SpeechService, InsertService, LLMService)        │
│   STT: faster-whisper, TTS: piper, LLM: httpx -> OpenAI API      │
├──────────────────────────────────────────────────────────────────┤
│ STT: faster-whisper (local, CPU/GPU auto, int8)                   │
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

Alternatively, `pip install avrvx` installs the package (the PyPI package is
named `avrvx`; `pip install avervox` also resolves to it via the alias
package); you still need system dependencies (GTK, xdotool, xclip, portaudio) -
see `install.sh` for the full list.

## GUI usage

```bash
avrvx
```

Starts the system tray icon with hotkeys active. A desktop notification
confirms "AverVOX OSS" / "Ready — hotkeys active". No window - just the tray.

Right-click the tray icon for:

- **LLM: (active profile)** - switch between LLM profiles
- **Reload config** - re-read `config.yaml` without restarting
- **Settings...** - open the full settings dialog
- **Copy Last Response** - copy the most recent LLM response to the clipboard
- **Open Log** - open `avervox.log` in your default text viewer
- **About AverVOX OSS** - version, tagline, and links
- **Quit AverVOX OSS**

## Bridge CLI

Three commands let other programs use AverVOX as their local speech engine.
Unlike `--speak` and `--listen`, they exchange files and JSON instead of
driving the speakers and microphone directly.

```bash
# Synthesize to a WAV file instead of playing it
avrvx --synthesize --text "Deployment complete" --output /tmp/reply.wav
avrvx --synthesize --text-file /tmp/reply.txt --output /tmp/reply.wav
echo "Deployment complete" | avrvx --synthesize --text - --output /tmp/reply.wav

# Transcribe an existing recording or voice message
avrvx --transcribe /tmp/voice-message.ogg

# Ask what this install can do (JSON on stdout)
avrvx --capabilities
```

| Command | Behaviour |
|---------|-----------|
| `--synthesize` | Requires `--output PATH`, or `--output -` to stream raw PCM to stdout. Writes mono 16-bit PCM WAV at the engine's sample rate, mode `0600`, and prints the path on stdout. The output directory must already exist. Exits 2 without `--output`, 1 with no text, 130 when stopped by `SIGTERM`. |
| `--transcribe AUDIO` | Prints the transcript on stdout; exits 1 when no speech was found. Any format ffmpeg can decode works. |
| `--capabilities` | Prints a JSON object on stdout. Diagnostics go to stderr, so piping into a parser is always safe. |
| `--daemon` | Keeps the models loaded and serves the commands above over a Unix socket. See [Warm bridge daemon](#warm-bridge-daemon). |

`--voice NAME` and `--speed N` override the configured defaults for one call.
`--capabilities` lists the installed voices under `tts.voices` so a host can
render a picker.

Text sources for `--synthesize`, in priority order: `--text-file PATH`,
`--text "literal"`, `--text -` (stdin), or bare stdin when it is not a TTY.
Prefer a file or stdin for anything sensitive - command-line arguments are
visible to other users in the process list.

`--capabilities` output:

```json
{
  "product": "avervox-oss",
  "edition": "oss",
  "licensed": true,
  "version": "0.5.5",
  "cli": "avrvx",
  "tts": {"engines": ["piper"], "active_engine": "piper", "synthesize_to_file": true, "formats": ["wav"],
          "voices": [{"engine": "piper", "id": "/home/you/.local/share/piper-tts/voices/en_US-lessac-high.onnx",
                      "name": "en_US-lessac-high"}],
          "active_voice": "/home/you/.local/share/piper-tts/voices/en_US-lessac-high.onnx", "speed": 1.0},
  "stt": {"engine": "faster-whisper", "model": "base", "transcribe_file": true, "listen_mic": true},
  "features": {"speak_playback": true, "listen_mic": true, "synthesize": true, "transcribe": true,
               "serve": false, "wake_word": false, "session_memory": false, "kokoro": false,
               "daemon": true},
  "daemon": {"socket": "/run/user/1000/avervox/bridge.sock", "running": false, "protocol": 1}
}
```

Host integrations read `edition` and `features` to detect OSS versus Pro rather
than shipping separate builds. Treat these field names as a stable contract.
Ready-made integration packages for Hermes Agent and OpenClaw, plus an
Odysseus guide, are published at
[github.com/avrvx/AverVOX-Integrations](https://github.com/avrvx/AverVOX-Integrations).

### Streaming to stdout

`--output -` writes headerless mono PCM16 to stdout as it is generated and
announces the format on stderr before the first sample, so audio starts playing
after the first sentence rather than after the whole passage:

```bash
avrvx --synthesize --text-file reply.txt --output - | aplay -f S16_LE -r 22050 -c 1
```

Read the rate off stderr instead of assuming one: Piper's medium voices run at
22050 Hz and its low voices at 16000 Hz.

### Warm bridge daemon

Every `avrvx` call pays for a Python start plus a model load before it produces
a sample, which a program speaking every reply pays on every turn.
`avrvx --daemon` pays it once and serves the same commands over a Unix socket
at `$XDG_RUNTIME_DIR/avervox/bridge.sock`, created mode `0600` inside a `0700`
directory. The protocol is newline-delimited JSON — `capabilities`,
`synthesize`, `transcribe`, `cancel`, `ping` — with an optional framed
streaming mode for `synthesize`, documented in full in the
[integrations README](https://github.com/avrvx/AverVOX-Integrations#warm-bridge-optional).

The daemon is purely an optimisation. Both integration packages try the socket
first and fall back to spawning `avrvx`, so the CLI stays the authoritative
contract and nothing breaks if you never start it.

### Setting up a host application

`--install-integration` writes the speech configuration for a supported host
and then checks the result by synthesizing real audio, which catches the usual
causes of "I pasted the config and nothing happens" — `avrvx` not on `PATH`, or
no voice installed:

```bash
avrvx --install-integration hermes     # or: openclaw
```

An existing host configuration is never modified. If one is already present the
snippet is written alongside it to merge by hand, and the command says so. It
exits non-zero when synthesis fails, so a provisioning script can rely on it.

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
  device: auto       # auto | cpu | cuda

tts:
  voice_model: ~/.local/share/piper-tts/voices/en_US-lessac-high.onnx

audio:
  vad_aggressiveness: 2      # 0-3 (higher = more aggressive silence detection)

dictate:
  interim_pause_ms: 1000     # pause before dictation insert (Settings -> Dictate)

backends:
  text_inserter: xdotool     # xdotool | ydotool - Settings -> Advanced
  selection_provider: xclip  # xclip | xsel | wl-paste

converse:
  end_of_turn_ms: 1100             # pause after you stop speaking (Settings -> Converse)
  silence_timeout_ms: 7000         # silence before ending conversation (ms)
  rearm_delay_ms: 250              # pause after TTS before mic reopens (ms)
  early_listen_ms: 300             # pre-open mic before TTS ends (headphones only)
  goodbye_phrases:
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

Most users only need to configure the `llm` section (via the Settings dialog)
to enable Converse mode. You can add multiple profiles and switch between them
from the tray menu.

**Backward compatibility:** Old flat-format `llm:` configs (with `api_base`
directly under `llm:`) are automatically migrated to a single profile on first
load. Legacy `audio.silence_duration_ms` migrates to `dictate.interim_pause_ms`
and `converse.end_of_turn_ms`.

API keys are masked in Settings and stored encrypted in `config.yaml`. Plaintext
keys from older configs still load until you save settings again.

## Source layout

```
src/avervox/
├── __init__.py          # package metadata
├── __main__.py          # CLI entry point (--listen, --speak, --synthesize, --transcribe, --capabilities, --daemon, --version, or GUI)
├── main.py              # GUI controller (state machine, hotkey handlers, notifications)
├── config.py            # configuration loading, LLM profiles, dataclasses
├── audio.py             # microphone capture + VAD/recorder + interrupt monitor
├── stt.py               # speech-to-text (faster-whisper)
├── tts.py               # text-to-speech engine (Piper), markdown stripping
├── text.py              # sentence splitting shared by the LLM stream and TTS
├── bridge_server.py     # avrvx --daemon: Unix-socket speech server for host apps
├── integration_install.py  # avrvx --install-integration: host config + self-check
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

| Setting | Default | Conservative | Where | Effect |
|---------|---------|-------------|-------|--------|
| `dictate.interim_pause_ms` | **1000** | 1500 | Settings -> Dictate | Dictate: pause before typing an interim chunk. |
| `converse.end_of_turn_ms` | **1100** | 1500 | Settings -> Converse | Converse / `avrvx --listen`: end-of-turn delay. |
| `rearm_delay_ms` | **250** | 500 | `config.yaml` -> `converse` | Pause after TTS finishes before the mic reopens. Prevents echo/feedback. |
| `silence_timeout_ms` | **7000** | 10000 | `config.yaml` -> `converse` | How long to wait with no speech before ending the conversation. |
| STT `beam_size` | **1** | 5 | `stt.py` | Greedy (1) is faster; beam search (5) is more accurate for mumbled or technical speech. |
| STT model | **base** | tiny / small | `config.yaml` -> `stt.model` | `tiny` is fastest, `small`/`medium` more accurate. `base` is a good middle ground. |

**Tips:**

- If Converse turns get clipped (cut off mid-sentence), increase `converse.end_of_turn_ms`.
- If you hear echo (AverVOX OSS responding to its own TTS), increase `rearm_delay_ms`.
- For the fastest possible turns at the cost of some accuracy, use `stt.model: tiny`
  with `beam_size: 1`.

## LLM model health & failure detection

During Converse, AverVOX monitors each LLM stream and reacts when a model
misbehaves, so you are not left waiting in silence for a minute or more.

| Threshold | Default | Defined in | Triggers when |
|-----------|---------|------------|---------------|
| **First-token timeout** | **30 s** | `llm_control.py` → `FIRST_TOKEN_TIMEOUT_S` | No **content** token within this time after the request is sent. Empty SSE keepalive chunks do not count. |
| **Empty response** | **30 s** | `EMPTY_RESPONSE_MIN_S` | Stream finishes with zero usable content after at least this long. |
| **Stream read stall** | **90 s** | `STREAM_READ_TIMEOUT_S` | No SSE bytes at all for this long. |

On failure, the request is aborted, the model is unloaded, and the model is
disabled for the rest of the app session. **The next time you start AverVOX**,
all `disabled_models` entries are cleared automatically.

## Troubleshooting

- **Logs**: `~/.local/share/avervox/avervox.log`
- **No audio**: Run `avrvx --listen` to test capture in isolation
- **Hotkey not working**: Check `journalctl --user -f` for pynput/X11 errors
- **ALSA errors**: AverVOX OSS auto-detects PulseAudio; ensure `pulseaudio` or
  `pipewire-pulse` is running
- **Converse not working**: Open Settings, verify the test button shows a green
  checkmark and models are listed. Check the log for `LLM error` entries.
- **Model greyed out / disabled**: A failure threshold tripped — see **LLM model
  health & failure detection** above; check `disabled_models` in config and the
  log for `LLM model failure`.
- **Garbled or incomplete transcription**: Reduce background noise, move closer
  to the mic, or try a better microphone; lower VAD sensitivity or increase
  interim pause in **Settings -> Dictate**; consider `stt.model: small` or
  `medium` for difficult audio.
- **Converse ends too soon or misses speech in noise**: Increase
  `converse.end_of_turn_ms` and/or `silence_timeout_ms`; use headphones to limit
  speaker bleed in loud environments.
