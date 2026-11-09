<script lang="ts">
  import { onMount } from "svelte";
  import { api, type AutoForwardStatus, type QwenStatus } from "../api";
  import { openCutter } from "../cutter/tauri";
  import { luna, type HookName, type LunaStatus } from "../luna";
  import type { EventEntry, ServerStatus } from "../types";

  // ---------------------------------------------------------------------------
  // Explicit Dashboard section visibility.
  //
  // Nothing is shown or hidden implicitly: every block below is wrapped in its
  // own `{#if sections.*}`. Flip a flag to show or hide a section. This is what
  // keeps the auto-forward block (and the rest) from disappearing by accident.
  // ---------------------------------------------------------------------------
  let sections = $state({
    game: true,
    status: true,
    engine: true,
    autoForward: true,
    import: true,
    tools: true,
    log: true,
    // Luna-Hook is on hold. The connection points exist; set this to true to
    // preview the card once the backend integration lands.
    luna: false,
  });

  let health: { qwen: boolean; status: string } | null = $state(null);
  let status: ServerStatus | null = $state(null);
  let qwen: QwenStatus | null = $state(null);
  let events: EventEntry[] = $state([]);
  let logging = $state(true);
  let qwenBusy = $state(false);
  let qwenMsg = $state("");
  let newGame = $state("");
  let importing = $state(false);
  let folderPath = $state("");
  let folders: Record<string, string> = $state({});
  let linkMsg = $state("");
  let linkBusy = $state(false);
  let cutterMsg = $state("");
  let lunaStatus: LunaStatus | null = $state(null);
  let lunaNames: HookName[] = $state([]);

  const imp = $derived.by(() => status?.import_status ?? null);

  // --- Auto-forward ----------------------------------------------------------
  const FALLBACK_HOTKEYS = [
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "PAUSE", "SCROLL", "INSERT",
  ];
  let af: AutoForwardStatus | null = $state(null);
  let afBusy = $state(false);
  let afMsg = $state("");
  let afForm = $state({ enabled: false, target: "", delay: 0.3, hotkey: "INSERT" });
  // Last values the backend reported; used to avoid overwriting a field while
  // the user is typing (hotkeys can change the state outside the GUI).
  const afSeen = { enabled: false, target: "", hotkey: "INSERT" };

  const hotkeyOptions = () =>
    af?.hotkey_options?.length ? af.hotkey_options : FALLBACK_HOTKEYS;

  const syncAutoForward = (s: AutoForwardStatus) => {
    af = s;
    if (s.target !== afSeen.target) { afForm.target = s.target; afSeen.target = s.target; }
    if (s.enabled !== afSeen.enabled) { afForm.enabled = s.enabled; afSeen.enabled = s.enabled; }
    if (s.hotkey !== afSeen.hotkey) { afForm.hotkey = s.hotkey; afSeen.hotkey = s.hotkey; }
  };

  const saveAutoForward = async () => {
    afBusy = true; afMsg = "";
    try {
      const s = await api.setAutoForward({
        enabled: afForm.enabled,
        target: afForm.target.trim(),
        delay: Number(afForm.delay) || 0.3,
        hotkey: afForm.hotkey,
      });
      syncAutoForward(s);
      afMsg = s.enabled ? "Auto-forward enabled." : "Auto-forward saved (off).";
    } catch (e) {
      afMsg = `Save failed: ${(e as Error).message}`;
    }
    afBusy = false;
  };

  const saveHotkey = async () => {
    afBusy = true; afMsg = "";
    try {
      const s = await api.setAutoForward({ hotkey: afForm.hotkey });
      syncAutoForward(s);
      afMsg = `Toggle hotkey set to ${s.hotkey}.`;
    } catch (e) {
      afMsg = `Hotkey failed: ${(e as Error).message}`;
    }
    afBusy = false;
  };

  const toggleAutoForward = async () => {
    afBusy = true; afMsg = "";
    try {
      const s = await api.toggleAutoForward();
      syncAutoForward(s);
      afMsg = s.enabled ? "Auto-forward enabled." : "Auto-forward disabled.";
    } catch (e) {
      afMsg = `Toggle failed: ${(e as Error).message}`;
    }
    afBusy = false;
  };

  const captureAutoForwardTarget = async () => {
    afBusy = true; afMsg = "Capturing in 5 s — switch to the game window now…";
    // The backend grabs the foreground window. Without a pause that is NovaTTS
    // itself, so give the user time to tab back to the game.
    await new Promise((r) => setTimeout(r, 5000));
    try {
      const r = await api.captureAutoForwardTarget();
      syncAutoForward(r);
      afMsg = r.title
        ? `Target captured: ${r.title}`
        : "Nothing captured — focus the game window and try again.";
    } catch (e) {
      afMsg = `Capture failed: ${(e as Error).message}`;
    }
    afBusy = false;
  };

  const testAutoForward = async () => {
    afBusy = true; afMsg = "";
    try {
      const r = await api.testAutoForward();
      afMsg = r.ok
        ? `Test keystroke sent (${r.method ?? "ok"}${r.wid ? `, window ${r.wid}` : ""}).`
        : `Test failed: ${r.reason ?? "unknown error"}`;
    } catch (e) {
      afMsg = `Test failed: ${(e as Error).message}`;
    }
    afBusy = false;
  };

  // --- Engine / voices -------------------------------------------------------
  const levelOf = (t: string) => t === "error" ? "error" : t === "queued" ? "info" : t === "speaker_discovered" || t === "unassigned_speaker" ? "warn" : "muted";

  const poll = async () => {
    try {
      health = await api.health();
      status = await api.status();
      qwen = (status?.qwen_mgr as unknown as QwenStatus) ?? await api.qwenStatus();
      try { folders = (await api.games()).folders ?? {}; } catch {}
      try { syncAutoForward(await api.autoForwardStatus()); } catch {}
    } catch { health = null; status = null; }
    if (logging) { try { events = await api.events(80); } catch {} }
    if (sections.luna) {
      try { lunaStatus = await luna.status(); lunaNames = await luna.names(); } catch {}
    }
  };

  const qwenStart = async () => { qwenBusy = true; qwenMsg = ""; try { await api.qwenStart(); qwenMsg = "Qwen starting…"; } catch (e) { qwenMsg = `Failed: ${(e as Error).message}`; } qwenBusy = false; await poll(); };
  const qwenStop = async () => { qwenBusy = true; qwenMsg = ""; try { const r = await api.qwenStop(); qwenMsg = r.status; } catch (e) { qwenMsg = (e as Error).message; } qwenBusy = false; await poll(); };
  const importNow = async () => { importing = true; qwenMsg = ""; try { const r = await api.importSamples(); qwenMsg = `Imported ${r.imported}/${r.total} voice(s) (${r.pairs} pairs, ${r.wavs} wavs${r.failed.length ? `, ${r.failed.length} failed` : ""})`; } catch (e) { qwenMsg = `Import failed: ${(e as Error).message}`; } importing = false; await poll(); };
  const createGame = async () => { const n = newGame.trim(); if (!n) return; await api.createGame(n); newGame = ""; await poll(); };
  const switchGame = async (name: string) => { await api.setActiveGame(name); await poll(); };
  const openPerfectCut = async () => {
    cutterMsg = "";
    try {
      const wasOpen = await openCutter();
      cutterMsg = wasOpen ? "Perfect Cut was already open — brought to the front." : "Perfect Cut opened in its own window.";
    } catch (e) {
      cutterMsg = (e as Error).message;
    }
  };
  const linkFolder = async () => {
    const game = status?.game; const folder = folderPath.trim();
    if (!game || !folder || linkBusy) return;
    linkBusy = true; linkMsg = "";
    try {
      const r = await api.linkGameFolder(game, folder);
      linkMsg = `Gekoppeld — mod: ${r.helper}${r.migrated ? " · speakers verhuisd" : ""}${r.helper === "foreign" ? " · LET OP: eigen bestand met mod-naam blijft staan" : ""}`;
      folderPath = "";
    } catch (e) { linkMsg = `Koppelen mislukt: ${(e as Error).message}`; }
    linkBusy = false; await poll();
  };
  const unlinkFolder = async () => {
    const game = status?.game;
    if (!game || linkBusy) return;
    linkBusy = true; linkMsg = "";
    try { await api.unlinkGameFolder(game); linkMsg = "Ontkoppeld — speakers staan weer in de data-map."; }
    catch (e) { linkMsg = `Ontkoppelen mislukt: ${(e as Error).message}`; }
    linkBusy = false; await poll();
  };
  onMount(() => { poll(); const id = setInterval(poll, 2500); return () => clearInterval(id); });
</script>

<section class="dashboard">
  <header class="page-head">
    <div>
      <h2>Dashboard</h2>
      <p class="subtitle">Live engine status · voices & queue</p>
    </div>
    <span class="health-dot" class:ok={health?.status === "ok"}>{health ? health.status : "offline"}</span>
  </header>

  {#if sections.game}
    <div class="game-bar">
      <div class="game-label">
        <span class="eyebrow">Active game</span>
        <strong class="game-name">{status?.game || "— default —"}</strong>
      </div>
      <div class="game-controls">
        <select value={status?.game ?? ""} onchange={(e) => switchGame((e.target as HTMLSelectElement).value)} aria-label="Active game">
          <option value="">— default —</option>
          {#each status?.games ?? [] as g}<option value={g}>{g}</option>{/each}
        </select>
        <input class="field" bind:value={newGame} placeholder="New game name…" onkeydown={(e) => e.key === "Enter" && createGame()} />
        <button onclick={createGame} disabled={!newGame.trim()}>Add</button>
      </div>
      {#if status?.game}
        <div class="link-row">
          {#if folders[status.game]}
            <span class="mono small wrap" title={folders[status.game]}>🔗 {folders[status.game]}</span>
            <button class="ghost" onclick={unlinkFolder} disabled={linkBusy}>Unlink</button>
          {:else}
            <input class="field" bind:value={folderPath} placeholder="Gamemap plakken… (map met game\ erin)" onkeydown={(e) => e.key === "Enter" && linkFolder()} />
            <button class="ghost" onclick={linkFolder} disabled={linkBusy || !folderPath.trim()}>{linkBusy ? "…" : "Link folder"}</button>
          {/if}
        </div>
        {#if linkMsg}<span class="hint">{linkMsg}</span>{/if}
      {/if}
    </div>
  {/if}

  {#if sections.status}
    <div class="cards">
      <div class="card"><span class="label">Qwen</span><span class="value dot" class:ok={qwen?.online || status?.qwen}>{qwen?.online || status?.qwen ? "online" : "offline"}</span></div>
      <div class="card"><span class="label">Clipboard</span><span class="value">{status?.clipboard ? "polling" : "stopped"}</span></div>
      <div class="card"><span class="label">Speakers</span><span class="value">{status?.speaker_count ?? "…"}</span></div>
      <div class="card"><span class="label">Queue</span><span class="value">{status?.queue_size ?? "…"}</span></div>
    </div>
    {#if status?.stale_mappings?.length}<div class="banner">⚠ {status.stale_mappings.length} speaker(s) point to missing voices — fix in Characters.</div>{/if}
  {/if}

  {#if sections.engine}
    <div class="section">
      <div class="panel-head">
        <h3>Qwen engine</h3>
        <span class="pill" class:ok={qwen?.online || status?.qwen}>{qwen?.online || status?.qwen ? "online" : "offline"}</span>
      </div>
      {#if qwen?.last_error}<p class="err">{qwen.last_error}</p>{/if}
      <div class="row">
        <button onclick={qwenStart} disabled={qwenBusy || !!qwen?.online}>{qwenBusy ? "…" : "Start Qwen"}</button>
        <button class="ghost" onclick={qwenStop} disabled={qwenBusy || !qwen?.managed_running}>Stop</button>
        <button class="ghost" onclick={poll} disabled={qwenBusy}>Refresh</button>
        {#if qwenMsg}<span class="hint">{qwenMsg}</span>{/if}
      </div>
    </div>
  {/if}

  {#if sections.autoForward}
    <div class="section">
      <div class="panel-head">
        <h3>Auto-forward</h3>
        {#if af}<span class="pill" class:ok={af.enabled}>{af.enabled ? "on" : "off"}</span>{/if}
      </div>
      <p class="hint">Sends Space to the game window after each clipboard line finishes, so RenPy advances to the next line.</p>
      {#if af && !af.available}<p class="err">{af.reason || "Auto-forward is not available on this platform."}</p>{/if}
      <label class="toggle">
        <input type="checkbox" bind:checked={afForm.enabled} onchange={saveAutoForward} disabled={afBusy || !af?.available} />
        Enable auto-forward
      </label>
      <div class="af-grid">
        <label class="field-row">
          <span class="k">Target window</span>
          <div class="row">
            <input class="field grow" bind:value={afForm.target} placeholder="Game window title (case-insensitive)" />
            <button class="ghost" onclick={captureAutoForwardTarget} disabled={afBusy || !af?.can_capture}>{afBusy ? "…" : "Capture (5 s)"}</button>
          </div>
        </label>
        <label class="field-row">
          <span class="k">Delay after line (s)</span>
          <input class="field sm" type="number" bind:value={afForm.delay} min="0.1" max="30" step="0.1" />
        </label>
        <label class="field-row">
          <span class="k">Toggle hotkey</span>
          <select class="field sm" bind:value={afForm.hotkey} onchange={saveHotkey} disabled={afBusy}>
            {#each hotkeyOptions() as h}<option value={h}>{h}</option>{/each}
          </select>
        </label>
      </div>
      <div class="row">
        <button onclick={saveAutoForward} disabled={afBusy || !af?.available}>Apply</button>
        <button class="ghost" onclick={toggleAutoForward} disabled={afBusy || !af?.available}>{afForm.enabled ? "Disable" : "Enable"}</button>
        <button class="ghost" onclick={testAutoForward} disabled={afBusy || !af?.can_test}>Send test Space</button>
        {#if afMsg}<span class="hint">{afMsg}</span>{/if}
      </div>
    </div>
  {/if}

  {#if sections.import}
    <div class="section">
      <div class="panel-head"><h3>Voices import</h3></div>
      {#if imp}
        <div class="mono small wrap">{imp.dir}</div>
        <div class="mono small wrap">{imp.found} stem(men) gevonden — {imp.pairs} pairs, {imp.unpaired} wavs zonder pair · {imp.loaded}/{imp.total || imp.found} geladen {imp.active ? "… aan het importeren" : "✓ klaar"}</div>
        {#if imp.active}<div class="bar"><div class="fill" style="width:{imp.total ? Math.round(imp.loaded / imp.total * 100) : 0}%"></div></div>{/if}
        {#if imp.error}<p class="err">{imp.error}</p>{/if}
      {:else}
        <p class="hint">No import status yet — the backend reports it once the samples folder is scanned.</p>
      {/if}
      <div class="row">
        <button class="ghost" onclick={importNow} disabled={importing || !qwen?.online}>{importing ? "Importing…" : "Import now"}</button>
        <button class="ghost" onclick={openPerfectCut}>Perfect Cut…</button>
        <span class="hint">Registers .spk/.rvq pairs verbatim — even when the .wav is gone.</span>
      </div>
    </div>
  {/if}

  {#if sections.tools}
    <div class="section">
      <div class="panel-head"><h3>Perfect Cut</h3></div>
      <p class="hint">Trim samples and prepare a voice dataset in its own window, then import the result here.</p>
      <div class="row">
        <button onclick={openPerfectCut}>Open Perfect Cut</button>
        {#if cutterMsg}<span class="hint">{cutterMsg}</span>{/if}
      </div>
    </div>
  {/if}

  {#if sections.luna}
    <div class="section">
      <div class="panel-head">
        <h3>Luna Hook</h3>
        <span class="pill" class:ok={lunaStatus?.available}>{lunaStatus?.available ? "connected" : "not available"}</span>
      </div>
      {#if lunaStatus?.available}
        <div class="row"><span class="k">Mode</span><span>{lunaStatus.mode}</span></div>
        <div class="row"><span class="k">Endpoint</span><span class="mono small">{lunaStatus.host}:{lunaStatus.port}</span></div>
        <div class="row"><span class="k">Clients</span><span>{lunaStatus.clients}</span><span class="k">Dropped</span><span>{lunaStatus.dropped}</span></div>
        {#if lunaStatus.lastRaw}<div class="mono small wrap">last: {lunaStatus.lastRaw}</div>{/if}
        {#if lunaNames.length}
          <div class="mono small wrap">{lunaNames.length} unregistered name(s): {lunaNames.map((n) => n.name).join(", ")}</div>
        {/if}
      {:else}
        <p class="hint">Luna-Hook is not active in this build. The connection points are ready and will light up when the backend integration lands.</p>
      {/if}
    </div>
  {/if}

  {#if sections.log}
    <div class="section log-panel">
      <div class="log-head">
        <h3>Live log</h3>
        <label class="toggle"><input type="checkbox" bind:checked={logging} /> auto</label>
      </div>
      <ul class="log-list">
        {#each events as e}<li class={levelOf(e.type)}><code>{e.type}</code><span class="payload">{JSON.stringify(e.payload)}</span></li>{:else}<li class="muted">No events yet — clipboard or TTS activity appears here.</li>{/each}
      </ul>
    </div>
  {/if}
</section>

<style>
  .dashboard{ display:flex; flex-direction:column; gap:1rem; max-width:860px; }
  .page-head h2{ font-size:1.35rem; }
  .health-dot{ align-self:center; background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.3rem 0.7rem; font-size:0.78rem; font-weight:600; color:#8b8e9a; display:inline-flex; align-items:center; gap:0.4rem; }
  .health-dot::before{ content:""; width:8px; height:8px; border-radius:50%; background:#e5484d; }
  .health-dot.ok{ color:#e8e8ec; border-color:#2a3a2e; } .health-dot.ok::before{ background:#30a46c; }
  .game-bar{ display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; align-items:center; background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; }
  .game-label{ display:flex; flex-direction:column; gap:0.15rem; min-width:160px; }
  .eyebrow{ font-size:0.68rem; text-transform:uppercase; letter-spacing:0.07em; color:#8b8e9a; }
  .game-name{ font-size:0.95rem; }
  .game-controls{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; flex:1; justify-content:flex-end; }
  .game-controls select{ min-width:170px; flex:1 1 160px; max-width:220px; }
  .link-row{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; flex-basis:100%; }
  .link-row .field{ flex:1 1 220px; max-width:340px; }
  .field{ flex:1 1 180px; max-width:240px; min-width:160px; }
  .field.grow{ flex:1 1 240px; max-width:none; }
  .field.sm{ flex:0 1 150px; max-width:150px; }
  .cards{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:0.7rem; }
  .card{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; display:flex; flex-direction:column; gap:0.35rem; }
  .label{ font-size:0.68rem; text-transform:uppercase; letter-spacing:0.06em; color:#8b8e9a; }
  .value{ font-size:1rem; font-weight:650; display:flex; align-items:center; gap:0.4rem; }
  .value.dot::before{ content:""; width:8px; height:8px; border-radius:50%; background:#e5484d; }
  .value.dot.ok::before{ background:#30a46c; }
  .banner{ background:#2a2430; border:1px solid #3a2a2e; color:#ffb4b4; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; }
  .panel-head{ display:flex; justify-content:space-between; align-items:center; gap:1rem; flex-wrap:wrap; }
  .section h3{ font-size:0.98rem; }
  .pill{ font-size:0.72rem; font-weight:650; padding:0.2rem 0.55rem; border-radius:999px; background:#2a1f24; border:1px solid #3a2a2e; color:#ffb4b4; }
  .pill.ok{ background:#1f2a22; border-color:#2a3a2e; color:#8fe0ac; }
  .af-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:0.75rem; align-items:end; }
  .field-row{ display:flex; flex-direction:column; gap:0.3rem; min-width:0; }
  .k{ color:#8b8e9a; font-size:0.82rem; }
  .mono.small{ font-family:ui-monospace,monospace; font-size:0.76rem; color:#8b8e9a; }
  .mono.small.wrap{ word-break:break-all; line-height:1.4; }
  .err{ color:#e5484d; font-size:0.82rem; margin:0; word-break:break-all; background:#2a1f24; border:1px solid #3a2a2e; border-radius:8px; padding:0.5rem 0.65rem; }
  .hint{ color:#8b8e9a; font-size:0.82rem; }
  .row{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
  .bar{ height:8px; background:#14151a; border:1px solid #2a2d36; border-radius:999px; overflow:hidden; }
  .bar .fill{ height:100%; background:#3b4b8f; transition:width 0.4s ease; }
  .log-panel{ padding:0; overflow:hidden; }
  .log-head{ display:flex; justify-content:space-between; align-items:center; padding:1rem 1.1rem 0; }
  .toggle{ display:flex; align-items:center; gap:0.4rem; font-size:0.78rem; color:#8b8e9a; cursor:pointer; }
  .toggle input{ accent-color:#3b4b8f; }
  .log-list{ list-style:none; margin:0; padding:0; background:#14151a; border-top:1px solid #2a2d36; max-height:320px; overflow-y:auto; font-size:0.78rem; }
  .log-list li{ display:flex; gap:0.6rem; padding:0.4rem 0.75rem; border-bottom:1px solid #1b1d24; align-items:baseline; }
  .log-list li:last-child{ border-bottom:none; }
  .log-list code{ color:#6c8fc7; font-family:ui-monospace,monospace; font-size:0.74rem; white-space:nowrap; }
  .log-list li.error code{ color:#e5484d; } .log-list li.warn code{ color:#e5c76b; } .log-list li.muted{ color:#6b6e79; }
  .payload{ color:#b6b8c0; word-break:break-all; font-family:ui-monospace,monospace; font-size:0.74rem; }
</style>
