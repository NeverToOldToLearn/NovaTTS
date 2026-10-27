# NovaTTS — Release Notes

*All 11 functions are back. Same app, smoother than before.*

The previous round of breakage is fully resolved: every tab, the audio editor and the
OpenAI-compatible endpoint are working again. Everything runs **100% local** — no cloud,
no subscription, nothing leaves your machine.

---

## What it does

NovaTTS is a local, offline text-to-speech system for Windows. It takes text and turns it
into natural speech using **Qwen3 TTS** (built on top of qwentts.cpp), with **Whisper.cpp**
available for speech-to-text. You can clone your own voices, load royalty-free voices, and
drive it from anywhere.

### Auto-forward (ready and tested)
The app watches the clipboard for dialogue lines (RenPy-style `copy_text_to_clipboard`) and
speaks them automatically, snapping to the right voice from your mapping. Works out of the
box with:

- **Luna Hook** — hooks Unity games and hands text to the clipboard; NovaTTS reads it and speaks.
- **Any app with a text to speech option** — including the built-in TTS of browsers and other tools.
- **OpenAI-compatible clients** — see below.

### OpenAI-compatible endpoint (no setup required)
NovaTTS exposes a drop-in OpenAI `/v1/audio/speech` endpoint. Point any app that supports
OpenAI's TTS API at it and it just works — **Open-WebUI included**, plus any text-to-speech
app you can think of. No extra configuration, no token, no proxy.

| Field | Value |
| --- | --- |
| Base URL | `http://127.0.0.1:8765/v1/audio/speech` |
| Method | `POST` |
| Models | `nova-fast`, `nova-balanced`, `nova-expressive` |
| Output formats | `mp3`, `opus`, `aac`, `flac`, `wav`, `pcm` |

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"nova-balanced","input":"Hello, world!","voice":"default","response_format":"mp3"}'
```

> Heads-up: the server is **always running in the background** while NovaTTS is up. It uses
> GPU (CUDA/AMD), RAM and CPU. If you want manual control instead of auto-forward, simply
> **turn the server off** (menu -> stop) and copy/paste the text yourself.

### Languages & voices
**11 languages supported, including Mandarin.** The model is language-agnostic: a single
voice can speak many languages. So yes — every voice can do Dutch too, and Mandarin too.
It's not perfect across every combination, but it's a long way past the "kid yelling at a
mic" baseline. Give it a sample, let it learn, and it'll match.

### Perfect Cut & Per Cut — your audio, tamed
- **Perfect Cut** — a built-in audio editor with a spectrum analyzer. Open any `.wav`, cut
  out exactly the piece you need, and export a clean file.
- **Per Cut** — weird cut-offs in your output? Per Cut trims silence **fully automatically**,
  snapping to the first "still moment" and cutting right where it matters.

### Batch tab
The batch tab does more than convert files:

- Converts `.wav` samples into the format Qwen3 TTS likes best.
- Transcribes voice sentences.
- Converts them into `.spk` / `.rvq` format, **skipping almost all loose `.wav` files** and
  offloading the work to the GPU.
- Cleans up stray `.wav` files automatically so your Samples folder stays tidy.

### Block list
Don't like how "Anny" says something? Put her on the list. Add your own list of words, and
toggle prefixes for **days, months, time of day, UI elements** and more. When a word is
filtered, the **live-log tells you exactly what got removed** — so you always know what the
app heard.

### VoiceDesign tab (disabled by default)
This is the easiest way to create **royalty-free voices that actually sound good** — you just
download a `CustomVoice` Qwen `.gguf` and enable the tab. Auto-play advances only when a
sentence has finished playing, and the app keeps an eye on the game so it never speaks while
you're mid-action.

---

## Installation — what to expect

NovaTTS ships three ways, all living on your **C: drive** (nothing mandatory in the dev
folder):

1. **Setup .exe** — a small Inno Setup installer (no `.venv`/`node_modules`). Optional
   "run setup now" task; otherwise it self-heals on first launch.
2. **Portable ZIP** — unzip anywhere, run `Install.cmd`, then `start_all.cmd`. No registry.
3. **Full payload** — bundles `.venv` + `node_modules` so it runs immediately.

The installer takes care of the heavy lifting: it **checks whether `qwen3tts.cpp` is
installed** (and builds/clones it if not) and pulls in **`whisper.cpp`** as a handy bonus.
It also ensures the Python venv and the Svelte/Vite GUI are ready.

**Storage:** plan for the models — the Qwen3-TTS models are large (~2 GB each), plus the
Whisper model. Keep some spare room on your hard drive to fit them.

### Quick start
```bash
# After installing, from the install folder:
start_all.cmd          # launches backend (:8765) + GUI (tauri window, or http://localhost:1420)
start_all.cmd --min    # windowless; logs to backend.log / gui.log
start_all.cmd --visible # console windows for debugging
```

The backend auto-starts Qwen and auto-imports your cloned samples (background, ~1-2 min).
The dashboard shows progress.

---

## Special thanks

- **ServeurpersoCom** for providing qwentts.cpp: https://github.com/ServeurpersoCom/qwentts.cpp
- **Team Qwen3** for such a capable model with so little overhead.
- **OpenCode and Muse/Meta AI** — without AI this project would never have seen the light of
  day. Big shoutout for keeping me going.

## License

**MIT licensed** — do whatever you want with it.

---

## Disclaimer

I will not be held responsible for the content **you** create using this software. If you
think to yourself, "is this too far?" — then yes, the answer is yes. Or not. Who cares,
because the best thing is: **it's all local.**

Star the repo if you'd like to get the app noticed. Now go make some voices.
