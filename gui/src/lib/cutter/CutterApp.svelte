<script lang="ts">
  // Shell for the standalone Perfect Cut window.
  //
  // Deliberately not in the main app's sidebar — this is a tool you open when
  // you are prepping samples, not a view you keep open. It reuses the main
  // app's palette and control styling so it reads as part of the family.

  import { onMount } from "svelte";
  import SampleCutter from "./SampleCutter.svelte";
  import DatasetPrep from "./DatasetPrep.svelte";
  import { cutterApi } from "./api";
  import type { CutterConfig } from "./types";

  type Tab = "cutter" | "prep";

  let tab = $state<Tab>("cutter");
  let status = $state("Loading config…");
  let online = $state<boolean | null>(null);
  let config = $state<CutterConfig | null>(null);

  function say(msg: string) {
    status = msg;
  }

  /** The Tauri side spawns the backend in a background thread on launch, so
   *  opening this window immediately can beat it. Retry for a while before
   *  showing the offline panel, which still carries a manual Retry. */
  const RETRY_DELAYS_MS = [400, 800, 1500, 2500, 4000];

  let retryTimers: ReturnType<typeof setTimeout>[] = [];

  function cancelRetries() {
    for (const t of retryTimers) clearTimeout(t);
    retryTimers = [];
  }

  async function load(attempt = 0) {
    try {
      const { config: c } = await cutterApi.config();
      cancelRetries();
      config = c;
      online = true;
      say("Ready.");
    } catch (e) {
      online = false;
      if (attempt < RETRY_DELAYS_MS.length) {
        const delay = RETRY_DELAYS_MS[attempt]!;
        say(`Waiting for the NovaTTS backend (retry in ${(delay / 1000).toFixed(1)}s)…`);
        retryTimers.push(setTimeout(() => void load(attempt + 1), delay));
        return;
      }
      say(`Backend unreachable on 127.0.0.1:8765 — ${(e as Error).message}`);
    }
  }

  /**
   * Persist any field the tabs bound directly to `config`.
   *
   * Patches accumulate for the length of the debounce window: holding a key
   * down fires dozens of `oninput` events, and sending only the first one
   * would save a single character.
   */
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let pending: Partial<CutterConfig> = {};

  function persist(patch: Partial<CutterConfig>) {
    if (!config) return;
    config = { ...config, ...patch };
    pending = { ...pending, ...patch };
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const body = pending;
      pending = {};
      saveTimer = null;
      try {
        const r = await cutterApi.saveConfig(body);
        config = r.config;
      } catch (e) {
        say(`✗ config not saved: ${(e as Error).message}`);
      }
    }, 400);
  }

  /** The cutter's "→ batch input" button: use the export folder as input dir. */
  function useAsInput(outFile: string) {
    if (!outFile) return;
    const dir = outFile.replace(/[\\/][^\\/]*$/, "") || outFile;
    persist({ input_dir: dir });
    tab = "prep";
    say(`Batch input dir → ${dir}`);
  }

  onMount(() => {
    void load();
    return cancelRetries;
  });
</script>

<div class="app">
  <header class="bar">
    <div class="brand">
      <span class="mark">✂</span>
      <div class="titles">
        <strong>Perfect Cut</strong>
        <span class="sub">NovaTTS sample cutter</span>
      </div>
    </div>
    <nav aria-label="Views">
      <button class:active={tab === "cutter"} onclick={() => (tab = "cutter")}>Sample Cutter</button>
      <button class:active={tab === "prep"} onclick={() => (tab = "prep")}>Dataset Prep</button>
    </nav>
    <span class="health" class:ok={online} title={online ? "backend connected" : "backend offline"}>
      {online === null ? "…" : online ? "online" : "offline"}
    </span>
  </header>

  <main>
    {#if !config}
      <div class="wait">
        {#if online === false}
          <p class="err">
            The NovaTTS backend is not running. Start the main app (or <code>start_all.cmd</code>) and
            reopen this window — cutting and batch prep both run server-side.
          </p>
          <button class="ghost" onclick={() => load()}>Retry</button>
        {:else}
          <p class="muted">Loading…</p>
        {/if}
      </div>
    {:else if tab === "cutter"}
      <SampleCutter {config} onstatus={say} onoutput={useAsInput} />
    {:else}
      <DatasetPrep {config} onconfig={persist} onstatus={say} />
    {/if}
  </main>

  <footer class="status" title={status}>{status}</footer>
</div>

<style>
  :global(:root){ --bg:#14151a; --fg:#e8e8ec; --muted:#8b8e9a; --card:#1e2027; --border:#2a2d36; --accent:#3b4b8f; }
  :global(body){ margin:0; background:#14151a; }
  .app{ display:flex; flex-direction:column; height:100vh; background:#14151a; color:#e8e8ec; font-family:ui-sans-serif,system-ui,-apple-system,sans-serif; }
  .bar{ display:flex; align-items:center; gap:1rem; padding:0.6rem 1rem; background:#1b1d24; border-bottom:1px solid #2a2d36; flex-wrap:wrap; }
  .brand{ display:flex; align-items:center; gap:0.55rem; }
  .mark{ font-size:1.1rem; color:#6c8fc7; }
  .titles{ display:flex; flex-direction:column; line-height:1.2; }
  .titles strong{ font-size:0.95rem; letter-spacing:-0.01em; }
  .sub{ font-size:0.68rem; color:#8b8e9a; letter-spacing:0.04em; }
  nav{ display:flex; gap:0.3rem; margin-left:auto; }
  nav button{ background:transparent; color:#b6b8c0; border:1px solid transparent; border-radius:9px; padding:0.42rem 0.8rem; cursor:pointer; font-size:0.84rem; font-weight:500; }
  nav button:hover{ background:#232634; border-color:#2a2d36; color:#e8e8ec; }
  nav button.active{ background:#3b4b8f; border-color:#4a5aa8; color:#fff; }
  .health{ display:inline-flex; align-items:center; gap:0.4rem; background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.25rem 0.65rem; font-size:0.72rem; font-weight:600; color:#8b8e9a; }
  .health::before{ content:""; width:7px; height:7px; border-radius:50%; background:#e5484d; }
  .health.ok::before{ background:#30a46c; }
  main{ flex:1; min-height:0; overflow-y:auto; padding:1rem 1.1rem 1.2rem; }
  .status{ background:#1b1d24; border-top:1px solid #2a2d36; color:#8b8e9a; font-size:0.74rem; padding:0.4rem 1rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-family:ui-monospace,monospace; }
  .wait{ display:flex; flex-direction:column; gap:0.7rem; align-items:flex-start; max-width:56ch; }
  .wait p{ margin:0; font-size:0.88rem; line-height:1.5; }
  .err{ color:#ffb4b4; background:#2a1f24; border:1px solid #3a2a2e; border-radius:10px; padding:0.7rem 0.85rem; }
  .muted{ color:#8b8e9a; }
  code{ background:#232634; padding:0.1rem 0.3rem; border-radius:5px; font-size:0.78rem; }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.5rem 0.9rem; cursor:pointer; font-size:0.84rem; font-weight:550; }
  button.ghost{ background:#232634; color:#e8e8ec; }
  button.ghost:hover{ background:#2a2e40; }
</style>
