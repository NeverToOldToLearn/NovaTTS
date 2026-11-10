<script lang="ts">
  // A path input with a native "Browse…" button.
  //
  // The picker goes through the app's own Tauri commands (see
  // cutter/tauri.ts) instead of a plugin JS API, so no extra capability or
  // fs scope is needed. Outside the desktop shell the command throws and we
  // show that message instead of silently doing nothing.
  import { isDesktop, pickDir, pickExe, pickModel } from "../cutter/tauri";
  import type { PathStatus } from "../types";

  type Kind = "exe" | "model" | "dir";

  let {
    label,
    kind = "dir",
    placeholder = "",
    status = undefined,
    disabled = false,
    // No fallback on purpose: callers bind this to optional settings fields
    // that are still `undefined` while the settings request is in flight.
    // A `$bindable("")` fallback makes Svelte throw props_invalid_value when
    // those bindings are undefined, which aborts the whole panel render.
    value = $bindable(),
  }: {
    label: string;
    kind?: Kind;
    placeholder?: string;
    status?: PathStatus;
    disabled?: boolean;
    value?: string;
  } = $props();

  let error = $state("");
  let desktop = $state(true);

  // Defer the check to the client: `window.__TAURI_INTERNALS__` only exists
  // once the page runs inside the WebView.
  $effect(() => {
    desktop = isDesktop();
  });

  const browse = async () => {
    error = "";
    try {
      const picked =
        kind === "exe"
          ? await pickExe(label, value ?? "")
          : kind === "model"
            ? await pickModel(label, value ?? "")
            : await pickDir(label, value ?? "");
      if (picked) value = picked;
    } catch (e) {
      error = (e as Error).message;
    }
  };
</script>

<div class="field-row">
  <span class="fk">{label}</span>
  <div class="fv">
    <input class="field" bind:value {placeholder} {disabled} spellcheck="false" />
    <button
      type="button"
      class="ghost browse"
      onclick={browse}
      {disabled}
      title={desktop ? "Pick a path" : "Available in the desktop app"}
    >
      Browse…
    </button>
    {#if status}
      <span class="dot" class:ok={status.exists} title={status.path || "not set"}>
        {status.exists ? "✓" : "✗"}
      </span>
    {/if}
  </div>
  {#if error}<span class="err">{error}</span>{/if}
</div>

<style>
  .fk {
    font-size: 0.78rem;
    color: #8b8e9a;
    font-weight: 550;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .fv { display: flex; gap: 0.5rem; align-items: center; }
  .field {
    width: 100%;
    flex: 1;
    font-family: ui-monospace, monospace;
  }
  .browse { flex: 0 0 auto; white-space: nowrap; }
  .dot {
    font-size: 0.8rem;
    font-weight: 700;
    color: #e5484d;
    min-width: 1.2rem;
    text-align: center;
  }
  .dot.ok { color: #30a46c; }
  .err { color: #ffb4b4; font-size: 0.78rem; word-break: break-word; }
</style>
