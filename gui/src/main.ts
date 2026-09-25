import { mount } from "svelte";
import App from "./App.svelte";
import CutterApp from "./lib/cutter/CutterApp.svelte";

// One bundle, two windows. The main window loads the app root; the Perfect Cut
// window is declared in tauri.conf.json with `index.html#/cutter`, so it lands
// here with the hash set and mounts the tool instead. Keeping it on a separate
// window (rather than a nav entry) is deliberate — see CutterApp.svelte.
const isCutter = window.location.hash.replace(/^#\/?/, "").startsWith("cutter");

const app = mount(isCutter ? CutterApp : App, {
  target: document.getElementById("app")!,
});

export default app;
