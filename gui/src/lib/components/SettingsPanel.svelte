<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";
  import { openCutter } from "../cutter/tauri";
  import type { HookMode, PathStatus, SettingsData, SettingsResponse } from "../types";

  let data: SettingsResponse | null = $state(null);
  let form: Partial<SettingsData> = $state({});
  let pathStatus: Record<string, PathStatus> = $state({});
  let err = $state("");
  let info = $state("");
  let saving = $state(false);
  let testing = $state(false);
  let converting = $state(false);
  let convertForce = $state(false);

  const load = async () => {
    try {
      const raw = await api.settings();
      // Robust fallback: settings response structure may vary
      const response = raw as any;
      data = {
        settings: response?.settings || response || {},
        path_status: response?.path_status || {},
        env_file: response?.env_file || "unknown",
      };
      form = { ...data.settings };
      pathStatus = data.path_status || {};
      err = "";
    } catch (e) {
      err = `Failed to load settings: ${(e as Error).message}`;
      console.error("Settings load error:", e);
      data = null;
      // Provide empty fallback so UI doesn't break
      form = {};
      pathStatus = {};
    }
  };

  const save = async () => {
    saving = true; err = ""; info = "";
    try {
      const res = await api.updateSettings(form);
      info = "Settings saved to .env — restart backend/Qwen to apply.";
      pathStatus = res.path_status;
      form = { ...res.settings };
    } catch (e) {
      err = (e as Error).message;
    }
    saving = false;
  };

  const testTts = async () => {
    testing = true; err = ""; info = "";
    try {
      await api.testTts();
      info = "TTS test OK — audio queued.";
    } catch (e) {
      err = (e as Error).message;
    }
    testing = false;
  };

  const openLog = async () => {
    err = "";
    try {
      const r = await api.openClipboardLog();
      info = `Opened raw clipboard log: ${r.path}`;
    } catch (e) {
      err = (e as Error).message;
    }
  };

  const clearLog = async () => {
    err = "";
    try {
      await api.clearClipboardLog();
      info = "Raw clipboard log cleared.";
    } catch (e) {
      err = (e as Error).message;
    }
  };

  const convertSamples = async () => {
    converting = true; err = ""; info = "";
    try {
      const r = await api.convertSamples(convertForce);
      if (r.failed > 0) {
        err = `${r.failed} conversion(s) failed: ${(r.errors ?? []).slice(0, 3).join(" | ")}`;
      }
      info = `Converted ${r.converted}/${r.total} wav(s), skipped ${r.skipped}. Pairs available: ${r.import_status?.pairs ?? "?"} (unpaired: ${r.import_status?.unpaired ?? "?"}). Restart Qwen engine to register them.`;
    } catch (e) {
      err = (e as Error).message;
    }
    converting = false;
  };

  const openPerfectCut = async () => {
    err = ""; info = "";
    try {
      const wasOpen = await openCutter();
      info = wasOpen
        ? "Perfect Cut was already open — brought to the front."
        : "Perfect Cut opened in its own window.";
    } catch (e) {
      err = (e as Error).message;
    }
  };

  const exists = (key: string) => pathStatus[key]?.exists ?? false;

  onMount(load);
</script>

<section class="panel">
  <header class="page-head">
    <div>
      <h2>Settings</h2>
      <p class="subtitle">Qwen engine paths, samples dir, general config</p>
    </div>
    <span class="pill">{data?.env_file ?? "…"}</span>
  </header>

  {#if err}<p class="callout error">{err}</p>{/if}
  {#if info}<p class="callout info">{info}</p>{/if}

  <div class="section">
    <h3>Qwen Engine</h3>
    <div class="form-grid">
      <label class="field-row">
        <span class="fk">tts-server binary</span>
        <div class="fv">
          <input class="field" bind:value={form.qwen_bin} placeholder="path to tts-server.exe" />
          <span class="dot" class:ok={exists("qwen_bin")}>{exists("qwen_bin") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Model (.gguf)</span>
        <div class="fv">
          <input class="field" bind:value={form.qwen_model} placeholder="path to model" />
          <span class="dot" class:ok={exists("qwen_model")}>{exists("qwen_model") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Codec (.gguf)</span>
        <div class="fv">
          <input class="field" bind:value={form.qwen_codec} placeholder="path to codec" />
          <span class="dot" class:ok={exists("qwen_codec")}>{exists("qwen_codec") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">qwen-codec binary</span>
        <div class="fv">
          <input class="field" bind:value={form.qwen_codec_bin} placeholder="auto = next to tts-server.exe" />
          <span class="dot" class:ok={exists("qwen_codec_bin")}>{exists("qwen_codec_bin") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Server URL</span>
        <input class="field" bind:value={form.qwen_url} placeholder="http://127.0.0.1:8080" />
      </label>
      <label class="field-row">
        <span class="fk">Default voice</span>
        <input class="field" bind:value={form.qwen_default_voice} placeholder="empty = model built-in voice" />
      </label>
      <label class="field-row">
        <span class="fk">Extra args</span>
        <input class="field" bind:value={form.qwen_extra_args} placeholder="--alias qwen3-tts" />
      </label>
      <label class="field-row">
        <span class="fk">Timeout (s)</span>
        <input class="field sm" type="number" bind:value={form.qwen_timeout} min="10" max="600" step="10" />
      </label>
    </div>
  </div>

  <div class="section">
    <h3>Voice Samples</h3>
    <div class="form-grid">
      <label class="field-row">
        <span class="fk">Samples directory</span>
        <div class="fv">
          <input class="field" bind:value={form.qwen_samples_dir} placeholder="D:\!!Scripts!!\Samples_Clone" />
          <span class="dot" class:ok={exists("qwen_samples_dir")}>{exists("qwen_samples_dir") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Extra dirs (comma-sep)</span>
        <input class="field" bind:value={form.qwen_samples_dirs_extra} placeholder="optional, comma separated" />
      </label>
    </div>
    <p class="muted small">Pre-extract <code>.spk</code>/<code>.rvq</code> pairs met qwen-codec.exe: importeert sneller bij elke Qwen-start (geen GPU-extractie per stem meer). Wavs zonder pair vallen terug op server-side extractie. Eenmaal omgezet mag de <code>.wav</code> zelfs weg — het paar alleen volstaat.</p>
    <div class="actions">
      <button class="ghost" onclick={convertSamples} disabled={converting}>
        {converting ? "Converting…" : "Pre-extract .spk/.rvq"}
      </button>
      <label class="chk"><input type="checkbox" bind:checked={convertForce} disabled={converting} /> force (alle, ook bestaande)</label>
    </div>
  </div>

  <div class="section">
    <h3>Text hook</h3>
    <p class="muted small">
      NovaTTS listens on <code>ws://{form.hook_host}:{form.hook_port}</code>. In
      LunaTranslator add <code>textractor_websocket_x64.xdll</code> and point it
      at that address. Leave translation off — NovaTTS wants the original line.
      The bind address is read-only because it is the socket the server binds;
      changing it live would mean rebinding underneath a live connection.
    </p>
    <div class="form-grid">
      <label class="field-row">
        <span class="fk">Source</span>
        <select
          class="field"
          value={form.hook_mode ?? "websocket"}
          onchange={(e) => (form.hook_mode = (e.target as HTMLSelectElement).value as HookMode)}
        >
          <option value="websocket">Hook only (LunaTranslator) — the default</option>
          <option value="both">Both — hook first, clipboard as backup</option>
          <option value="clipboard">Clipboard only (RenPy, legacy)</option>
        </select>
      </label>
      <!--
        The legacy route keeps a visible, working option rather than being
        buried in backend\.env. D1 keeps the RenPy code as a fallback, and a
        fallback a user cannot find is not a fallback -- someone on RenPy
        would conclude their game is broken. The badge says what it is
        instead of pretending otherwise.
      -->
      {#if form.hook_mode === "clipboard"}
        <p class="muted small">
          Legacy route: NovaTTS reads the RenPy <code>copy_voice_to_clipboard</code>
          output. It still works and is still tested. Choose this only if your game
          has no hook — with LunaTranslator available, “Hook only” gives you live
          text, a speaker per turn and the multi-speaker split that the clipboard
          form cannot express.
        </p>
      {/if}
      <label class="field-row">
        <span class="fk">Hook port</span>
        <input class="field sm" type="number" bind:value={form.hook_port} min="1" max="65535" />
      </label>
      <label class="field-row">
        <span class="fk">Bind address</span>
        <div class="fv">
          <input class="field" value={form.hook_host ?? ""} readonly />
          <span class="muted small">restart required</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Outgoing ws URL</span>
        <input class="field" bind:value={form.luna_ws_url} placeholder="empty = listen; ws://host:port = connect out" />
      </label>
      <!-- A div, not a <label>: the toggle below is a label of its own and
           nesting labels is invalid HTML. The browser un-nests them silently,
           and the path field then stops toggling the checkbox. -->
      <div class="field-row">
        <span class="fk">File watch</span>
        <div class="fv">
          <input
            class="field"
            bind:value={form.file_watch_path}
            placeholder="textractor_output.txt"
            disabled={!form.file_watch}
          />
          <label class="chk"><input type="checkbox" bind:checked={form.file_watch} /> on</label>
        </div>
      </div>
      <label class="chk-row">
        <input type="checkbox" bind:checked={form.hook_space_form} />
        <span>Space form — Textractor sends <code>Rick It's 2 parts.</code> rather than <code>Rick: …</code></span>
      </label>
      <label class="chk-row">
        <input type="checkbox" bind:checked={form.hook_dual_hook} />
        <span>Dual hook — buffers a bare name and merges it with the next line</span>
      </label>
      <label class="field-row">
        <span class="fk">Dedup window (ms)</span>
        <input class="field sm" type="number" bind:value={form.dedup_window_ms} min="0" max="5000" step="50" />
      </label>
    </div>
    <p class="muted small">
      Source and port are read once at start, so they need a backend restart —
      same rule as the bind address. Everything below them is read per line.
    </p>
  </div>

  <div class="section">
    <h3>Misc</h3>
    <div class="form-grid">
      <label class="field-row">
        <span class="fk">Emotion sounds dir</span>
        <div class="fv">
          <input class="field" bind:value={form.emotion_sounds_dir} placeholder="C:\Piper\emotion_sounds" />
          <span class="dot" class:ok={exists("emotion_sounds_dir")}>{exists("emotion_sounds_dir") ? "✓" : "✗"}</span>
        </div>
      </label>
      <label class="field-row">
        <span class="fk">Clipboard poll (s)</span>
        <input class="field sm" type="number" bind:value={form.poll_interval} min="0.05" max="2" step="0.05" />
      </label>
    </div>
  </div>

  <div class="actions">
    <button onclick={save} disabled={saving}>{saving ? "Saving…" : "Save to .env"}</button>
    <button class="ghost" onclick={testTts} disabled={testing}>{testing ? "Testing…" : "Test TTS"}</button>
    <button class="ghost" onclick={load} disabled={saving || testing}>Reload</button>
  </div>

  <div class="section">
    <h3>Tools</h3>
    <p class="muted small">Perfect Cut is a separate window — it is deliberately not in the sidebar, so it stays out of the way until you are prepping samples.</p>
    <div class="actions">
      <button class="ghost" onclick={openPerfectCut}>Open Perfect Cut</button>
    </div>
  </div>

  <div class="section">
    <h3>Clipboard raw log</h3>
    <p class="muted small">Every clipboard capture is written verbatim before any filtering, so you can copy the exact source text when tuning regex/filters (e.g. variable-length “aaaah”).</p>
    <div class="actions">
      <button onclick={openLog}>Open log</button>
      <button class="ghost" onclick={clearLog}>Clear</button>
    </div>
  </div>
</section>

<style>
  .panel{ display:flex; flex-direction:column; gap:1rem; max-width:860px; }
  .page-head{ display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; align-items:flex-start; }
  .page-head h2{ margin:0; font-size:1.25rem; letter-spacing:-0.02em; } .subtitle{ margin:0.2rem 0 0; color:#8b8e9a; font-size:0.82rem; }
  .pill{ align-self:center; background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.35rem 0.75rem; font-size:0.72rem; font-family:ui-monospace,monospace; color:#8b8e9a; white-space:nowrap; max-width:340px; overflow:hidden; text-overflow:ellipsis; }
  .callout{ margin:0; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; word-break:break-word; }
  .callout.error{ background:#2a1f24; border:1px solid #3a2a2e; color:#ffb4b4; } .callout.info{ background:#1c2330; border:1px solid #2a3550; color:#a8b8e6; }
  .muted{ color:#8b8e9a; } .small{ font-size:0.8rem; }
  .chk{ display:flex; align-items:center; gap:0.4rem; font-size:0.82rem; color:#8b8e9a; cursor:pointer; }
  .chk input{ accent-color:#3b4b8f; }
  .chk-row{ display:flex; align-items:flex-start; gap:0.5rem; font-size:0.83rem; color:#b6b8c0; cursor:pointer; line-height:1.35; }
  .chk-row input{ accent-color:#3b4b8f; margin-top:0.15rem; }
  select.field{ cursor:pointer; }
  input.field:read-only{ color:#8b8e9a; background:#191a20; }
  .section{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:0.75rem; }
  .section h3{ margin:0; font-size:0.95rem; letter-spacing:-0.01em; color:#e8e8ec; }
  .form-grid{ display:flex; flex-direction:column; gap:0.65rem; }
  .field-row{ display:flex; flex-direction:column; gap:0.2rem; cursor:default; }
  .fk{ font-size:0.78rem; color:#8b8e9a; font-weight:550; text-transform:uppercase; letter-spacing:0.04em; }
  .fv{ display:flex; gap:0.5rem; align-items:center; }
  .fv .field{ flex:1; }
  .field{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; line-height:1.2; width:100%; font-family:ui-monospace,monospace; }
  .field.sm{ max-width:100px; width:auto; flex:0 1 100px; }
  input.field:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  .dot{ font-size:0.8rem; font-weight:700; color:#e5484d; min-width:1.2rem; text-align:center; }
  .dot.ok{ color:#30a46c; }
  .actions{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 1rem; cursor:pointer; font-size:0.88rem; font-weight:550; line-height:1; }
  button:hover:not(:disabled){ background:#4458aa; } button:active:not(:disabled){ background:#35468a; }
  button.ghost{ background:#232634; color:#e8e8ec; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button:disabled{ opacity:0.5; cursor:default; }
</style>
