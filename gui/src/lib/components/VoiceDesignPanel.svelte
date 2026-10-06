<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../api";

  type VDFile = { name: string; size: number; mtime: number };

  let status: {
    enabled: boolean;
    tts_bin: string; model: string; codec: string; out_dir: string;
    tts_exists: boolean; model_exists: boolean; codec_exists: boolean;
    busy: boolean; languages: string[];
  } | null = $state(null);

  let files: VDFile[] = $state([]);
  let outDir = $state("");

  let text = $state("");
  let language = $state("auto");

  // Helpers om de stem-beschrijving op te bouwen.
  let gender = $state("");
  let age = $state("");
  let pitch = $state("");
  let emotion = $state("");
  let pace = $state("");
  let extra = $state("");
  let instruct = $state("");

  let seed = $state(-1);
  let temperature = $state(0.9);
  let top_k = $state(50);
  let top_p = $state(1.0);
  let saveName = $state("");

  let busy = $state(false);
  let err = $state("");
  let info = $state("");
  let promoteName: Record<string, string> = $state({});
  /** Afspeelsnelheid per bestand (afluisteren) — dezelfde waarde wordt
      gebruikt om de versie weg te schrijven. */
  let speedOf: Record<string, number> = $state({});
  let rendering: string | null = $state(null);
  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];

  const ready = () => !!status && status.enabled && status.tts_exists && status.model_exists && status.codec_exists;

  const load = async () => {
    try {
      status = await api.voiceDesignStatus();
      if (!status.languages?.includes(language)) language = "auto";
      const f = await api.voiceDesignFiles();
      files = f.files;
      outDir = f.dir;
    } catch (e) {
      err = `Voice-design status laden mislukt: ${(e as Error).message}`;
    }
  };

  const compose = () => {
    const merged = effectiveInstruct();
    if (merged !== instruct.trim()) {
      instruct = merged;
      info = "";
    }
  };

  /** Helpers + vrij veld samengevoegd — dit is wat echt verzonden wordt,
      ook als iemand vergeten is op Samenstellen te klikken. */
  const effectiveInstruct = () => {
    const base = instruct.trim().replace(/[.\s]+$/, "");
    const have = base.toLowerCase();
    const parts = [gender, age, pitch, emotion, pace, extra]
      .map((s) => s.trim().replace(/[.\s]+$/, ""))
      .filter((p) => p && !have.includes(p.toLowerCase()));
    return [base, ...parts].filter(Boolean).join(", ");
  };

  const generate = async () => {
    err = ""; info = "";
    const finalInstruct = effectiveInstruct();
    if (!text.trim()) { err = "Vul eerst de te spreken zin in."; return; }
    if (!finalInstruct) { err = "Beschrijf eerst de stem (instructie)."; return; }
    busy = true;
    try {
      const r = await api.voiceDesignGenerate({
        text: text.trim(),
        instruct: finalInstruct,
        language,
        seed, temperature, top_k, top_p,
        save_name: saveName.trim(),
      });
      info = `Klaar: ${r.file} (${Math.round(r.size / 1024)} KB) — beluister hieronder.`;
      const f = await api.voiceDesignFiles();
      files = f.files;
    } catch (e) {
      err = (e as Error).message;
    }
    busy = false;
  };

  const remove = async (name: string) => {
    err = ""; info = "";
    try {
      await api.voiceDesignDelete(name);
      files = files.filter((f) => f.name !== name);
      info = `Verwijderd: ${name}`;
    } catch (e) {
      err = (e as Error).message;
    }
  };

  const promote = async (name: string) => {
    err = ""; info = "";
    const voice = (promoteName[name] ?? "").trim();
    if (!voice) { err = "Geef een stem-naam op om te promoten naar de samples-map."; return; }
    try {
      // Wat je hoort is wat je krijgt: staat er een tempo op deze rij,
      // dan wordt eerst die versie weggeschreven en die gepromoot.
      let src = name;
      const speed = speedOf[name] ?? 1;
      if (speed !== 1) {
        rendering = name;
        try {
          const r = await api.voiceDesignRenderSpeed(name, speed);
          src = r.file;
          const f = await api.voiceDesignFiles();
          files = f.files;
        } finally {
          rendering = null;
        }
      }
      const r = await api.voiceDesignPromote(src, voice);
      info = r.registered
        ? `Gepromoot als '${r.voice}' (${speed}×) en direct geregistreerd op de engine.`
        : `Gepromoot als '${r.voice}' (${speed}×) naar samples-map (${r.dest}). Wordt geregistreerd bij import/engine-start.`;
    } catch (e) {
      err = (e as Error).message;
    }
  };

  const setSpeed = (name: string, speed: number) => {
    speedOf[name] = speed;
    const el = document.querySelector<HTMLAudioElement>(`audio[data-vd="${CSS.escape(name)}"]`);
    if (el) el.playbackRate = speed;
  };

  const renderSpeed = async (name: string) => {
    err = ""; info = "";
    const speed = speedOf[name] ?? 1;
    if (speed === 1) { err = "Kies eerst een andere snelheid om weg te schrijven."; return; }
    rendering = name;
    try {
      const r = await api.voiceDesignRenderSpeed(name, speed);
      info = `Bewaard als ${r.file} (${speed}×) — beluister hieronder op normale snelheid.`;
      const f = await api.voiceDesignFiles();
      files = f.files;
    } catch (e) {
      err = (e as Error).message;
    }
    rendering = null;
  };

  const fmtDate = (t: number) => new Date(t * 1000).toLocaleString();
  const fmtSize = (b: number) => b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`;

  onMount(load);
</script>

<section class="panel">
  <header class="page-head">
    <div>
      <h2>Voice Design <span class="tag">experimenteel</span></h2>
      <p class="subtitle">Maak sample-stemmen uit een beschrijving met het voicedesign-model — om uit te proberen vóórdat je beslist of dit in de app komt.</p>
    </div>
    <button class="ghost" onclick={load}>Vernieuwen</button>
  </header>

  {#if err}<p class="callout error">{err}</p>{/if}
  {#if info}<p class="callout info">{info}</p>{/if}

  {#if status && !ready()}
    <p class="callout error">
      Voice-design is niet beschikbaar:
      {#if !status.enabled}Het staat uit — zet het aan onder Settings → Voice Design. {/if}
      {#if !status.tts_exists}qwen-tts.exe niet gevonden ({status.tts_bin}). {/if}
      {#if !status.model_exists}voicedesign-model niet gevonden ({status.model}). {/if}
      {#if !status.codec_exists}codec niet gevonden ({status.codec}). {/if}
      Paden aanpassen kan onder Settings.
    </p>
  {/if}

  <div class="section">
    <h3>1 · Wat moet hij zeggen?</h3>
    <textarea class="field" rows="3" bind:value={text} maxlength="2000"
      placeholder="bv. Hallo, dit is een test van mijn nieuwe stem."></textarea>
    <div class="row">
      <label class="inline">Taal
        <select bind:value={language}>
          {#each status?.languages ?? ["auto"] as l}<option value={l}>{l}</option>{/each}
        </select>
      </label>
      <label class="inline grow">Bestandsnaam <span class="muted">(optioneel)</span>
        <input class="field" bind:value={saveName} placeholder="bv. jonge-vrouw-vrolijk" maxlength="80" />
      </label>
    </div>
  </div>

  <div class="section">
    <h3>2 · Hoe moet hij klinken?</h3>
    <p class="muted small">Kies eigenschappen — ze worden automatisch meegenomen bij het genereren (ook zonder op <em>Samenstellen</em> te klikken). Liever alles zelf typen? Zet alles in het instructie-veld hieronder (Engels werkt het best, bv. <code>young female, cheerful, high pitch, fast-paced</code>).</p>
    <div class="grid">
      <label>Geslacht
        <select bind:value={gender}>
          <option value="">—</option>
          <option value="female">female</option>
          <option value="male">male</option>
        </select>
      </label>
      <label>Leeftijd
        <select bind:value={age}>
          <option value="">—</option>
          <option value="child">child</option>
          <option value="teenager">teenager</option>
          <option value="young adult">young adult</option>
          <option value="middle-aged">middle-aged</option>
          <option value="elderly">elderly</option>
        </select>
      </label>
      <label>Toonhoogte
        <select bind:value={pitch}>
          <option value="">—</option>
          <option value="low pitch">low pitch</option>
          <option value="moderate pitch">moderate pitch</option>
          <option value="high pitch">high pitch</option>
          <option value="deep voice">deep voice</option>
        </select>
      </label>
      <label>Emotie / stijl
        <select bind:value={emotion}>
          <option value="">—</option>
          <option value="neutral">neutral</option>
          <option value="cheerful">cheerful</option>
          <option value="calm">calm</option>
          <option value="sad">sad</option>
          <option value="angry">angry</option>
          <option value="whispering">whispering</option>
          <option value="dramatic">dramatic</option>
        </select>
      </label>
      <label>Tempo
        <select bind:value={pace}>
          <option value="">—</option>
          <option value="speaking slowly">speaking slowly</option>
          <option value="steady speaking speed">steady speaking speed</option>
          <option value="fast-paced">fast-paced</option>
        </select>
      </label>
      <label>Extra <span class="muted">(accent, karakter…)</span>
        <input class="field" bind:value={extra} placeholder="bv. with a British accent" maxlength="200" />
      </label>
    </div>
    <div class="row">
      <button class="ghost" onclick={compose}>Samenstellen → instructie</button>
    </div>
    <label class="col">Stem-beschrijving (instructie → --instruct, verplicht)
      <textarea class="field" rows="2" bind:value={instruct} maxlength="1000"
        placeholder="young female, cheerful, high pitch"></textarea>
    </label>
    {#if effectiveInstruct() !== instruct.trim()}
      <p class="muted small">Verzonden wordt (helpers automatisch toegevoegd): <code>{effectiveInstruct()}</code></p>
    {/if}
    <details class="adv">
      <summary>Geavanceerd: sampling</summary>
      <div class="row">
        <label class="inline">Seed <input class="field sm" type="number" bind:value={seed} step="1" title="-1 = willekeurig" /></label>
        <label class="inline">Temp <input class="field sm" type="number" bind:value={temperature} min="0.1" max="1.5" step="0.05" /></label>
        <label class="inline">Top-k <input class="field sm" type="number" bind:value={top_k} min="0" max="200" step="1" /></label>
        <label class="inline">Top-p <input class="field sm" type="number" bind:value={top_p} min="0.1" max="1" step="0.05" /></label>
      </div>
      <p class="muted small">Zelfde beschrijving + zelfde seed ≈ zelfde stem. Varieer de seed om meerdere kandidaten uit één beschrijving te maken.</p>
    </details>
  </div>

  <div class="actions">
    <button onclick={generate} disabled={busy || !ready()}>{busy ? "Genereren… (kan een minuut duren)" : "Genereer sample"}</button>
    {#if status?.busy}<span class="muted small">Engine is bezig…</span>{/if}
  </div>

  <div class="section">
    <h3>Resultaten <span class="muted">({files.length})</span></h3>
    {#if outDir}<p class="mono small">{outDir}</p>{/if}
    {#if files.length === 0}
      <p class="muted small">Nog geen samples — genereer hierboven je eerste. Elke generatie slaat een WAV op die je hier kunt beluisteren.</p>
    {:else}
      <ul class="files">
        {#each files as f (f.name)}
          <li class="file">
            <div class="file-head">
              <strong class="mono">{f.name}</strong>
              <span class="muted small">{fmtSize(f.size)} · {fmtDate(f.mtime)}</span>
            </div>
            <audio controls preload="none" src={api.voiceDesignAudioUrl(f.name)} data-vd={f.name}></audio>
            <div class="row">
              <label class="inline">Tempo
                <select
                  value={speedOf[f.name] ?? 1}
                  onchange={(e) => setSpeed(f.name, Number((e.target as HTMLSelectElement).value))}
                  title="Afluistersnelheid — wordt ook gebruikt bij wegschrijven"
                >
                  {#each SPEEDS as s}<option value={s}>{s}×</option>{/each}
                </select>
              </label>
              <button
                class="ghost"
                onclick={() => renderSpeed(f.name)}
                disabled={rendering === f.name || (speedOf[f.name] ?? 1) === 1}
                title="Schrijf deze versie (op gehoorde snelheid) weg als nieuwe WAV"
              >{rendering === f.name ? "Schrijven…" : "Bewaar op deze snelheid"}</button>
            </div>
            <div class="row">
              <input class="field grow" placeholder="Stem-naam voor samples-map…" bind:value={promoteName[f.name]} maxlength="80" />
              <button class="ghost" onclick={() => promote(f.name)} title="Kopieer naar samples-map als clone-stem">Naar samples</button>
              <a class="ghost btn" href={api.voiceDesignAudioUrl(f.name)} download={f.name}>Download</a>
              <button class="danger" onclick={() => remove(f.name)}>Wis</button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>

<style>
  .panel{ display:flex; flex-direction:column; gap:1rem; max-width:860px; }
  .page-head{ display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; align-items:flex-start; }
  .page-head h2{ margin:0; font-size:1.25rem; letter-spacing:-0.02em; }
  .tag{ font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; background:#2a2430; border:1px solid #4a3a50; color:#d8b8e6; border-radius:999px; padding:0.15rem 0.55rem; vertical-align:middle; }
  .subtitle{ margin:0.2rem 0 0; color:#8b8e9a; font-size:0.82rem; max-width:60ch; }
  .callout{ margin:0; border-radius:10px; padding:0.6rem 0.8rem; font-size:0.85rem; word-break:break-word; }
  .callout.error{ background:#2a1f24; border:1px solid #3a2a2e; color:#ffb4b4; }
  .callout.info{ background:#1c2330; border:1px solid #2a3550; color:#a8b8e6; }
  .muted{ color:#8b8e9a; } .small{ font-size:0.8rem; } .mono{ font-family:ui-monospace,monospace; }
  .mono.small{ font-size:0.76rem; color:#8b8e9a; word-break:break-all; }
  .section{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:1rem 1.1rem; display:flex; flex-direction:column; gap:0.75rem; }
  .section h3{ margin:0; font-size:0.95rem; letter-spacing:-0.01em; }
  .field{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; line-height:1.4; width:100%; font-family:inherit; }
  .field.sm{ max-width:90px; }
  textarea.field{ resize:vertical; }
  input.field:focus, textarea.field:focus, select:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  select{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.5rem 0.7rem; font-size:0.88rem; }
  .row{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:end; }
  .inline{ display:flex; flex-direction:column; gap:0.25rem; font-size:0.78rem; color:#8b8e9a; font-weight:550; text-transform:uppercase; letter-spacing:0.04em; }
  .grow{ flex:1; min-width:180px; }
  .col{ display:flex; flex-direction:column; gap:0.25rem; font-size:0.78rem; color:#8b8e9a; font-weight:550; text-transform:uppercase; letter-spacing:0.04em; }
  .grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:0.6rem; }
  .grid label{ display:flex; flex-direction:column; gap:0.25rem; font-size:0.78rem; color:#8b8e9a; font-weight:550; text-transform:uppercase; letter-spacing:0.04em; }
  .adv{ font-size:0.85rem; color:#8b8e9a; }
  .adv summary{ cursor:pointer; font-weight:550; }
  .adv .row{ margin-top:0.5rem; }
  .actions{ display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center; }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.52rem 1rem; cursor:pointer; font-size:0.88rem; font-weight:550; line-height:1; }
  button:hover:not(:disabled){ background:#4458aa; }
  button.ghost, a.btn.ghost{ background:#232634; color:#e8e8ec; text-decoration:none; display:inline-block; border-radius:9px; padding:0.52rem 1rem; font-size:0.88rem; font-weight:550; }
  button.ghost:hover:not(:disabled), a.btn.ghost:hover{ background:#2a2e40; }
  button.danger{ background:#3a2328; color:#ffb4b4; }
  button.danger:hover:not(:disabled){ background:#4a2b31; }
  button:disabled{ opacity:0.5; cursor:default; }
  .files{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:0.75rem; }
  .file{ background:#14151a; border:1px solid #2a2d36; border-radius:10px; padding:0.75rem; display:flex; flex-direction:column; gap:0.5rem; }
  .file-head{ display:flex; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; align-items:baseline; }
  .file-head .mono{ font-size:0.82rem; word-break:break-all; }
  audio{ width:100%; height:36px; }
</style>
