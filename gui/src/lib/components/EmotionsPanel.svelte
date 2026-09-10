<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let dir = $state("");
  let count = $state(0);
  let map: Record<string, string> = $state({});
  let aliases: Record<string, string> = $state({});
  let aliasExpr = $state("");
  let aliasTag = $state("");
  let msg = $state("");

  const load = async () => {
    const d = await api.emotions();
    dir = d.dir; count = d.sounds; map = d.map; aliases = d.aliases;
  };
  const reload = async () => { await api.reloadEmotions(); await load(); msg = "Reloaded from disk — discovered sounds updated."; setTimeout(() => (msg = ""), 2500); };
  const addAlias = async () => {
    const e = aliasExpr.trim(), t = aliasTag.trim(); if (!e || !t) return;
    await api.addEmotionAlias(e, t); aliasExpr = ""; aliasTag = ""; await load();
  };
  const delAlias = async (k: string) => { await api.deleteEmotionAlias(k); await load(); };
  onMount(load);
</script>

<section class="panel">
  <header>
    <div>
      <h2>Emotion Sounds</h2>
      <p class="subtitle">Stripped from TTS text and played inline from <code class="inline">{dir || "—"}</code> · {count} sounds · tags inserted between TTS segments.</p>
    </div>
    <button onclick={reload}>Reload from disk</button>
  </header>
  {#if msg}<p class="ok">{msg}</p>{/if}

  <div class="card">
    <div class="card-head"><h3>Sound map</h3><span class="count">{Object.keys(map).length} tags</span></div>
    {#if Object.keys(map).length}
      <div class="list">
        {#each Object.entries(map).sort((a,b)=>a[0].localeCompare(b[0])) as [k,v]}<div class="row2"><span class="k">{k}</span><span class="v" title={v}>{v}</span></div>{/each}
      </div>
    {:else}
      <p class="muted small">No sounds discovered — check the directory and file permissions, then Reload.</p>
    {/if}
    <p class="muted small">Auto-discovered from <code class="inline mono">{dir}</code>. Add/remove <code class="inline">.wav/.ogg</code> on disk and hit Reload — map is validated against what actually exists.</p>
  </div>

  <div class="card">
    <div class="card-head"><h3>Custom aliases</h3><span class="count">{Object.keys(aliases).length}</span></div>
    <div class="alias-form">
      <input class="field" bind:value={aliasExpr} placeholder="expression  e.g. mwah" aria-label="Alias expression" />
      <span class="arrow">→</span>
      <input class="field" bind:value={aliasTag} placeholder="tag  e.g. kiss" aria-label="Alias tag" />
      <button onclick={addAlias} disabled={!aliasExpr.trim() || !aliasTag.trim()}>Add</button>
    </div>
    {#if Object.keys(aliases).length}
      <div class="list">
        {#each Object.entries(aliases) as [k,v]}<div class="row2"><span class="k">{k}</span><span class="arrow">→</span><span class="v">{v}</span><button class="x" aria-label="Remove {k}" onclick={()=>delAlias(k)}>×</button></div>{/each}
      </div>
    {:else}
      <p class="muted small">No aliases yet — map shorthand expressions to a sound tag.</p>
    {/if}
  </div>
</section>

<style>
  .panel{ display:flex; flex-direction:column; gap:0.9rem; max-width:740px; }
  header{ display:flex; justify-content:space-between; gap:1rem; align-items:flex-start; flex-wrap:wrap; }
  header h2{ margin:0; font-size:1.25rem; letter-spacing:-0.02em; } .subtitle{ margin:0.3rem 0 0; color:#8b8e9a; font-size:0.82rem; line-height:1.45; max-width:620px; }
  .inline{ background:#232634; padding:0.15rem 0.4rem; border-radius:6px; font-size:0.76rem; word-break:break-all; } .inline.mono{ font-family:ui-monospace,monospace; }
  .card{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:0.7rem; }
  .card-head{ display:flex; justify-content:space-between; align-items:center; gap:1rem; } .card-head h3{ margin:0; font-size:0.95rem; letter-spacing:-0.01em; }
  .count{ font-size:0.76rem; color:#8b8e9a; background:#14151a; border:1px solid #2a2d36; border-radius:999px; padding:0.2rem 0.6rem; white-space:nowrap; }
  .muted.small{ color:#8b8e9a; font-size:0.82rem; margin:0; line-height:1.4; }
  .list{ display:flex; flex-direction:column; gap:0.28rem; max-height:320px; overflow-y:auto; background:#14151a; border:1px solid #2a2d36; border-radius:10px; padding:0.65rem 0.7rem; }
  .row2{ display:flex; gap:0.6rem; font-size:0.84rem; align-items:center; min-width:0; }
  .k{ color:#6c8fc7; min-width:96px; max-width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:550; } .v{ color:#8b8e9a; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-family:ui-monospace,monospace; font-size:0.80rem; }
  .alias-form{ display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; }
  .alias-form .field{ flex:1 1 140px; min-width:120px; } .arrow{ color:#8b8e9a; font-size:0.9rem; }
  .field{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; min-width:0; }
  .field:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 0.95rem; cursor:pointer; font-size:0.88rem; font-weight:550; white-space:nowrap; }
  button:hover:not(:disabled){ background:#4458aa; } button:disabled{ opacity:0.5; cursor:default; }
  button.x{ background:transparent; color:#8b8e9a; padding:0.2rem 0.4rem; border-radius:6px; font-size:1rem; line-height:1; min-width:28px; } button.x:hover{ background:#2a1f24; color:#e5484d; }
  .ok{ margin:0; color:#30a46c; font-size:0.85rem; background:#162a1e; border:1px solid #1e3a28; border-radius:8px; padding:0.5rem 0.7rem; }
</style>
