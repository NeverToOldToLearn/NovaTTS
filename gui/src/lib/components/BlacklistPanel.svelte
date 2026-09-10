<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  let presets: string[] = $state([]);
  let enabled: string[] = $state([]);
  let custom: string[] = $state([]);
  let input = $state("");
  let msg = $state("");
  let saving = $state(false);

  const load = async () => {
    const d = await api.blacklist();
    presets = d.presets;
    enabled = d.enabled_presets;
    custom = d.custom_words;
  };
  const save = async () => {
    saving = true;
    await api.setBlacklist(custom, enabled);
    msg = "Saved — blacklist active on next clipboard line.";
    saving = false;
    setTimeout(() => (msg = ""), 2500);
  };
  const toggle = (p: string) => {
    if (enabled.includes(p)) enabled = enabled.filter((x) => x !== p);
    else enabled = [...enabled, p];
  };
  const add = () => {
    const w = input.trim();
    if (!w || custom.includes(w)) return;
    custom = [...custom, w];
    input = "";
  };
  const remove = (w: string) => { custom = custom.filter((x) => x !== w); };
  onMount(load);
</script>

<section class="panel">
  <header>
    <div>
      <h2>Blacklist</h2>
      <p class="subtitle">Filtered before TTS · presets + custom words · RenPy exception dumps are always skipped (no preset needed).</p>
    </div>
  </header>

  <div class="card">
    <div class="card-head"><h3>Presets</h3><span class="count">{enabled.length}/{presets.length} on</span></div>
    <div class="presets">
      {#each presets as p}
        <label class="check" class:on={enabled.includes(p)}>
          <input type="checkbox" checked={enabled.includes(p)} onchange={() => toggle(p)} />
          <span>{p}</span>
        </label>
      {/each}
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h3>Custom words / phrases</h3><span class="count">{custom.length}</span></div>
    <div class="row">
      <input class="field" bind:value={input} placeholder="Add word or phrase" onkeydown={(e) => e.key === "Enter" && add()} />
      <button onclick={add} disabled={!input.trim()}>Add</button>
    </div>
    {#if custom.length}
      <div class="chips">
        {#each custom as w}<span class="chip">{w}<button class="x" aria-label="Remove {w}" onclick={() => remove(w)}>×</button></span>{/each}
      </div>
    {:else}
      <p class="muted small">No custom words yet — add UI tokens you want stripped (e.g. save-slot labels).</p>
    {/if}
  </div>

  <div class="actions">
    <button onclick={save} disabled={saving}>{saving ? "Saving…" : "Save blacklist"}</button>
    {#if msg}<span class="ok">{msg}</span>{/if}
    <button class="ghost" onclick={load}>Reset</button>
  </div>
</section>

<style>
  .panel{ display:flex; flex-direction:column; gap:0.9rem; max-width:720px; }
  header h2{ margin:0; font-size:1.25rem; letter-spacing:-0.02em; } .subtitle{ margin:0.25rem 0 0; color:#8b8e9a; font-size:0.82rem; line-height:1.4; max-width:640px; }
  .card{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:0.75rem; }
  .card-head{ display:flex; justify-content:space-between; align-items:center; gap:1rem; }
  .card-head h3{ margin:0; font-size:0.95rem; letter-spacing:-0.01em; }
  .count{ font-size:0.76rem; color:#8b8e9a; background:#14151a; border:1px solid #2a2d36; border-radius:999px; padding:0.2rem 0.6rem; }
  .presets{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:0.45rem; }
  .check{ display:flex; align-items:center; gap:0.5rem; background:#14151a; border:1px solid #2a2d36; border-radius:10px; padding:0.5rem 0.65rem; cursor:pointer; font-size:0.88rem; color:#b6b8c0; transition:border-color 0.15s, background 0.15s; user-select:none; }
  .check:hover{ border-color:#3a3e4d; background:#1b1d24; } .check.on{ border-color:#3b4b8f; background:#1c2330; color:#e8e8ec; }
  .check input{ accent-color:#3b4b8f; width:16px; height:16px; }
  .row{ display:flex; gap:0.5rem; align-items:center; }
  .field{ flex:1; min-width:160px; background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; }
  .field:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 1rem; cursor:pointer; font-size:0.88rem; font-weight:550; }
  button:hover:not(:disabled){ background:#4458aa; } button:disabled{ opacity:0.5; cursor:default; }
  button.ghost{ background:#232634; color:#e8e8ec; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button.x{ background:transparent; color:#8b8e9a; padding:0.15rem 0.35rem; border-radius:6px; font-size:1rem; line-height:1; } button.x:hover{ background:#2a1f24; color:#e5484d; }
  .chips{ display:flex; flex-wrap:wrap; gap:0.4rem; }
  .chip{ background:#232634; border:1px solid #2a2d36; border-radius:999px; padding:0.25rem 0.35rem 0.25rem 0.7rem; font-size:0.82rem; display:inline-flex; gap:0.3rem; align-items:center; color:#e8e8ec; }
  .muted.small{ color:#8b8e9a; font-size:0.82rem; margin:0; line-height:1.4; }
  .actions{ display:flex; gap:0.6rem; align-items:center; flex-wrap:wrap; }
  .ok{ color:#30a46c; font-size:0.85rem; font-weight:500; }
</style>
