<script lang="ts">
  // Tab 1 — Sample Cutter. Waveform, selection, preview, ffmpeg export.
  //
  // Same surface as the tkinter tool, plus the edgelock utterance navigation
  // that used to be dead code (see ./edgelock.ts and ./select.ts).

  import Waveform from "./Waveform.svelte";
  import { analyzeBytes, audioContext, MAX_DECODE_BYTES, playSlice, type PlayHandle } from "./audio";
  import { cutterApi, exportMode } from "./api";
  import {
    expandToUtterances,
    nearestSilence,
    nextUtterance,
    prevUtterance,
    summarise,
    utteranceIndexAt,
    windowFor,
    type Window,
  } from "./select";
  import { fmtSeconds, fmtTime, parseTime } from "./time";
  import { pickSaveWav, pickWav, readAudioFile } from "./tauri";
  import type { AudioAnalysis, CutterConfig } from "./types";

  interface Props {
    config: CutterConfig;
    onstatus: (msg: string) => void;
    onoutput: (path: string) => void;
  }

  let { config, onstatus, onoutput }: Props = $props();

  let filePath = $state("");
  let buffer = $state<AudioBuffer | null>(null);
  let analysis = $state<AudioAnalysis | null>(null);
  let loading = $state(false);
  let exporting = $state(false);

  let start = $state(0);
  let end = $state(0);
  let playhead = $state(0);
  let startText = $state("00:00.000");
  let endText = $state("00:00.000");
  let outPath = $state("");
  let showSilences = $state(true);
  let qwenPreset = $state(true);
  let keepSr = $state(false);
  /** How many consecutive utterances "auto-select" should grab. */
  let groupSize = $state(1);
  /**
   * Index of the utterance the current selection was built from, or -1 when
   * the selection was made by hand (drag, time field, snap). The next/previous
   * buttons step from here, so repeated clicks walk the file instead of
   * re-picking the same utterance.
   */
  let anchor = $state(-1);

  let wave: Waveform;
  let handle: PlayHandle | null = null;
  let rafId = 0;
  let playBase = 0;
  let playStop = 0;
  let playCtxStart = 0;

  const duration = () => analysis?.duration ?? 0;
  const hasFile = () => !!analysis;
  const sel = () => Math.max(0, end - start);
  const basename = (p: string) => p.split(/[\\/]/).pop() ?? p;
  const stamp = (t: number) => fmtTime(t).replace(/:/g, "-");

  // --- loading ---------------------------------------------------------

  async function open() {
    const p = await pickWav();
    if (p) await load(p);
  }

  async function load(path: string) {
    loading = true;
    stop();
    try {
      onstatus(`Reading ${path}…`);
      const bytes = await readAudioFile(path);
      if (bytes.byteLength > MAX_DECODE_BYTES) {
        throw new Error(`${(bytes.byteLength / 1048576).toFixed(0)} MB is over the 200 MB limit`);
      }
      const { buffer: buf, analysis: a } = await analyzeBytes(bytes);
      buffer = buf;
      analysis = a;
      filePath = path;
      start = 0;
      end = a.duration;
      playhead = 0;
      anchor = -1;
      startText = fmtTime(0);
      endText = fmtTime(a.duration);
      suggestOutput();
      wave?.fitAll();
      onstatus(
        `${basename(path)} — ${a.fileRate} Hz · ${a.channels} ch · ${fmtTime(a.duration)} · ` +
          summarise(a.detection.utterances, a.duration),
      );
    } catch (e) {
      analysis = null;
      buffer = null;
      filePath = "";
      onstatus(`✗ could not open: ${(e as Error).message}`);
    } finally {
      loading = false;
    }
  }

  // --- selection -------------------------------------------------------

  function suggestOutput() {
    if (!filePath) return;
    const base = filePath.replace(/\.wav$/i, "");
    outPath = `${base}_cut_${stamp(start)}_${stamp(end)}.wav`;
  }

  function setSelection(a: number, b: number) {
    if (!analysis) return;
    const lo = Math.max(0, Math.min(a, b));
    const hi = Math.min(analysis.duration, Math.max(a, b));
    start = lo;
    end = hi;
    startText = fmtTime(lo);
    endText = fmtTime(hi);
    // A hand-made selection is no longer tied to a detected utterance.
    anchor = -1;
    suggestOutput();
  }

  function setPlayhead(t: number) {
    playhead = Math.max(0, Math.min(duration(), t));
  }

  function applyTimeFields(): string | null {
    if (!analysis) return null;
    const s = parseTime(startText);
    const e = parseTime(endText);
    if (s === null || e === null) return "bad time format — use 00:05.200 or 5.2";
    let a = Math.max(0, Math.min(s, analysis.duration));
    let b = Math.max(0, Math.min(e, analysis.duration));
    if (e < s) [a, b] = [b, a];
    setSelection(a, b);
    return null;
  }

  function nudge(which: "start" | "end", delta: number) {
    if (!analysis) return;
    if (which === "start") setSelection(Math.max(0, start + delta), end);
    else setSelection(start, Math.min(analysis.duration, end + delta));
  }

  function resetSelection() {
    if (!analysis) return;
    setSelection(0, analysis.duration);
  }

  // --- silence / utterance snapping -------------------------------------

  /** The original tool's "Autosnap stilte": nearest quiet frame. Kept for parity. */
  function autosnapQuiet() {
    if (!analysis) return;
    const s = nearestSilence(analysis, start);
    const e = nearestSilence(analysis, end);
    setSelection(s, e);
    onstatus(`Snapped to nearest quiet frame → ${fmtTime(s)} … ${fmtTime(e)}`);
  }

  /** The real edgelock snap: whole utterance, silence-aligned, zero-crossed. */
  function autoSelectNext() {
    if (!analysis) return;
    if (!analysis.detection.utterances.length) {
      onstatus("No speech detected in this file.");
      return;
    }
    // Step on from the current utterance when there is one, otherwise from
    // wherever the playhead is.
    const i =
      anchor >= 0 ? anchor + 1 : nextUtterance(analysis, playhead);
    if (i < 0 || i >= analysis.detection.utterances.length) {
      onstatus("No utterance after the selection.");
      return;
    }
    report(expandToUtterances(analysis, i, groupSize), i);
  }

  function selectPrev() {
    if (!analysis) return;
    if (!analysis.detection.utterances.length) {
      onstatus("No speech detected in this file.");
      return;
    }
    const i = anchor > 0 ? anchor - 1 : prevUtterance(analysis, start);
    if (i < 0) {
      onstatus("No utterance before the selection.");
      return;
    }
    report(expandToUtterances(analysis, i, groupSize), i);
  }

  function jumpToUtterance(index: number) {
    if (!analysis) return;
    report(windowFor(analysis, index), index);
  }

  function report(w: Window | null, index: number) {
    if (!w) {
      onstatus(`Utterance ${index + 1} runs into the next onset — no clean boundary to cut on.`);
      return;
    }
    setSelection(w.start, w.end);
    // setSelection clears the anchor, so claim it after.
    anchor = index;
    setPlayhead(w.start);
    wave?.zoomToSelection();
    onstatus(
      `Utterance ${index + 1}: ${fmtTime(w.start)} → ${fmtTime(w.end)} ` +
        `(${fmtSeconds(w.end - w.start)}) — ${w.reason} / ${w.reasonEnd}`,
    );
  }

  const currentUtterance = () =>
    anchor >= 0 ? anchor : analysis ? utteranceIndexAt(analysis, playhead) : -1;

  // --- playback ---------------------------------------------------------

  function tick() {
    if (!analysis) return;
    playhead = Math.max(0, Math.min(duration(), playBase + (audioContext().currentTime - playCtxStart)));
    // Stop on the *playback* end, not the selection end — "▶ All" plays past
    // the selection and must not cut short there.
    if (handle && playhead >= playStop - 1e-4) {
      stop();
      return;
    }
    rafId = requestAnimationFrame(tick);
  }

  function play(from: number, to: number) {
    if (!analysis || !buffer) return;
    stop();
    const h = playSlice(buffer, analysis, {
      offsetSec: from,
      durationSec: to - from,
      onEnded: () => stop(),
    });
    if (!h) {
      onstatus("Selection is too short to play.");
      return;
    }
    handle = h;
    playBase = from;
    playStop = to;
    playCtxStart = audioContext().currentTime;
    playhead = from;
    rafId = requestAnimationFrame(tick);
    onstatus(`▶ ${fmtTime(from)} → ${fmtTime(to)} (${fmtSeconds(to - from)})`);
  }

  function playAll() {
    if (!analysis) return;
    play(playhead >= duration() - 0.05 ? 0 : playhead, duration());
  }

  function playSelection() {
    if (!analysis) return;
    if (end - start < 0.02) {
      onstatus("Selection is under 20 ms.");
      return;
    }
    play(start, end);
  }

  function stop() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    handle?.stop();
    handle = null;
  }

  // --- export -----------------------------------------------------------

  async function doExport() {
    if (!filePath || !analysis) return;
    if (sel() < 0.05) {
      onstatus("Selection is under 50 ms.");
      return;
    }
    exporting = true;
    onstatus(`Cutting ${fmtTime(start)} → ${fmtTime(end)}…`);
    try {
      const r = await cutterApi.exportCut({
        src: filePath,
        out: outPath,
        start,
        end,
        mode: exportMode(qwenPreset, keepSr),
      });
      onstatus(
        `✓ ${basename(r.out)} — ${r.rate} Hz · ${r.channels} ch · ${r.duration.toFixed(2)}s (${r.via})`,
      );
    } catch (e) {
      onstatus(`✗ export failed: ${(e as Error).message}`);
    } finally {
      exporting = false;
    }
  }

  async function browseOutput() {
    const p = await pickSaveWav(basename(outPath) || "cut.wav", filePath);
    if (p) outPath = p;
  }

  // --- keyboard ---------------------------------------------------------

  function onKey(e: KeyboardEvent) {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    const step = e.shiftKey ? 0.1 : 0.01;
    switch (e.key) {
      case " ":
        e.preventDefault();
        handle ? stop() : playSelection();
        break;
      case "ArrowLeft":
        e.preventDefault();
        setPlayhead(playhead - (e.ctrlKey ? 1 : step));
        break;
      case "ArrowRight":
        e.preventDefault();
        setPlayhead(playhead + (e.ctrlKey ? 1 : step));
        break;
      case "Home":
        setPlayhead(0);
        break;
      case "End":
        setPlayhead(duration());
        break;
      case "i":
      case "I":
        nudge("start", -step);
        break;
      case "o":
      case "O":
        nudge("end", step);
        break;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<section class="cutter">
  <div class="row head">
    <button onclick={open} disabled={loading}>{loading ? "Reading…" : "Open WAV"}</button>
    <span class="file" class:empty={!filePath} title={filePath}>
      <span class="fname">{filePath ? basename(filePath) : "No file loaded"}</span>
      {#if analysis}
        <span class="meta">{analysis.fileRate} Hz · {analysis.channels} ch · {fmtTime(analysis.duration)}</span>
      {/if}
    </span>
    <span class="spacer"></span>
    {#if analysis}
      <span class="meta" title="Detected by the edgelock detector">
        {analysis.detection.utterances.length} utt · {analysis.detection.silences.length} sil · thr
        {analysis.detection.threshold.toFixed(1)} dB
      </span>
    {/if}
  </div>

  <div class="wave-wrap">
    <Waveform
      bind:this={wave}
      {analysis}
      {start}
      {end}
      {playhead}
      {showSilences}
      onselect={setSelection}
      onplayhead={setPlayhead}
      onzoom={(center, factor) => wave.zoomAround(center, factor)}
    />
    <p class="hint">
      drag = select · shift/middle-click = playhead · double-click = collapse · wheel = zoom ·
      space = play/stop · <kbd>i</kbd>/<kbd>o</kbd> = trim edge · <kbd>←</kbd><kbd>→</kbd> = scrub
    </p>
  </div>

  {#if analysis}
    <div class="row nav">
      <button class="ghost" onclick={selectPrev} disabled={!analysis.detection.utterances.length}>← Previous</button>
      <button onclick={autoSelectNext} disabled={!analysis.detection.utterances.length}>Auto-select next utterance</button>
      <label class="chk" title="Grab this many consecutive utterances in one selection">
        <input type="number" class="num" min="1" max="6" bind:value={groupSize} />×
      </label>
      <button class="ghost" onclick={autosnapQuiet} disabled={!analysis.detection.silences.length}>Snap to quiet frame</button>
      <label class="chk"><input type="checkbox" bind:checked={showSilences} /> shade silences</label>
      <span class="spacer"></span>
      <span class="meta">
        {currentUtterance() >= 0
          ? `utterance ${currentUtterance() + 1}/${analysis.detection.utterances.length}`
          : "—"}
      </span>
    </div>

    <div class="strip" title="Detected utterances — click to select">
      {#each analysis.detection.utterances as u, i (i)}
        <button
          class="utt"
          class:on={i === currentUtterance()}
          style="left:{(u.start / analysis.duration) * 100}%;width:{Math.max(0.35, ((u.end - u.start) / analysis.duration) * 100)}%"
          title={`utterance ${i + 1}: ${fmtTime(u.start)} → ${fmtTime(u.end)}`}
          onclick={() => jumpToUtterance(i)}
        >
          {i + 1}
        </button>
      {/each}
    </div>

    <div class="panel">
      <div class="grid">
        <label class="f">
          <span>Start</span>
          <div class="fv">
            <input
              class="mono"
              bind:value={startText}
              onchange={() => { const e = applyTimeFields(); if (e) onstatus(e); }}
              onkeydown={(e) => e.key === "Enter" && applyTimeFields()}
            />
            <button class="ghost sm" title="Set start to the playhead" onclick={() => setSelection(playhead, end)}>set</button>
            <button class="ghost sm" title="−10 ms" onclick={() => nudge("start", -0.01)}>−</button>
            <button class="ghost sm" title="+10 ms" onclick={() => nudge("start", 0.01)}>+</button>
          </div>
        </label>
        <label class="f">
          <span>End</span>
          <div class="fv">
            <input
              class="mono"
              bind:value={endText}
              onchange={() => { const e = applyTimeFields(); if (e) onstatus(e); }}
              onkeydown={(e) => e.key === "Enter" && applyTimeFields()}
            />
            <button class="ghost sm" title="Set end to the playhead" onclick={() => setSelection(start, playhead)}>set</button>
            <button class="ghost sm" title="−10 ms" onclick={() => nudge("end", -0.01)}>−</button>
            <button class="ghost sm" title="+10 ms" onclick={() => nudge("end", 0.01)}>+</button>
          </div>
        </label>
        <label class="f">
          <span>Playhead</span>
          <div class="fv">
            <input class="mono" value={fmtTime(playhead)} readonly />
            <button class="ghost sm" title="Use playhead as end" onclick={() => setSelection(start, playhead)}>→ end</button>
            <button class="ghost sm" title="Use playhead as start" onclick={() => setSelection(playhead, end)}>← start</button>
          </div>
        </label>
        <label class="f">
          <span>Duration</span>
          <div class="fv">
            <input class="mono" value={`${fmtTime(sel())} · ${fmtSeconds(sel())}`} readonly />
            <button class="ghost sm" onclick={resetSelection}>reset</button>
          </div>
        </label>
      </div>

      <div class="row transport">
        <button onclick={playAll}>▶ All</button>
        <button onclick={playSelection}>▶ Selection</button>
        <button class="ghost" onclick={stop}>■ Stop</button>
        <span class="spacer"></span>
        <button class="ghost" onclick={() => wave?.fitAll()}>Fit</button>
        <button class="ghost" onclick={() => wave?.zoomToSelection()} disabled={sel() <= 0}>Zoom selection</button>
        <button class="ghost" onclick={() => wave?.zoomBy(0.7)}>＋</button>
        <button class="ghost" onclick={() => wave?.zoomBy(1 / 0.7)}>－</button>
      </div>
    </div>

    <div class="panel">
      <label class="f">
        <span>Output</span>
        <div class="fv">
          <input class="mono" bind:value={outPath} placeholder="D:\out\cut.wav" />
          <button class="ghost" onclick={browseOutput}>Browse…</button>
        </div>
      </label>
      <div class="row">
        <label class="chk">
          <input type="checkbox" bind:checked={qwenPreset} onchange={() => (keepSr = false)} />
          Qwen3TTS preset — 24 kHz mono PCM16 + loudnorm
        </label>
        <label class="chk">
          <input type="checkbox" bind:checked={keepSr} onchange={() => (qwenPreset = false)} />
          keep original sample rate
        </label>
        <span class="spacer"></span>
        <button class="ghost" onclick={() => onoutput(outPath)} disabled={!outPath} title="Use this folder as the batch input dir">
          → batch input
        </button>
        <button onclick={doExport} disabled={exporting}>{exporting ? "Cutting…" : "Cut & export"}</button>
      </div>
    </div>
  {/if}
</section>

<style>
  .cutter{ display:flex; flex-direction:column; gap:0.7rem; }
  .row{ display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; }
  .head{ gap:0.6rem; }
  .spacer{ flex:1; }
  .file{ display:flex; flex-direction:column; line-height:1.25; min-width:0; }
  .fname{ font-size:0.85rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:38ch; }
  .file.empty .fname{ color:#6b6e79; }
  .meta{ color:#8b8e9a; font-size:0.72rem; font-family:ui-monospace,monospace; white-space:nowrap; }
  .wave-wrap{ display:flex; flex-direction:column; gap:0.3rem; }
  .hint{ margin:0; color:#6b6e79; font-size:0.72rem; }
  kbd{ background:#232634; border:1px solid #2a2d36; border-radius:4px; padding:0.05rem 0.3rem; font-family:ui-monospace,monospace; font-size:0.68rem; }
  .strip{ position:relative; height:20px; background:#14151a; border:1px solid #2a2d36; border-radius:7px; overflow:hidden; }
  .utt{ position:absolute; top:2px; bottom:2px; min-width:8px; padding:0; background:#232634; border:1px solid #2a2d36; border-radius:4px; color:#8b8e9a; font-size:0.58rem; line-height:1; cursor:pointer; overflow:hidden; }
  .utt:hover{ background:#2a2e40; color:#e8e8ec; }
  .utt.on{ background:#3b4b8f; border-color:#4a5aa8; color:#fff; }
  .panel{ background:#1e2027; border:1px solid #2a2d36; border-radius:12px; padding:0.85rem 1rem; display:flex; flex-direction:column; gap:0.7rem; }
  .grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:0.6rem 1rem; }
  .f{ display:flex; flex-direction:column; gap:0.2rem; min-width:0; }
  .f > span{ font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; color:#8b8e9a; font-weight:600; }
  .fv{ display:flex; gap:0.3rem; align-items:center; }
  .fv input{ flex:1; min-width:0; }
  .transport{ border-top:1px solid #2a2d36; padding-top:0.7rem; }
  .chk{ display:flex; align-items:center; gap:0.4rem; font-size:0.8rem; color:#8b8e9a; cursor:pointer; }
  .chk input{ accent-color:#3b4b8f; }
  input.num{ width:3.2rem; padding:0.3rem 0.35rem; text-align:center; }
  input{ background:#14151a; border:1px solid #343842; color:#e8e8ec; border-radius:9px; padding:0.45rem 0.6rem; font-size:0.85rem; line-height:1.2; }
  input.mono{ font-family:ui-monospace,monospace; }
  input[readonly]{ color:#8b8e9a; }
  input:focus{ outline:none; border-color:#4a5aa8; box-shadow:0 0 0 3px rgba(59,75,143,0.25); }
  button{ background:#3b4b8f; color:#fff; border:none; border-radius:9px; padding:0.5rem 0.85rem; cursor:pointer; font-size:0.84rem; font-weight:550; line-height:1; white-space:nowrap; }
  button:hover:not(:disabled){ background:#4458aa; } button:active:not(:disabled){ background:#35468a; }
  button.ghost{ background:#232634; color:#e8e8ec; } button.ghost:hover:not(:disabled){ background:#2a2e40; }
  button.sm{ padding:0.4rem 0.5rem; font-size:0.74rem; }
  button:disabled{ opacity:0.45; cursor:default; }
</style>
