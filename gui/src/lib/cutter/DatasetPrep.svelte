<script lang="ts">
  // Tab 2 — Dataset Prep (the old VoiceClonePrep-TTS.py).
  //
  // Batch clean (silenceremove + loudnorm → 24 kHz mono PCM16) + whisper
  // transcription, run server-side so it survives closing the window.

  import { onDestroy, onMount } from "svelte";
  import { cutterApi, type BatchInput } from "./api";
  import { pickDir, pickExe, pickModel, openPath } from "./tauri";
  import type { BatchStatus, CutterConfig, CutterTools } from "./types";

  interface Props {
    config: CutterConfig;
    onconfig: (patch: Partial<CutterConfig>) => void;
    onstatus: (msg: string) => void;
  }

  let { config, onconfig, onstatus }: Props = $props();

  const LANGS = ["en", "nl", "de", "fr", "auto"];

  let tools = $state<CutterTools | null>(null);
  let status = $state<BatchStatus | null>(null);
  let logLines = $state<string[]>([]);
  let busy = $state(false);
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  /** Guards the "batch done" status line so it is announced only once. */
  let announced = false;

  const batch = (): BatchInput => ({
    input_dir: config.input_dir,
    output_dir: config.output_dir,
    whisper_exe: config.whisper_exe,
    whisper_model: config.whisper_model,
    lang: config.lang,
  });

  /**
   * Every field pushes its own new value up. The config object is owned by the
   * shell (CutterApp), which applies the patch locally and debounces the POST,
   * so a held key keeps every character instead of only the first one.
   */
  async function refreshTools() {
    try {
      tools = await cutterApi.tools();
    } catch (e) {
      onstatus(`✗ backend unreachable: ${(e as Error).message}`);
    }
  }

  async function autoDetect() {
    try {
      tools = await cutterApi.autoTools();
      onconfig({
        ffmpeg: tools.ffmpeg,
        whisper_exe: tools.whisper_exe,
        whisper_model: tools.whisper_model,
      });
      onstatus("Re-detected ffmpeg and whisper.");
    } catch (e) {
      onstatus(`✗ ${(e as Error).message}`);
    }
  }

  async function test(tool: "ffmpeg" | "whisper_exe") {
    try {
      const r = await cutterApi.testTool(tool);
      onstatus(`${r.ok ? "✓" : "✗"} ${r.path} — ${r.message}`);
    } catch (e) {
      onstatus(`✗ ${(e as Error).message}`);
    }
  }

  // --- run control ------------------------------------------------------

  async function preflight() {
    try {
      const r = await cutterApi.batchPreflight(batch());
      logLines = r.lines;
      return r.ok;
    } catch (e) {
      logLines = [`✗ ${(e as Error).message}`];
      return false;
    }
  }

  async function start() {
    busy = true;
    announced = false;
    logLines = ["running preflight…"];
    if (!(await preflight())) {
      busy = false;
      onstatus("✗ preflight failed.");
      return;
    }
    try {
      await cutterApi.batchStart(batch());
      onstatus("▶ batch started.");
      startPolling();
    } catch (e) {
      logLines = [...logLines, `✗ ${(e as Error).message}`];
      onstatus("✗ could not start the batch.");
    } finally {
      busy = false;
    }
  }

  async function stop() {
    try {
      await cutterApi.batchStop();
      onstatus("⏹ stop requested — finishing the current file.");
    } catch (e) {
      onstatus(`✗ ${(e as Error).message}`);
    }
  }

  async function poll() {
    try {
      status = await cutterApi.batchStatus();
      if (status.lines.length) logLines = status.lines;
    } catch {
      return; // backend busy — try again on the next tick
    }
    if (status.finished && !announced) {
      announced = true;
      onstatus(`🏁 batch done — ✓ ${status.ok} · ✗ ${status.fail}`);
    }
  }

  /**
   * The timer is started once and left running for the life of the tab. It
   * must NOT be cleared when a job ends: `poll()` is also what re-arms
   * progress for the *next* job, and clearing here used to leave the second
   * batch of a session frozen on its first poll.
   */
  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => void poll(), 500);
  }

  onMount(() => {
    void (async () => {
      await refreshTools();
      await poll();
    })();
    startPolling();
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  });

  // --- pickers ----------------------------------------------------------

  async function browseDir(which: "input_dir" | "output_dir") {
    const p = await pickDir(which === "input_dir" ? "Input dir (wavs)" : "Output dir", config[which]);
    if (p) {
      onconfig({ [which]: p });
      onstatus(`${which} → ${p}`);
    }
  }

  async function browseExe() {
    const p = await pickExe("whisper-cli.exe", config.whisper_exe);
    if (p) onconfig({ whisper_exe: p });
  }

  async function browseModel() {
    const p = await pickModel("Whisper model (.bin)", config.whisper_model);
    if (p) onconfig({ whisper_model: p });
  }

  async function reveal(dir: string) {
    if (!dir) return;
    try {
      await openPath(dir);
    } catch (e) {
      onstatus(`✗ ${(e as Error).message}`);
    }
  }
</script>

<section class="prep">
  <header class="head">
    <div>
      <h2>Dataset Prep</h2>
      <p class="subtitle">Batch clean (silenceremove + loudnorm → 24 kHz mono PCM16) + whisper transcription</p>
    </div>
    {#if status?.running}
      <span class="pill running">{status.index}/{status.total}</span>
    {:else if status?.finished}
      <span class="pill">idle</span>
    {/if}
  </header>

  <div class="panel">
    <h3>Folders</h3>
    <label class="f">
      <span>Input dir (wav)</span>
      <div class="fv">
        <input class="mono" value={config.input_dir} oninput={(e) => onconfig({ input_dir: e.currentTarget.value })} placeholder="D:\Samples_Clone\Done" />
        <button class="ghost" onclick={() => browseDir("input_dir")}>Browse…</button>
      </div>
    </label>
    <label class="f">
      <span>Output dir</span>
      <div class="fv">
        <input class="mono" value={config.output_dir} oninput={(e) => onconfig({ output_dir: e.currentTarget.value })} placeholder="D:\Samples_Clone\Reference" />
        <button class="ghost" onclick={() => browseDir("output_dir")}>Browse…</button>
        <button class="ghost" onclick={() => reveal(config.output_dir)} disabled={!config.output_dir}>Open</button>
      </div>
    </label>
  </div>

  <div class="panel">
    <div class="row">
      <h3>Tools</h3>
      <span class="spacer"></span>
      <button class="ghost sm" onclick={autoDetect}>Auto-detect</button>
      <button class="ghost sm" onclick={refreshTools}>Refresh</button>
    </div>
    <label class="f">
      <span>ffmpeg</span>
      <div class="fv">
        <input class="mono" value={config.ffmpeg} oninput={(e) => onconfig({ ffmpeg: e.currentTarget.value })} />
        <span class="dot" class:ok={tools?.ffmpeg_exists}>{tools?.ffmpeg_exists ? "✓" : "✗"}</span>
        <button class="ghost" onclick={() => test("ffmpeg")}>Test</button>
      </div>
    </label>
    <label class="f">
      <span>whisper-cli</span>
      <div class="fv">
        <input class="mono" value={config.whisper_exe} oninput={(e) => onconfig({ whisper_exe: e.currentTarget.value })} />
        <span class="dot" class:ok={tools?.whisper_exe_exists}>{tools?.whisper_exe_exists ? "✓" : "✗"}</span>
        <button class="ghost" onclick={browseExe}>Browse…</button>
        <button class="ghost" onclick={() => test("whisper_exe")}>Test</button>
      </div>
    </label>
    <label class="f">
      <span>whisper model</span>
      <div class="fv">
        <input class="mono" value={config.whisper_model} oninput={(e) => onconfig({ whisper_model: e.currentTarget.value })} />
        <span class="dot" class:ok={tools?.whisper_model_exists}>{tools?.whisper_model_exists ? "✓" : "✗"}</span>
        <button class="ghost" onclick={browseModel}>Browse…</button>
      </div>
    </label>
    <label class="f sm">
      <span>Language</span>
      <div class="fv">
        <select value={config.lang} onchange={(e) => onconfig({ lang: e.currentTarget.value })}>
          {#each LANGS as l}<option value={l}>{l}</option>{/each}
        </select>
      </div>
    </label>
  </div>

  <div class="panel">
    <div class="row">
      <button onclick={start} disabled={busy || !!status?.running}>▶ Start batch</button>
      <button class="ghost" onclick={stop} disabled={!status?.running}>■ Stop</button>
      <button class="ghost" onclick={preflight}>Preflight</button>
      <span class="spacer"></span>
      {#if status}
        <span class="counts">
          <span class="ok">✓ {status.ok}</span>
          <span class="bad">✗ {status.fail}</span>
          <span class="tot">/ {status.total}</span>
        </span>
      {/if}
    </div>
    {#if status?.total}
      <div class="bar"><div class="fill" style="width:{status.pct}%"></div></div>
      <p class="cur mono">{status.name || "—"}</p>
    {/if}
  </div>

  <div class="panel log">
    <div class="row">
      <h3>Log</h3>
      <span class="spacer"></span>
      <button class="ghost sm" onclick={() => (logLines = [])}>Clear</button>
    </div>
    <pre class="mono">{#each logLines as line, i (i)}{line}
{/each}</pre>
  </div>

  <p class="foot">Files with <code>_clean</code> in the name are skipped. Intermediate WAVs go to a temp dir, never to your input dir.</p>
</section>

<style>
  .prep{ display:flex; flex-direction:column; gap:0.8rem; max-width:900px; }
  .head{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; }
  .head h2{ margin:0; font-size:1.2rem; letter-spacing:-0.02em; }
  .subtitle{ margin:0.2rem 0 0; color:#8b8e9a; font-size:0.82rem; }
  .pill{ background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.3rem 0.7rem; font-size:0.75rem; font-family:ui-monospace,monospace; color:#8b8e9a; white-space:nowrap; }
  .pill.running{ border-color:#4a5aa8; color:#a8b8e6; }
  .panel{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; display:flex; flex-direction:column; gap:0.6rem; }
  .panel h3{ margin:0; font-size:0.92rem; letter-spacing:-0.01em; }
  .row{ display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; }
  .spacer{ flex:1; }
  .f{ display:flex; flex-direction:column; gap:0.2rem; min-width:0; }
  .f.sm{ max-width:180px; }
  .f > span{ font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; color:#8b8e9a; font-weight:600; }
  .fv{ display:flex; gap:0.4rem; align-items:center; }
  .fv input{ flex:1; min-width:0; }
  .dot{ font-size:0.8rem; font-weight:700; color:#e5484d; min-width:1.1rem; text-align:center; }
  .dot.ok{ color:#30a46c; }
  .counts{ display:flex; gap:0.5rem; font-family:ui-monospace,monospace; font-size:0.8rem; }
  .counts .ok{ color:#30a46c; } .counts .bad{ color:#e5484d; } .counts .tot{ color:#6b6e79; }
  .bar{ height:8px; background:#14151a; border:1px solid #2a2d36; border-radius:999px; overflow:hidden; }
  .bar .fill{ height:100%; background:#3b4b8f; transition:width 0.3s ease; }
  .cur{ margin:0; color:#8b8e9a; font-size:0.75rem; }
  .log pre{ margin:0; background:#14151a; border:1px solid #2a2d36; border-radius:9px; padding:0.6rem 0.7rem; max-height:260px; overflow:auto; font-size:0.74rem; line-height:1.45; color:#b6b8c0; white-space:pre-wrap; word-break:break-word; }
  .foot{ margin:0; color:#6b6e79; font-size:0.75rem; }
  .foot code{ background:#232634; padding:0.05rem 0.3rem; border-radius:4px; font-size:0.72rem; }
  input,select{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.45rem 0.6rem; font-size:0.85rem; line-height:1.2; }
  input.mono{ font-family:ui-monospace,monospace; }
  input:focus,select:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.5rem 0.85rem; cursor:pointer; font-size:0.84rem; font-weight:550; line-height:1; white-space:nowrap; }
  button:hover:not(:disabled){ background:#4458aa; } button:active:not(:disabled){ background:#35468a; }
  button.ghost{ background:#232634; color:#e8e8ec; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button.sm{ padding:0.4rem 0.6rem; font-size:0.76rem; }
  button:disabled{ opacity:0.45; cursor:default; }
</style>
