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
  let showSounds = $state(false);

  const load = async () => {
    const d = await api.emotions();
    dir = d.dir; count = d.sounds; map = d.map; aliases = d.aliases;
  };
  const reload = async () => { await api.reloadEmotions(); await load(); msg = "Reloaded from disk — discovered sounds updated."; setTimeout(() => (msg = ""), 2500); };
  const addAlias = async () => { 
    const e = aliasExpr.trim(), t = aliasTag.trim(); 
    if (!e || !t) return;
    await api.addEmotionAlias(e, t); 
    aliasExpr = ""; 
    aliasTag = ""; 
    await load();
    msg = "Emotion mapping added.";
    setTimeout(() => (msg = ""), 2500);
  };
  const delAlias = async (k: string) => { await api.deleteEmotionAlias(k); await load(); };
  onMount(load);
</script>

<section class="panel">
  <header>
    <div>
      <h2>Emotion Sounds</h2>
      <p class="subtitle">Link words/phrases to sound effects from <code class="inline">{dir || "—"}</code></p>
    </div>
    <button onclick={reload}>Reload from disk</button>
  </header>
  {#if msg}<p class="ok">{msg}</p>{/if}

  <!-- PRIMARY: ADD EMOTION FORM (at top) -->
  <div class="card">
    <div class="card-head"><h3>Add Emotion Mapping</h3></div>
    <div class="form-section">
      <div class="input-row">
        <input 
          type="text" 
          placeholder="Word or phrase (e.g., heartbeat, thunder)" 
          bind:value={aliasExpr}
        />
        <select bind:value={aliasTag}>
          <option value="">Select sound...</option>
          {#each Object.entries(map).sort((a,b)=>a[0].localeCompare(b[0])) as [tag, file]}
            <option value={tag}>{tag}</option>
          {/each}
        </select>
        <button onclick={addAlias} disabled={!aliasExpr.trim() || !aliasTag.trim()}>Add</button>
      </div>
    </div>
  </div>

  <!-- SECONDARY: CURRENT MAPPINGS (scrollable, main focus) -->
  {#if Object.keys(aliases).length > 0}
    <div class="card">
      <div class="card-head">
        <h3>Active Mappings</h3>
        <span class="count">{Object.keys(aliases).length}</span>
      </div>
      <div class="list">
        {#each Object.entries(aliases).sort((a,b)=>a[0].localeCompare(b[0])) as [phrase, sound]}
          <div class="row-with-delete">
            <div>
              <span class="phrase">{phrase}</span>
              <span class="arrow">→</span>
              <span class="sound">{sound}</span>
            </div>
            <button class="btn-delete" onclick={() => delAlias(phrase)}>✕</button>
          </div>
        {/each}
      </div>
    </div>
  {:else}
    <div class="card">
      <p class="muted small">No emotion mappings yet — add one above.</p>
    </div>
  {/if}

  <!-- TERTIARY: SOUND MAP (collapsed by default, reference only) -->
  <div class="card">
    <button class="card-head toggle" onclick={() => showSounds = !showSounds}>
      <span>
        <h3>Available Sounds</h3>
        <span class="count">{count} discovered {showSounds ? '▼' : '▶'}</span>
      </span>
    </button>
    {#if showSounds}
      {#if Object.keys(map).length}
        <div class="list sounds-list">
          {#each Object.entries(map).sort((a,b)=>a[0].localeCompare(b[0])) as [k,v]}
            <div class="row2">
              <span class="k">{k}</span>
              <span class="v hint" title={v}>{v}</span>
            </div>
          {/each}
        </div>
      {:else}
        <p class="muted small">No sounds discovered in {dir}</p>
      {/if}
    {/if}
  </div>
</section>

<style>
  .panel { display:flex; flex-direction:column; gap:1rem; padding:1rem; }
  header { display:flex; justify-content:space-between; align-items:flex-start; }
  header div { flex:1; }
  header h2 { margin:0 0 0.25rem; }
  header .subtitle { margin:0; font-size:0.875rem; color:var(--muted-foreground); }
  button { padding:0.5rem 1rem; background:var(--accent); color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:500; }
  button:disabled { opacity:0.5; cursor:not-allowed; }
  button:hover:not(:disabled) { opacity:0.9; }

  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; overflow:hidden; }
  .card-head { display:flex; justify-content:space-between; align-items:center; padding:0.75rem; background:#0f0f12; border-bottom:1px solid var(--border); gap:1rem; }
  .card-head h3 { margin:0; font-size:0.95rem; }
  .count { font-size:0.8rem; color:var(--muted-foreground); }
  .card-head.toggle { cursor:pointer; user-select:none; }
  .card-head.toggle:hover { background:#1a1a20; }

  .form-section { padding:1rem; }
  .input-row { display:flex; gap:0.5rem; }
  .input-row input, .input-row select { flex:1; padding:0.5rem; background:#0f0f12; border:1px solid var(--border); border-radius:6px; color:#fff; }
  .input-row input::placeholder { color:var(--muted-foreground); }
  .input-row button { flex:0 0 auto; min-width:80px; }

  .list { display:flex; flex-direction:column; gap:0.25rem; max-height:320px; overflow-y:auto; background:#14151a; padding:0.5rem; }
  .sounds-list { max-height:240px; }
  .row2 { display:flex; justify-content:space-between; align-items:center; padding:0.5rem; border-radius:4px; font-size:0.875rem; }
  .row2:hover { background:#1a1a20; }
  .row2 .k { font-weight:500; color:var(--foreground); }
  .row2 .v { color:var(--muted-foreground); text-overflow:ellipsis; overflow:hidden; max-width:60%; }

  .row-with-delete { display:flex; justify-content:space-between; align-items:center; padding:0.5rem; border-radius:4px; }
  .row-with-delete:hover { background:#1a1a20; }
  .row-with-delete div { display:flex; align-items:center; gap:0.5rem; flex:1; }
  .phrase { font-weight:600; color:var(--accent); }
  .arrow { color:var(--muted-foreground); margin:0 0.25rem; }
  .sound { color:var(--foreground); }
  .btn-delete { padding:0.25rem 0.5rem; background:transparent; color:var(--muted-foreground); border:1px solid var(--border); font-size:0.8rem; min-width:auto; margin-left:auto; }
  .btn-delete:hover { background:#ff4444; color:#fff; border-color:#ff4444; }

  .muted { color:var(--muted-foreground); font-size:0.875rem; margin:0.5rem; }
  .ok { color:var(--accent); font-size:0.875rem; margin:0; padding:0.5rem; background:#1a2a1a; border-radius:4px; }
  code.inline { background:#14151a; padding:0.2rem 0.4rem; border-radius:3px; font-size:0.85rem; }
</style>
