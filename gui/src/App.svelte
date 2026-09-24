<script lang="ts">
  import Dashboard from "./lib/components/Dashboard.svelte";
  import SpeakersPanel from "./lib/components/SpeakersPanel.svelte";
  import BlacklistPanel from "./lib/components/BlacklistPanel.svelte";
  import EmotionsPanel from "./lib/components/EmotionsPanel.svelte";
  import SettingsPanel from "./lib/components/SettingsPanel.svelte";

  let tab: "dashboard" | "speakers" | "blacklist" | "emotions" | "settings" = "dashboard";
</script>

<main class="app">
  <aside class="sidebar">
    <div class="brand">
      <h1>NovaTTS</h1>
      <span class="brand-sub">Qwen3 · RenPy clipboard</span>
    </div>
    <nav aria-label="Primary">
      <button class:active={tab === "dashboard"} onclick={() => (tab = "dashboard")}>
        <span class="ico">◉</span> Dashboard
      </button>
      <button class:active={tab === "speakers"} onclick={() => (tab = "speakers")}>
        <span class="ico">◎</span> Characters
      </button>
      <button class:active={tab === "blacklist"} onclick={() => (tab = "blacklist")}>
        <span class="ico">⊘</span> Blacklist
      </button>
      <button class:active={tab === "emotions"} onclick={() => (tab = "emotions")}>
        <span class="ico">♪</span> Emotions
      </button>
      <button class:active={tab === "settings"} onclick={() => (tab = "settings")}>
        <span class="ico">⚙</span> Settings
      </button>
    </nav>
    <p class="hint">Close the window → backend/Qwen keep polling — use <code>stop_all.cmd</code>.</p>
  </aside>

  <section class="content">
    {#if tab === "dashboard"}
      <Dashboard />
    {:else if tab === "speakers"}
      <SpeakersPanel />
    {:else if tab === "blacklist"}
      <BlacklistPanel />
    {:else if tab === "emotions"}
      <EmotionsPanel />
    {:else}
      <SettingsPanel />
    {/if}
  </section>
</main>

<style>
  :global(:root) {
    --background: #14151a;
    --foreground: #e8e8ec;
    --muted-foreground: #8b8e9a;
    --card: #1e2027;
    --border: #2a2d36;
    --accent: #3b4b8f;
  }
  .app {
    display: flex;
    height: 100vh;
    background: #14151a;
    color: #e8e8ec;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  }
  .sidebar {
    width: 230px;
    min-width: 230px;
    padding: 1.1rem 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
    background: #1b1d24;
    border-right: 1px solid #2a2d36;
  }
  .brand h1 {
    font-size: 1.2rem;
    margin: 0;
    letter-spacing: -0.02em;
    font-weight: 750;
  }
  .brand-sub{ font-size:0.72rem; color:#8b8e9a; letter-spacing:0.04em; }
  nav {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  nav button {
    display:flex; align-items:center; gap:0.55rem;
    text-align: left;
    padding: 0.6rem 0.75rem;
    border: 1px solid transparent;
    border-radius: 10px;
    background: transparent;
    color: #b6b8c0;
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 500;
  }
  .ico{ width:1.1rem; text-align:center; font-size:0.85rem; opacity:0.9; }
  nav button:hover {
    background: #232634;
    border-color:#2a2d36;
    color:#e8e8ec;
  }
  nav button.active {
    background: #3b4b8f;
    border-color:#4a5aa8;
    color: #fff;
  }
  .hint{ margin:auto 0 0; color:#6b6e79; font-size:0.72rem; line-height:1.4; border-top:1px solid #2a2d36; padding-top:0.75rem; }
  .hint code{ background:#232634; padding:0.1rem 0.3rem; border-radius:5px; font-size:0.7rem; }
  .content {
    flex: 1;
    min-width:0;
    overflow-y: auto;
    padding: 1.4rem 1.5rem 1.5rem;
  }
</style>
