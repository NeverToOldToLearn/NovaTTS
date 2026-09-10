<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";
  import type { Speaker, SpeakersResponse } from "../types";

  let speakers: Record<string, Speaker> = $state({});
  let voices: string[] = $state([]);
  let stale: { speaker: string; voice: string }[] = $state([]);
  let voiceUsed: Record<string, string[]> = $state({});
  let qwenOnline = $state(false);
  let fallback: string = $state("Narrator");
  let newName = $state("");
  let err = $state("");
  let info = $state("");
  let previewBusy: string | null = $state(null);
  let previewText = $state("Hello from NovaTTS.");
  let showAdvanced = $state(false);
  let showVoices = $state(false);
  let editing: string | null = $state(null);
  let editVal = $state("");
  let aliasFor: string | null = $state(null);
  let aliasVal = $state("");
  let dragOver = $state(false);
  let fileInput: HTMLInputElement | undefined = $state(undefined);
  let refTextFallback = $state("");
  let pollId: ReturnType<typeof setInterval> | null = null;

  const load = async () => {
    const [sp, st, vs] = await Promise.all([api.speakers(), api.status(), api.voices()]);
    speakers = (sp as SpeakersResponse).speakers ?? (sp as Record<string, Speaker>);
    voices = vs.voices ?? st.voices ?? [];
    stale = st.stale_mappings ?? [];
    voiceUsed = (st as unknown as { voice_used_by?: Record<string, string[]> }).voice_used_by ?? {};
    qwenOnline = vs.qwen_online ?? st.qwen ?? false;
    fallback = (sp as SpeakersResponse).fallback ?? "Narrator";
  };
  const isStale = (name: string, voice: string) => stale.some((s) => s.speaker === name && s.voice === voice);

  const addSpeaker = async () => {
    err = ""; const n = newName.trim(); if (!n) return;
    try { await api.createSpeaker(n); newName = ""; info = `Added ${n}`; await load(); } catch (e) { err = (e as Error).message; }
  };
  const patchVoice = async (name: string, voice: string) => {
    err = "";
    try { await api.updateSpeaker(name, { voice }); info = `${name} → ${voice || "(default)"}`; await load(); }
    catch (e) { err = (e as Error).message; }
  };
  const delSpeaker = async (name: string) => {
    if (name === fallback) return;
    err = "";
    try { await api.deleteSpeaker(name); info = `Removed ${name}`; await load(); }
    catch (e) { err = (e as Error).message; }
  };
  const doRename = async (old: string) => {
    const nn = editVal.trim(); if (!nn || nn === old) { editing = null; return; }
    try { await api.renameSpeaker(old, nn); editing = null; info = `Renamed ${old} → ${nn}`; await load(); }
    catch (e) { err = (e as Error).message; }
  };
  const doAlias = async (src: string) => {
    const al = aliasVal.trim(); if (!al) return;
    try { await api.aliasSpeaker(src, al); aliasFor = null; aliasVal = ""; info = `Alias ${al} = ${src}`; await load(); }
    catch (e) { err = (e as Error).message; }
  };
  const preview = async (voice: string) => {
    if (!voice) return;
    previewBusy = voice; err = ""; info = "";
    try { const r = await api.previewVoice(voice, previewText); info = `Queued ${r.voice}`; }
    catch (e) { err = (e as Error).message; } finally { previewBusy = null; }
  };
  const cloneFiles = async (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".wav"));
    if (!list.length) { err = "No .wav selected."; return; }
    err = ""; info = ""; let ok = 0, fail = 0;
    for (const file of list) {
      const voiceName = file.name.replace(/\.wav$/i, "");
      const txtName = voiceName + ".txt";
      let refText = "";
      const sib = Array.from(files).find((f) => f.name.toLowerCase() === txtName.toLowerCase());
      if (sib) refText = (await sib.text()).trim();
      else if (refTextFallback.trim()) refText = refTextFallback.trim();
      try { const buf = new Uint8Array(await file.arrayBuffer()); await api.cloneVoiceFromBytes(voiceName, buf, refText); ok++; }
      catch (e) { fail++; err = (e as Error).message; }
    }
    info = `Cloned ${ok}${fail ? `, ${fail} failed` : ""}`; await load();
  };
  const onFileInput = async (e: Event) => {
    const i = e.target as HTMLInputElement; if (i.files?.length) await cloneFiles(i.files); i.value = "";
  };
  const onDrop = async (e: DragEvent) => { dragOver = false; if (e.dataTransfer?.files.length) await cloneFiles(e.dataTransfer.files); };

  onMount(() => { load(); pollId = setInterval(load, 4000); return () => { if (pollId) clearInterval(pollId); }; });
</script>

<section class="panel">
  <header class="page-head">
    <div>
      <h2>Characters</h2>
      <p class="subtitle">Voices per character · live from clipboard & game save</p>
    </div>
    <span class="pill">{Object.keys(speakers).length} speakers · {voices.length} voices {qwenOnline ? "● online" : "○ offline"}</span>
  </header>

  {#if stale.length}<div class="banner">⚠ {stale.length} speaker(s) point to missing voices — reassign below.</div>{/if}
  {#if err}<p class="callout error">{err}</p>{/if}
  {#if info}<p class="callout info">{info}</p>{/if}

  <div class="add-row">
    <input class="field" bind:value={newName} placeholder="New character name…" onkeydown={(e) => e.key === "Enter" && addSpeaker()} />
    <button onclick={addSpeaker} disabled={!newName.trim()}>Add</button>
  </div>

  <div class="table-wrap">
  <table>
    <thead><tr><th>Character</th><th>Voice</th><th class="col-actions">Actions</th><th>Current</th></tr></thead>
    <tbody>
      {#each Object.values(speakers).sort((a,b)=>a.name.localeCompare(b.name)) as s (s.name)}
        <tr class:fallback={s.name===fallback} class:stale={isStale(s.name, s.voice)} class:unassigned={!s.voice}>
          <td class="name-cell">
            {#if editing===s.name}
              <input class="field sm" bind:value={editVal} onkeydown={(e)=>e.key==="Enter"&&doRename(s.name)} />
              <button class="ghost small" onclick={()=>doRename(s.name)}>Save</button>
              <button class="ghost small" onclick={()=>editing=null}>Cancel</button>
            {:else}
              <span class="sname">{s.name}</span>
              {#if s.name===fallback}<span class="tag">fallback</span>{/if}
              {#if !s.voice}<span class="badge warn" title="No voice assigned — will play as Narrator default">no voice</span>{/if}
              {#if isStale(s.name,s.voice)}<span class="badge err">missing</span>{/if}
              <button class="icon small" title="Rename / fix spelling" onclick={()=>{editing=s.name;editVal=s.name;}}>✎</button>
            {/if}
          </td>
          <td class="voice-cell">
            <select value={s.voice} onchange={(e)=>patchVoice(s.name,(e.target as HTMLSelectElement).value)} aria-label="Voice for {s.name}">
              <option value="">— no voice (Narrator default) —</option>
              {#if s.voice && !voices.includes(s.voice)}<option value={s.voice}>{s.voice} ⚠ missing</option>{/if}
              {#each voices as v (v)}<option value={v}>{v}{voiceUsed[v] ? ` — ${voiceUsed[v].join(", ")}` : ""}</option>{/each}
            </select>
            <button class="icon" title="Preview this voice" disabled={!s.voice || previewBusy!==null} onclick={()=>preview(s.voice)}>{previewBusy===s.voice?"…":"▶"}</button>
          </td>
          <td class="actions">
            {#if s.name!==fallback}<button class="del" title="Remove speaker" onclick={()=>delSpeaker(s.name)}>✕</button>{/if}
            {#if aliasFor===s.name}
              <input bind:value={aliasVal} placeholder="alias" class="alias-in field sm" onkeydown={(e)=>e.key==="Enter"&&doAlias(s.name)} />
              <button class="ghost small" onclick={()=>doAlias(s.name)}>Add</button>
              <button class="ghost small" onclick={()=>aliasFor=null}>×</button>
            {:else}
              <button class="ghost small" onclick={()=>{aliasFor=s.name; aliasVal="";}}>Alias</button>
            {/if}
          </td>
          <td class="hint">{s.voice || "default"}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  </div>
  <p class="muted small">Auto-discovered from clipboard. Pick a voice per character — changes apply on next line, no restart. Alias handles spelling variants (e.g. “RICK” → “Rick”).</p>

  <details class="adv" bind:open={showAdvanced}>
    <summary>Advanced — import voices</summary>
    {#if showAdvanced}
      <div class="adv-body">
        <p class="muted small">Voices are cloned samples. Auto-imported from <code>D:\!!Scripts!!\Samples_Clone</code> on Qwen start; use below for extras.</p>
        <input class="field" bind:value={refTextFallback} placeholder="Fallback ref_text if no .txt sibling" />
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="dropzone" class:over={dragOver} ondragover={(e)=>{e.preventDefault();dragOver=true;}} ondragleave={()=>dragOver=false} ondrop={(e)=>{e.preventDefault(); onDrop(e);}} onclick={()=>fileInput?.click()}>
          Drop .wav (+ .txt) here or click to browse
        </div>
        <input bind:this={fileInput} type="file" accept=".wav,.txt" multiple hidden onchange={onFileInput} />
      </div>
    {/if}
  </details>

  <details class="adv" bind:open={showVoices}>
    <summary>All voices on engine ({voices.length})</summary>
    {#if showVoices}
      <div class="preview-row">
        <input class="field grow" bind:value={previewText} placeholder="Preview text…" />
        <button class="ghost" onclick={()=>preview(previewText)} disabled={!previewText.trim()}>Test default</button>
      </div>
      {#if voices.length}
        <ul class="voice-list">
          {#each voices as v (v)}<li><span class="vname" title={v}>{v}{voiceUsed[v] ? ` — ${voiceUsed[v].join(", ")}` : ""}</span><button class="ghost" disabled={previewBusy!==null} onclick={()=>preview(v)}>{previewBusy===v?"…":"▶ Preview"}</button></li>{/each}
        </ul>
      {:else}<p class="muted">No voices yet.</p>{/if}
    {/if}
  </details>
</section>

<style>
  .panel{ display:flex; flex-direction:column; gap:0.85rem; max-width:920px; }
  .page-head{ display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; align-items:flex-start; }
  .page-head h2{ margin:0; font-size:1.25rem; letter-spacing:-0.02em; } .subtitle{ margin:0.2rem 0 0; color:#8b8e9a; font-size:0.82rem; }
  .pill{ align-self:center; background:#1e2027; border:1px solid #2a2d36; border-radius:999px; padding:0.35rem 0.75rem; font-size:0.78rem; color:#8b8e9a; white-space:nowrap; }
  .banner{ background:#2a2430; border:1px solid #3a2a2e; color:#ffb4b4; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; }
  .callout{ margin:0; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; word-break:break-word; }
  .callout.error{ background:#2a1f24; border:1px solid #3a2a2e; color:#ffb4b4; } .callout.info{ background:#1c2330; border:1px solid #2a3550; color:#a8b8e6; }
  .add-row{ display:flex; gap:0.5rem; align-items:center; }
  .add-row .field{ flex:1; min-width:160px; }
  input,select{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; line-height:1.2; }
  .field{ flex:1; } .field.sm{ flex:0 1 160px; max-width:200px; } .alias-in{ width:130px; }
  input:focus,select:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 0.95rem; cursor:pointer; font-size:0.88rem; font-weight:550; line-height:1; }
  button:hover:not(:disabled){ background:#4458aa; } button:active:not(:disabled){ background:#35468a; }
  button:disabled{ opacity:0.5; cursor:default; }
  button.del{ background:transparent; color:#e5484d; padding:0.35rem 0.55rem; border-radius:8px; } button.del:hover{ background:#2a1f24; }
  button.ghost{ background:#232634; color:#e8e8ec; font-size:0.82rem; padding:0.38rem 0.75rem; }
  button.ghost.small{ font-size:0.78rem; padding:0.3rem 0.6rem; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button.icon{ background:#232634; padding:0.38rem 0.6rem; font-size:0.85rem; min-width:36px; } button.icon.small{ font-size:0.75rem; padding:0.25rem 0.45rem; min-width:28px; }
  .table-wrap{ overflow-x:auto; border-radius:12px; border:1px solid #2a2d36; background:#1e2027; }
  table{ width:100%; border-collapse:collapse; min-width:640px; }
  th,td{ text-align:left; padding:0.6rem 0.75rem; border-bottom:1px solid #262a33; font-size:0.88rem; vertical-align:middle; }
  th{ color:#8b8e9a; font-size:0.70rem; text-transform:uppercase; letter-spacing:0.06em; background:#1b1d24; position:sticky; top:0; }
  tr:last-child td{ border-bottom:none; }
  tr.stale{ background:#2a1f24; } tr.unassigned{ background:#1e2430; } tr.fallback td:first-child{ color:#8b8e9a; }
  .col-actions{ width:160px; }
  .name-cell{ display:flex; gap:0.35rem; align-items:center; flex-wrap:wrap; min-width:160px; }
  .sname{ font-weight:600; }
  .badge{ border-radius:999px; font-size:0.62rem; padding:0.14rem 0.45rem; font-weight:600; }
  .badge.warn{ background:#2e2a16; color:#e5d171; border:1px solid #4a4a1a; }
  .badge.err{ background:#3a1a1a; color:#ff9a9a; border:1px solid #4a2a2a; }
  .tag{ background:#3b4b8f; border-radius:999px; font-size:0.62rem; padding:0.14rem 0.45rem; font-weight:600; color:#fff; }
  .voice-cell{ display:flex; gap:0.4rem; align-items:center; min-width:220px; }
  .voice-cell select{ flex:1; min-width:160px; }
  .actions{ display:flex; gap:0.35rem; align-items:center; flex-wrap:wrap; min-width:140px; }
  .hint{ color:#6b6e79; font-size:0.78rem; font-family:ui-monospace,monospace; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .muted{ color:#8b8e9a; font-size:0.85rem; } .muted.small{ font-size:0.8rem; margin:0; line-height:1.4; }
  .adv{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.8rem 1rem; }
  .adv summary{ cursor:pointer; font-size:0.88rem; color:#b6b8c0; font-weight:600; list-style:none; display:flex; align-items:center; gap:0.4rem; }
  .adv summary::before{ content:"▶"; font-size:0.65rem; transition:transform 0.15s; display:inline-block; } .adv[open] summary::before{ transform:rotate(90deg); }
  .adv-body{ margin-top:0.7rem; display:flex; flex-direction:column; gap:0.6rem; }
  code{ background:#232634; padding:0.15rem 0.4rem; border-radius:6px; font-size:0.78rem; word-break:break-all; }
  .dropzone{ border:1.5px dashed #3a3e4d; border-radius:10px; padding:1rem; text-align:center; color:#8b8e9a; cursor:pointer; font-size:0.88rem; transition:border-color 0.15s, background 0.15s; }
  .dropzone.over{ border-color:#6c8fc7; background:#232634; color:#e8e8ec; } .dropzone:hover{ border-color:#4a5aa8; }
  .preview-row{ display:flex; gap:0.5rem; margin:0.5rem 0 0.6rem; align-items:center; }
  .preview-row input.grow{ flex:1; min-width:160px; }
  .voice-list{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:0.35rem; max-height:340px; overflow-y:auto; padding-right:0.2rem; }
  .voice-list li{ display:flex; gap:0.5rem; align-items:center; background:#14151a; border:1px solid #2a2d36; border-radius:10px; padding:0.45rem 0.6rem; }
  .vname{ flex:1; font-size:0.84rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
</style>
