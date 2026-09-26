<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";
  import { openCutter } from "../cutter/tauri";
  import type { PathStatus, SettingsData, SettingsResponse } from "../types";

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
