<script lang="ts">
  // Canvas waveform + loudness view. Replaces the matplotlib FigureCanvasTkAgg
  // pair: two stacked plots (waveform, dBFS) sharing one time axis, with
  // drag-to-select, shift-click playhead, wheel zoom and silence shading.

  import { onMount } from "svelte";
  import { fmtTime } from "./time";
  import type { AudioAnalysis } from "./types";
  import { SILENCE_DB } from "./edgelock";

  interface Props {
    analysis: AudioAnalysis | null;
    start: number;
    end: number;
    playhead: number;
    showSilences: boolean;
    onselect: (start: number, end: number) => void;
    onplayhead: (t: number) => void;
    onzoom: (center: number, factor: number) => void;
  }

  let { analysis, start, end, playhead, showSilences, onselect, onplayhead, onzoom }: Props = $props();

  let canvas: HTMLCanvasElement;
  let host: HTMLDivElement;
  /** Visible time window. */
  let view = $state({ t0: 0, t1: 1 });
  let dragging = $state(false);
  let dragAnchor = 0;
  let hover = $state<number | null>(null);

  const WAVE_H = 132;
  const LOUD_H = 92;
  const GAP = 10;
  const RULER_H = 20;
  const PAD_L = 8;
  const PAD_R = 8;

  const width = () => Math.max(320, host?.clientWidth ?? 640);
  const height = () => RULER_H + WAVE_H + GAP + LOUD_H;

  const timeToX = (t: number) =>
    PAD_L + ((t - view.t0) / Math.max(1e-6, view.t1 - view.t0)) * (width() - PAD_L - PAD_R);
  const xToTime = (x: number) =>
    view.t0 + ((x - PAD_L) / Math.max(1, width() - PAD_L - PAD_R)) * (view.t1 - view.t0);

  /** Visible span, so the view always stays inside the file. */
  function span(): { t0: number; t1: number } {
    if (!analysis) return { t0: 0, t1: 1 };
    const total = analysis.duration;
    let w = Math.min(total, view.t1 - view.t0);
    w = Math.max(0.05, Math.min(w, total));
    let t0 = Math.max(0, Math.min(view.t0, total - w));
    return { t0, t1: t0 + w };
  }

  export function fitAll() {
    if (!analysis) return;
    view = { t0: 0, t1: analysis.duration };
    draw();
  }

  export function zoomTo(t0: number, t1: number) {
    if (!analysis) return;
    const total = analysis.duration;
    let w = Math.max(0.05, Math.min(t1 - t0, total));
    let a = Math.max(0, Math.min(t0, total - w));
    view = { t0: a, t1: a + w };
    draw();
  }

  export function zoomBy(factor: number) {
    if (!analysis) return;
    const { t0, t1 } = span();
    const w = (t1 - t0) * factor;
    zoomTo(t0 + (t1 - t0 - w) / 2, t0 + (t1 - t0 + w) / 2);
  }

  /** Zoom keeping `center` (a time in seconds) at the same screen position. */
  export function zoomAround(center: number, factor: number) {
    if (!analysis) return;
    const { t0, t1 } = span();
    const w = (t1 - t0) * factor;
    const ratio = (center - t0) / Math.max(1e-6, t1 - t0);
    zoomTo(center - w * ratio, center - w * ratio + w);
  }

  /** Zoom to the current selection, with a little breathing room. */
  export function zoomToSelection() {
    if (!analysis || end <= start) return;
    const pad = Math.max(0.1, (end - start) * 0.15);
    zoomTo(Math.max(0, start - pad), Math.min(analysis.duration, end + pad));
  }

  // --- rendering ---------------------------------------------------------

  function draw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = width();
    const h = height();
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    const g = canvas.getContext("2d");
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);

    if (!analysis) {
      g.fillStyle = "#6b6e79";
      g.font = "0.85rem ui-sans-serif, system-ui, sans-serif";
      g.textAlign = "center";
      g.fillText("Open a WAV to see the waveform", w / 2, h / 2);
      return;
    }

    const { t0, t1 } = span();
    const waveTop = RULER_H;
    const loudTop = RULER_H + WAVE_H + GAP;
    const plotW = w - PAD_L - PAD_R;

    // Panels
    g.fillStyle = "#14151a";
    g.fillRect(PAD_L, waveTop, plotW, WAVE_H);
    g.fillRect(PAD_L, loudTop, plotW, LOUD_H);

    drawSilences(g, t0, t1, waveTop, loudTop);
    drawWave(g, t0, t1, waveTop, plotW);
    drawLoudness(g, t0, t1, loudTop, plotW);
    drawDimOutside(g, waveTop, loudTop, plotW);
    drawRuler(g, t0, t1, w);
    drawHandles(g, waveTop, loudTop, plotW);
  }

  function drawSilences(
    g: CanvasRenderingContext2D,
    t0: number,
    t1: number,
    waveTop: number,
    loudTop: number,
  ) {
    if (!showSilences || !analysis) return;
    g.fillStyle = "rgba(48, 164, 108, 0.13)";
    for (const s of analysis.detection.silences) {
      if (s.end < t0 || s.start > t1) continue;
      const a = timeToX(Math.max(s.start, t0));
      const b = timeToX(Math.min(s.end, t1));
      g.fillRect(a, waveTop, Math.max(1, b - a), WAVE_H);
      g.fillRect(a, loudTop, Math.max(1, b - a), LOUD_H);
    }
  }

  function drawWave(g: CanvasRenderingContext2D, t0: number, t1: number, top: number, plotW: number) {
    if (!analysis) return;
    const mid = top + WAVE_H / 2;
    const half = WAVE_H / 2 - 2;
    const n = analysis.envMin.length;
    const first = Math.max(0, Math.floor((t0 / analysis.duration) * n));
    const last = Math.min(n, Math.ceil((t1 / analysis.duration) * n));
    if (last <= first) return;

    g.strokeStyle = "#2a2d36";
    g.beginPath();
    g.moveTo(PAD_L, mid);
    g.lineTo(PAD_L + plotW, mid);
    g.stroke();

    const barW = Math.max(1, plotW / (last - first));
    g.fillStyle = "#3b4b8f";
    g.beginPath();
    for (let i = first; i < last; i++) {
      const t = ((i + 0.5) / n) * analysis.duration;
      const y1 = mid - analysis.envMax[i]! * half;
      const y2 = mid - analysis.envMin[i]! * half;
      g.rect(timeToX(t), y1, barW, Math.max(1, y2 - y1));
    }
    g.fill();
  }

  function drawLoudness(g: CanvasRenderingContext2D, t0: number, t1: number, top: number, plotW: number) {
    if (!analysis) return;
    const { db, hop } = analysis.rms;
    const DB_FLOOR = -60;
    const yFor = (v: number) => top + (1 - (v - DB_FLOOR) / -DB_FLOOR) * LOUD_H;
    const first = Math.max(0, Math.floor(t0 / hop));
    const last = Math.min(db.length, Math.ceil(t1 / hop));
    if (last <= first) return;

    // Filled area under the curve.
    g.beginPath();
    g.moveTo(timeToX(first * hop), yFor(DB_FLOOR));
    for (let i = first; i < last; i++) g.lineTo(timeToX(i * hop), yFor(db[i]!));
    g.lineTo(timeToX((last - 1) * hop), yFor(DB_FLOOR));
    g.closePath();
    g.fillStyle = "rgba(59, 75, 143, 0.35)";
    g.fill();

    g.strokeStyle = "#7dd3fc";
    g.lineWidth = 1;
    g.beginPath();
    for (let i = first; i < last; i++) {
      const x = timeToX(i * hop);
      const y = yFor(db[i]!);
      i === first ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.stroke();

    // Silence threshold + adaptive speech threshold.
    for (const [value, color, label] of [
      [SILENCE_DB, "#e5484d", `silence ${SILENCE_DB} dB`],
      [analysis.detection.threshold, "#e5c76b", `speech ${analysis.detection.threshold.toFixed(1)} dB`],
    ] as [number, string, string][]) {
      const y = yFor(value);
      g.save();
      g.strokeStyle = color;
      g.setLineDash([4, 4]);
      g.globalAlpha = 0.6;
      g.beginPath();
      g.moveTo(PAD_L, y);
      g.lineTo(PAD_L + plotW, y);
      g.stroke();
      g.restore();
      g.fillStyle = color;
      g.globalAlpha = 0.75;
      g.font = "0.62rem ui-monospace, monospace";
      g.textAlign = "left";
      g.fillText(label, PAD_L + 4, y - 3);
      g.globalAlpha = 1;
    }
  }

  function drawDimOutside(g: CanvasRenderingContext2D, waveTop: number, loudTop: number, plotW: number) {
    if (!analysis) return;
    g.fillStyle = "rgba(20, 21, 26, 0.62)";
    const a = timeToX(start);
    const b = timeToX(end);
    if (a > PAD_L) g.fillRect(PAD_L, waveTop, a - PAD_L, WAVE_H);
    if (a > PAD_L) g.fillRect(PAD_L, loudTop, a - PAD_L, LOUD_H);
    if (b < PAD_L + plotW) g.fillRect(b, waveTop, PAD_L + plotW - b, WAVE_H);
    if (b < PAD_L + plotW) g.fillRect(b, loudTop, PAD_L + plotW - b, LOUD_H);

    g.strokeStyle = "#6c8fc7";
    g.lineWidth = 1.5;
    for (const [x, t] of [
      [a, start],
      [b, end],
    ] as [number, number][]) {
      if (t < view.t0 - 1e-6 || t > view.t1 + 1e-6) continue;
      g.beginPath();
      g.moveTo(x, waveTop);
      g.lineTo(x, waveTop + WAVE_H);
      g.moveTo(x, loudTop);
      g.lineTo(x, loudTop + LOUD_H);
      g.stroke();
    }
  }

  function drawHandles(g: CanvasRenderingContext2D, waveTop: number, loudTop: number, plotW: number) {
    // Playhead, plus a time badge while it is on screen.
    if (playhead < view.t0 || playhead > view.t1) return;
    const x = timeToX(playhead);
    g.strokeStyle = "#e5c76b";
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(x, waveTop);
    g.lineTo(x, waveTop + WAVE_H);
    g.moveTo(x, loudTop);
    g.lineTo(x, loudTop + LOUD_H);
    g.stroke();

    const label = fmtTime(playhead);
    g.font = "0.65rem ui-monospace, monospace";
    const tw = g.measureText(label).width + 10;
    const bx = Math.min(Math.max(PAD_L, x - tw / 2), PAD_L + plotW - tw);
    g.fillStyle = "#e5c76b";
    g.beginPath();
    g.roundRect(bx, 2, tw, RULER_H - 6, 4);
    g.fill();
    g.fillStyle = "#14151a";
    g.textAlign = "center";
    g.fillText(label, bx + tw / 2, RULER_H - 9);

    if (hover !== null && !dragging) {
      g.strokeStyle = "rgba(232, 232, 236, 0.28)";
      g.lineWidth = 1;
      g.beginPath();
      const hx = timeToX(hover);
      g.moveTo(hx, waveTop);
      g.lineTo(hx, waveTop + WAVE_H);
      g.stroke();
    }
  }

  function drawRuler(g: CanvasRenderingContext2D, t0: number, t1: number, w: number) {
    const targetTicks = Math.max(2, Math.floor((w - PAD_L - PAD_R) / 90));
    const raw = (t1 - t0) / targetTicks;
    const nice = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    const step = nice.find((n) => n >= raw) ?? nice[nice.length - 1]!;

    g.fillStyle = "#14151a";
    g.fillRect(0, 0, w, RULER_H);
    g.strokeStyle = "#2a2d36";
    g.beginPath();
    g.moveTo(0, RULER_H - 0.5);
    g.lineTo(w, RULER_H - 0.5);
    g.stroke();

    g.fillStyle = "#8b8e9a";
    g.font = "0.62rem ui-monospace, monospace";
    g.textAlign = "left";
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
      const x = timeToX(t);
      g.fillText(fmtTime(t), Math.min(x + 3, w - 44), RULER_H - 6);
    }
  }

  // --- interaction -------------------------------------------------------

  function localX(e: MouseEvent | WheelEvent): number {
    return e.clientX - canvas.getBoundingClientRect().left;
  }

  function onPointerDown(e: PointerEvent) {
    if (!analysis) return;
    const t = xToTime(localX(e));
    if (e.shiftKey || e.button === 1) {
      onplayhead(t);
      return;
    }
    canvas.setPointerCapture(e.pointerId);
    dragging = true;
    dragAnchor = t;
    onselect(t, t);
    draw();
  }

  function onPointerMove(e: PointerEvent) {
    if (!analysis) return;
    const t = Math.max(0, Math.min(analysis.duration, xToTime(localX(e))));
    hover = t;
    if (!dragging) {
      draw();
      return;
    }
    onselect(Math.min(dragAnchor, t), Math.max(dragAnchor, t));
    draw();
  }

  function onPointerUp(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
    // A click (rather than a drag) drops the playhead instead.
    if (Math.abs(xToTime(localX(e)) - dragAnchor) < 0.02) onplayhead(dragAnchor);
    draw();
  }

  function onDoubleClick(e: MouseEvent) {
    if (!analysis) return;
    const t = Math.max(0, Math.min(analysis.duration, xToTime(localX(e))));
    onselect(t, t);
    draw();
  }

  function onWheel(e: WheelEvent) {
    if (!analysis) return;
    e.preventDefault();
    onzoom(xToTime(localX(e)), e.deltaY < 0 ? 0.8 : 1.25);
  }

  // Redraw on prop changes. `view` is deliberately *not* a dependency: the
  // zoom helpers write it, and draw() must stay a pure read of it or this
  // effect would retrigger itself.
  $effect(() => {
    start;
    end;
    playhead;
    showSilences;
    analysis;
    draw();
  });

  let resizeObserver: ResizeObserver | null = null;
  onMount(() => {
    resizeObserver = new ResizeObserver(() => draw());
    if (host) resizeObserver.observe(host);
    return () => resizeObserver?.disconnect();
  });
</script>

<div class="wave-host" bind:this={host}>
  <canvas
    bind:this={canvas}
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    onpointerleave={() => { hover = null; draw(); }}
    ondblclick={onDoubleClick}
    onwheel={onWheel}
  ></canvas>
</div>

<style>
  .wave-host{ position:relative; width:100%; }
  canvas{ display:block; width:100%; border-radius:10px; background:#14151a; border:1px solid #2a2d36; cursor:crosshair; touch-action:none; }
</style>
