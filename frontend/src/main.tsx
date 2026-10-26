import { createRoot } from "react-dom/client";
import { App } from "./App";
import type { PrivateEntry } from "./Auth";
import "./style.css";

// Read before mounting: the fragment is never sent to the server and is removed
// before any API call. Tokens stay only in this page's transient memory.
const path = window.location.pathname;
let entry: PrivateEntry = null;
if (path === "/invitation" || path === "/reinitialisation") {
  const candidate =
    new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
  entry = {
    kind: path === "/invitation" ? "invitation" : "reinitialisation",
    token: /^[A-Za-z0-9_-]{40,64}$/.test(candidate) ? candidate : "",
  };
}
if (window.location.hash || window.location.search)
  window.history.replaceState(null, "", path);
createRoot(document.getElementById("root")!).render(
  <App initialEntry={entry} />,
);
entry = null;
