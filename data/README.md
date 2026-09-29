# `data/` — runtime-config

All of this is plain config, no audio. **NovaTTS ships no sound fragments of
its own** — the emotion sounds are yours to supply, because the audio comes
from wherever you got it and that is a copyright question for you, not for
this project.

Point the app at a folder of your own files under **Instellingen → Emotion
sounds** (or `NOVATTS_EMOTION_SOUNDS_DIR` in `backend/.env`). `.wav`,
`.ogg`, `.opus` and `.mp3` are picked up; the filename without extension
becomes the tag.

## Which files are tracked and which are not

| File | Tracked | What it is |
| --- | --- | --- |
| `emotion_patterns.json` | yes | Shared defaults: regex → tag. Safe to edit, keep it if you like it. |
| `speakers.json` | yes | Speaker → voice/instruct mapping. |
| `blacklist.json` | yes | Text replacements. |
| `active_game.json` | yes | Which game is currently selected. |
| `emotion_sound_map.json` | **no** | Cache of your sound folder. Generated, rewritten on every reload. |
| `emotion_aliases.json` | **no** | Your own phrase → tag mappings. |
| `games/*/speakers.json` | **no** | Per-game voice casting. |
| `perfect_cut.json` | **no** | Perfect Cut tool settings. |

Everything in the "no" column is local: it describes *your* audio library or
*your* per-game setup, so it is not pushed and not put in a release build.
Each one is created automatically the first time the app needs it, so a fresh
clone works without them.

## The two generated emotion files

Neither file needs to exist — the app creates both on first run. If you want
to pre-seed them, copy the example next to it:

```
data/emotion_sound_map.json.example   ->  data/emotion_sound_map.json
data/emotion_aliases.json.example     ->  data/emotion_aliases.json
```

### `emotion_sound_map.json`

`"tag": "filename"`, both relative to your sounds folder. You normally never
need this file: the folder is scanned on startup and on **Reload from disk**,
and this file is rewritten to match. It is worth editing only to give a sound a
second name, which is how the `chuckle` → `chuckles.wav` example above works.
Entries pointing at a file that no longer exists are dropped on the next reload.

### `emotion_aliases.json`

`"phrase": "tag"`, where `tag` must be a key in the sound map. The phrase is
matched case-insensitively; `*phrase*` matches inside a line. This is the
"Add Emotion Mapping" form in the GUI, and it is what turns written dialogue
into a sound. Every tag used here is a key in `emotion_sound_map.json.example`
so the example resolves end to end.

### `emotion_patterns.json`

A list of `{"pattern": "<regex>", "tag": "<tag>"}` and is used two ways: tags
drive the emotion overlay, and the bare patterns are used by the text cleaner
to strip the leftovers. `"tag": null` means "match but play nothing", which is
how sound-effect words get removed from the text without noise. The default
set is a reasonable starting point for Dutch and English.

## What the hook route changes in this folder

Since F8 the hook is the **default** input route rather than the optional one,
so this section applies to a fresh install without you configuring anything.
Almost nothing changes on disk — and the one thing that does is worth knowing
before you wonder why a name showed up in your speakers.

**No hook-specific file is ever written here.** The hook is configured entirely
in `backend/.env` (`NOVATTS_HOOK_*`), not in `data/`, so there is nothing here to
clean up and nothing to back up when you switch between the clipboard and the
websocket route.

**`speakers.json` can grow while you play.** When a line arrives over the hook
and its speaker is *stated* — `"Rick: Hello"` — NovaTTS registers that name with
the default voice so it can speak from the very next line, instead of waiting
for you to add it by hand. The **Characters** tab reads the registry live, so
reloading that tab is enough to see it; there is nothing to restart. The file on
disk catches up within about half a minute, and always when NovaTTS closes
cleanly — so do not be surprised if a name you just heard is not in the file
immediately after a crash.

It is deliberately conservative about *guessed* names. Textractor's space form
(`Rick Hello`, no colon) makes it genuinely ambiguous whether `Rick` is the
speaker, so those lines are **not** registered — you get audio with a fallback
voice rather than a registry polluted with every fragment of a sentence. Only
`Name: Text` and the JSON form (`{"name": …, "text": …}`) register. Same rule on
all routes, so turning the hook on does not quietly change what your registry
contains.

Everything else in this folder is route-independent: `blacklist.json`,
`emotion_patterns.json`, the generated emotion files and `games/*/speakers.json`
behave identically no matter where the text came from.
