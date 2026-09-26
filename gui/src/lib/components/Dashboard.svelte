<script lang="ts">
  import { onMount } from "svelte";
  import { api, type QwenStatus } from "../api";
  import type { EventEntry, ServerStatus } from "../types";

  let health: { qwen: boolean; status: string } | null = $state(null);
  let status: ServerStatus | null = $state(null);
  let qwen: QwenStatus | null = $state(null);
  let events: EventEntry[] = $state([]);
  let logging = $state(true);
  let qwenBusy = $state(false);
  let qwenMsg = $state("");
  let newGame = $state("");
  let importing = $state(false);

  const levelOf = (t: string) => t === "error" ? "error" : t === "queued" ? "info" : t === "speaker_discovered" || t === "unassigned_speaker" ? "warn" : "muted";

  const poll = async () => {
    try {
      health = await api.health();
      status = await api.status();
      qwen = (status?.qwen_mgr as unknown as QwenStatus) ?? await api.qwenStatus();
    } catch { health = null; status = null; }
    if (logging) { try { events = await api.events(80); } catch {} }
  };
  const qwenStart = async () => { qwenBusy = true; qwenMsg = ""; try { const r = await api.qwenStart(); qwenMsg = `Started pid ${r.pid ?? "?"}`; } catch (e) { qwenMsg = `Failed: ${(e as Error).message}`; } qwenBusy = false; await poll(); };
  const qwenStop = async () => { qwenBusy = true; qwenMsg = ""; try { const r = await api.qwenStop(); qwenMsg = r.status; } catch (e) { qwenMsg = (e as Error).message; } qwenBusy = false; await poll(); };
  const importNow = async () => { importing = true; qwenMsg = ""; try { const r = await api.importSamples(); qwenMsg = `Imported ${r.imported}/${r.total} voice(s) (${r.pairs} pairs, ${r.wavs} wavs${r.failed.length ? `, ${r.failed.length} failed` : ""})`; } catch (e) { qwenMsg = `Import failed: ${(e as Error).message}`; } importing = false; await poll(); };
  const createGame = async () => { const n = newGame.trim(); if (!n) return; await api.createGame(n); newGame = ""; await poll(); };
  const switchGame = async (name: string) => { await api.setActiveGame(name); await poll(); };
  onMount(() => { poll(); const id = setInterval(poll, 2500); return () => clearInterval(id); });
</script>

<section class="dashboard">
  <header class="page-head">
    <div>
      <h2>Dashboard</h2>
      <p class="subtitle">Live engine status · voices & queue</p>
    </div>
    <span class="health-dot" class:ok={health?.status==="ok"}>{health ? health.status : "offline"}</span>
  </header>

  <div class="game-bar">
    <div class="game-label">
      <span class="eyebrow">Active game</span>
      <strong class="game-name">{status?.game || "— default —"}</strong>
    </div>
    <div class="game-controls">
      <select value={status?.game ?? ""} onchange={(e)=>switchGame((e.target as HTMLSelectElement).value)} aria-label="Active game">
        <option value="">— default —</option>
        {#each status?.games ?? [] as g}<option value={g}>{g}</option>{/each}
      </select>
      <input class="field" bind:value={newGame} placeholder="New game name…" onkeydown={(e)=>e.key==="Enter"&&createGame()} />
      <button onclick={createGame} disabled={!newGame.trim()}>Add</button>
    </div>
  </div>

  <div class="cards">
    <div class="card"><span class="label">Qwen</span><span class="value dot" class:ok={qwen?.online || status?.qwen}>{qwen?.online||status?.qwen?"online":"offline"}</span></div>
    <div class="card"><span class="label">Clipboard</span><span class="value">{status?.clipboard?"polling":"stopped"}</span></div>
    <div class="card"><span class="label">Speakers</span><span class="value">{status?.speaker_count ?? "…"}</span></div>
    <div class="card"><span class="label">Queue</span><span class="value">{status?.queue_size ?? "…"}</span></div>
  </div>
  {#if status?.stale_mappings?.length}<div class="banner">⚠ {status.stale_mappings.length} speaker(s) point to missing voices — fix in Characters.</div>{/if}

  <div class="panel">
    <div class="qwen-head"><h3>Qwen engine</h3><span class="mono small url" title={qwen?.qwen_url ?? ""}>{qwen?.qwen_url ?? "—"}</span></div>
    <div class="qwen-grid">
      <span class="k">Managed</span><span class="v">{qwen ? (qwen.managed_running?`pid ${qwen.pid}`:"stopped"):"…"}</span>
      <span class="k">External</span><span class="v">{qwen ? (qwen.external_running?"online":"offline"):"…"}</span>
      <span class="k">Bin</span><span class="v mono" title={qwen?.bin ?? ""}>{qwen?.bin ?? "—"} {qwen ? (qwen.bin_exists?"✓":"✗"):""}</span>
    </div>
    {#if qwen?.last_error}<p class="err">{qwen.last_error}</p>{/if}
    <div class="row">
      <button onclick={qwenStart} disabled={qwenBusy || !!qwen?.online}>{qwenBusy?"…":"Start Qwen"}</button>
      <button class="ghost" onclick={qwenStop} disabled={qwenBusy || !qwen?.managed_running}>Stop</button>
      <button class="ghost" onclick={poll} disabled={qwenBusy}>Refresh</button>
      {#if qwenMsg}<span class="hint">{qwenMsg}</span>{/if}
    </div>
  </div>

  {#if (status as unknown as { import_status?: { found:number; loaded:number; total:number; active:boolean; dir:string; pairs?:number; unpaired?:number } })?.import_status}
    {@const imp = (status as unknown as { import_status: { found:number; loaded:number; total:number; active:boolean; dir:string; error:string|null; pairs?:number; unpaired?:number } }).import_status}
    <div class="panel">
      <h3>Voices import</h3>
      <div class="mono small wrap">{imp.dir}</div>
      <div class="mono small wrap">{imp.found} stem(men) gevonden — {imp.pairs} pairs, {imp.unpaired} wavs zonder pair · {imp.loaded}/{imp.total || imp.found} geladen {imp.active ? "… aan het importeren" : "✓ klaar"}</div>
      {#if imp.active}<div class="bar"><div class="fill" style="width:{imp.total?Math.round(imp.loaded/imp.total*100):0}%"></div></div>{/if}
      {#if imp.error}<p class="err">{imp.error}</p>{/if}
      <div class="row">
        <button class="ghost" onclick={importNow} disabled={importing || !qwen?.online}>{importing ? "Importing…" : "Import now"}</button>
        <span class="hint">Registreert .spk/.rvq paren verbatim — ook als de .wav al verwijderd is.</span>
      </div>
    </div>
  {/if}

  <div class="panel log-panel">
    <div class="log-head">
      <h3>Live log</h3>
      <label class="toggle"><input type="checkbox" bind:checked={logging}/> auto</label>
    </div>
    <ul class="log-list">
      {#each events as e (e.type+JSON.stringify(e.payload))}<li class={levelOf(e.type)}><code>{e.type}</code><span class="payload">{JSON.stringify(e.payload)}</span></li>{:else}<li class="muted">No events yet — clipboard or TTS activity appears here.</li>{/each}
    </ul>
  </div>
</section>

<style>
  .dashboard{ display:flex; flex-direction:column; gap:1rem; max-width:860px; }
  .page-head{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; }
  .page-head h2{ margin:0; font-size:1.35rem; letter-spacing:-0.02em; }
  .subtitle{ margin:0.15rem 0 0; color:#8b8e9a; font-size:0.82rem; }
  .health-dot{ align-self:center; background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.3rem 0.7rem; font-size:0.78rem; font-weight:600; color:#8b8e9a; display:inline-flex; align-items:center; gap:0.4rem; }
  .health-dot::before{ content:""; width:8px; height:8px; border-radius:50%; background:#e5484d; }
  .health-dot.ok{ color:#e8e8ec; border-color:#2a3a2e; } .health-dot.ok::before{ background:#30a46c; }
  .game-bar{ display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; align-items:center; background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; }
  .game-label{ display:flex; flex-direction:column; gap:0.15rem; min-width:160px; }
  .eyebrow{ font-size:0.68rem; text-transform:uppercase; letter-spacing:0.07em; color:#8b8e9a; }
  .game-name{ font-size:0.95rem; }
  .game-controls{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; flex:1; justify-content:flex-end; }
  .game-controls select{ min-width:170px; flex:1 1 160px; max-width:220px; }
  .field{ flex:1 1 180px; max-width:240px; min-width:160px; }
  .cards{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:0.7rem; }
  .card{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; display:flex; flex-direction:column; gap:0.35rem; }
  .label{ font-size:0.68rem; text-transform:uppercase; letter-spacing:0.06em; color:#8b8e9a; }
  .value{ font-size:1rem; font-weight:650; display:flex; align-items:center; gap:0.4rem; }
  .value.dot::before{ content:""; width:8px; height:8px; border-radius:50%; background:#e5484d; }
  .value.dot.ok::before{ background:#30a46c; }
  .banner{ background:#2a2430; border:1px solid #3a2a2e; color:#ffb4b4; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; }
  .panel{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:0.75rem; }
  .qwen-head{ display:flex; justify-content:space-between; align-items:center; gap:1rem; flex-wrap:wrap; }
  .qwen-head h3,.panel h3{ margin:0; font-size:0.98rem; letter-spacing:-0.01em; }
  .qwen-grid{ display:grid; grid-template-columns:96px 1fr; gap:0.3rem 0.8rem; font-size:0.85rem; align-items:center; }
  .k{ color:#8b8e9a; font-size:0.82rem; } .v.mono{ font-family:ui-monospace,monospace; font-size:0.76rem; word-break:break-all; }
  .mono.small{ font-family:ui-monospace,monospace; font-size:0.76rem; color:#8b8e9a; }
  .mono.small.url{ max-width:320px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .mono.small.wrap{ word-break:break-all; line-height:1.4; }
  .err{ color:#e5484d; font-size:0.82rem; margin:0; word-break:break-all; background:#2a1f24; border:1px solid #3a2a2e; border-radius:8px; padding:0.5rem 0.65rem; }
  .hint{ color:#8b8e9a; font-size:0.82rem; }
  .row{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
  input,select{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; line-height:1.2; }
  input:focus,select:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 1rem; cursor:pointer; font-size:0.88rem; font-weight:550; line-height:1; }
  button:hover:not(:disabled){ background:#4458aa; } button:active:not(:disabled){ background:#35468a; }
  button.ghost{ background:#232634; color:#e8e8ec; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button:disabled{ opacity:0.5; cursor:default; }
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
