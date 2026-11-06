<script lang="ts">
  // First-run setup: ask where the Qwen engine and its models live instead of
  // assuming a path baked into the build. Whatever the user picks is written
  // to the backend .env through POST /settings (the same route the Settings
  // panel uses), so a packaged app never starts with someone else's paths.
  import { onMount } from "svelte";
  import { api } from "../api";
  import type { PathStatus, SetupDefaults } from "../types";
  import PathField from "./PathField.svelte";

  let { onclose }: { onclose: () => void } = $props();

  type PathKey = "qwen_bin" | "qwen_model" | "qwen_codec" | "qwen_codec_bin" | "qwen_samples_dir";

  const REQUIRED: PathKey[] = ["qwen_bin", "qwen_model", "qwen_codec"];

  let form = $state<Record<PathKey, string>>({
    qwen_bin: "",
    qwen_model: "",
    qwen_codec: "",
    qwen_codec_bin: "",
    qwen_samples_dir: "",
  });
  let pathStatus: Record<string, PathStatus> = $state({});
  let defaults: SetupDefaults | null = $state(null);
  let envFile = $state("");
  let err = $state("");
  let info = $state("");
  let loading = $state(true);
  let saving = $state(false);

  const load = async () => {
    loading = true;
    err = "";
    try {
      const [settings, suggestions] = await Promise.all([
        api.settings(),
        api.setupDefaults().catch(() => null),
      ]);
      defaults = suggestions;
      for (const key of Object.keys(form) as PathKey[]) form[key] = settings.settings[key] ?? "";
      pathStatus = settings.path_status ?? {};
      envFile = settings.env_file ?? suggestions?.env_file ?? "";
      if (suggestions && REQUIRED.some((k) => !pathStatus[k]?.exists)) {
        // Nothing usable configured yet: pre-fill only the suggestions that
        // actually exist on this machine, never a path from another install.
        for (const key of Object.keys(form) as PathKey[]) {
          const s = suggestions.paths[key];
          if (s?.exists && s.suggested) form[key] = s.suggested;
        }
      }
    } catch (e) {
      err = `Could not load settings: ${(e as Error).message}`;
    }
    loading = false;
  };

  const useSuggestions = () => {
    if (!defaults) return;
    info = "";
    err = "";
    let applied = 0;
    for (const key of Object.keys(form) as PathKey[]) {
      const s = defaults.paths[key];
      if (s?.suggested && s.exists) {
        form[key] = s.suggested;
        applied++;
      }
    }
    info = applied
      ? `Filled ${applied} path(s) that exist on this machine.`
      : "No suggested paths were found. Use Browse… to pick them.";
  };

  const save = async () => {
    saving = true;
    err = "";
    info = "";
    try {
      const res = await api.updateSettings({
        qwen_bin: form.qwen_bin.trim(),
        qwen_model: form.qwen_model.trim(),
        qwen_codec: form.qwen_codec.trim(),
        qwen_codec_bin: form.qwen_codec_bin.trim(),
        qwen_samples_dir: form.qwen_samples_dir.trim(),
        qwen_autostart: true,
        qwen_auto_import_samples: true,
      });
      pathStatus = res.path_status;
      envFile = envFile || "";
      const missing = REQUIRED.filter((k) => !res.path_status[k]?.exists);
      if (missing.length) {
        err = `Still missing or not found: ${missing
          .map((k) => k.replace("qwen_", "").replace("_", " "))
          .join(", ")}. Pick an existing file and save again.`;
        saving = false;
        return;
      }
      onclose();
    } catch (e) {
      err = (e as Error).message;
    }
    saving = false;
  };

  onMount(load);
</script>

<div class="overlay" role="dialog" aria-modal="true" aria-labelledby="setup-title">
  <div class="card">
    <header>
      <h2 id="setup-title">Set up the Qwen engine</h2>
      <p class="subtitle">
        NovaTTS needs the local Qwen3-TTS server and its model files. Point it at the copies
        on this machine — the paths are saved to <code>{envFile || ".env"}</code> and can be
        changed later in Settings.
      </p>
    </header>

    {#if err}<p class="callout error">{err}</p>{/if}
    {#if info}<p class="callout info">{info}</p>{/if}

    {#if loading}
      <p class="muted">Looking for existing paths…</p>
    {:else}
      <div class="grid">
        <PathField
          label="tts-server binary"
          kind="exe"
          bind:value={form.qwen_bin}
          placeholder="…\AI-Tools\qwentts.cpp\build\Release\tts-server.exe"
          status={pathStatus.qwen_bin}
        />
        <PathField
          label="Talker model (.gguf)"
          kind="model"
          bind:value={form.qwen_model}
          placeholder="…\models\qwen-talker-1.7b-base-Q8_0.gguf"
          status={pathStatus.qwen_model}
        />
        <PathField
          label="Tokenizer / codec (.gguf)"
          kind="model"
          bind:value={form.qwen_codec}
          placeholder="…\models\qwen-tokenizer-12hz-Q8_0.gguf"
          status={pathStatus.qwen_codec}
        />
        <PathField
          label="qwen-codec binary (optional)"
          kind="exe"
          bind:value={form.qwen_codec_bin}
          placeholder="auto = next to tts-server.exe"
          status={pathStatus.qwen_codec_bin}
        />
        <PathField
          label="Voice samples folder"
          kind="dir"
          bind:value={form.qwen_samples_dir}
          placeholder="folder with .wav voices (optional)"
          status={pathStatus.qwen_samples_dir}
        />
      </div>

      <p class="muted small">
        The AI-tools installer puts the engine under
        <code>%LOCALAPPDATA%\NovaTTS\AI-Tools\qwentts.cpp</code>; if that build exists,
        “Use suggested paths” fills it in.
      </p>

      <footer>
        <button class="ghost" onclick={useSuggestions} disabled={saving || !defaults}>
          Use suggested paths
        </button>
        <span class="spacer"></span>
        <button class="ghost" onclick={onclose} disabled={saving}>Skip for now</button>
        <button onclick={save} disabled={saving}>{saving ? "Saving…" : "Save & continue"}</button>
      </footer>
    {/if}
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    background: rgba(10, 11, 15, 0.82);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }
  .card {
    width: min(720px, 100%);
    max-height: 100%;
    overflow-y: auto;
    background: #1b1d24;
    border: 1px solid #2a2d36;
    border-radius: 14px;
    padding: 1.3rem 1.4rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.55);
  }
  h2 { margin: 0; font-size: 1.2rem; letter-spacing: -0.02em; }
  .subtitle { margin: 0.35rem 0 0; color: #8b8e9a; font-size: 0.85rem; line-height: 1.5; }
  code {
    background: #232634;
    border-radius: 5px;
    padding: 0.08rem 0.3rem;
    font-size: 0.78rem;
    font-family: ui-monospace, monospace;
  }
  .grid { display: flex; flex-direction: column; gap: 0.75rem; }
  .muted { color: #8b8e9a; }
  .small { font-size: 0.8rem; margin: 0; }
  .callout { margin: 0; border-radius: 10px; padding: 0.6rem 0.8rem; font-size: 0.85rem; word-break: break-word; }
  .callout.error { background: #2a1f24; border: 1px solid #3a2a2e; color: #ffb4b4; }
  .callout.info { background: #1c2330; border: 1px solid #2a3550; color: #a8b8e6; }
  footer { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
  .spacer { flex: 1; }
  button {
    background: #3b4b8f;
    color: #fff;
    border: none;
    border-radius: 9px;
    padding: 0.55rem 1.05rem;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 550;
    line-height: 1;
  }
  button:hover:not(:disabled) { background: #4458aa; }
  button.ghost { background: #232634; color: #e8e8ec; }
  button.ghost:hover:not(:disabled) { background: #2a2e40; }
  button:disabled { opacity: 0.5; cursor: default; }
</style>
