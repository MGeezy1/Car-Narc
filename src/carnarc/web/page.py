"""The dashboard page. Plain HTML + a little JS, no build step.

All dynamic content is inserted with textContent / DOM methods (never innerHTML),
so watchlist labels and plate text cannot inject markup.
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Car Narc</title>
<style>
  :root { --bg:#fff; --fg:#1b1f24; --muted:#6a737d; --line:#d8dde3; --card:#f6f8fa; --hit:#c62828; --near:#b26a00; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1318; --fg:#e6e9ed; --muted:#8b949e; --line:#2a313a; --card:#161b22; --hit:#ff6b6b; --near:#f0b429; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.4 system-ui, sans-serif; background:var(--bg); color:var(--fg); }
  header { display:flex; justify-content:space-between; align-items:baseline; padding:14px 16px; border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:18px; }
  #status { color:var(--muted); font-size:13px; }
  main { max-width:960px; margin:0 auto; padding:16px; }
  section { margin-bottom:28px; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 8px; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); vertical-align:middle; }
  td img { height:36px; border-radius:3px; display:block; }
  .plate { font:600 18px ui-monospace, monospace; letter-spacing:.08em; }
  .conf { color:var(--muted); font-size:13px; }
  .badge { font-size:12px; padding:1px 6px; border-radius:10px; border:1px solid currentColor; }
  .hit { color:var(--hit); } .near { color:var(--near); }
  form { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
  input, button { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--fg); }
  button { cursor:pointer; }
  .empty { color:var(--muted); padding:14px 6px; }
  a { color:inherit; }
</style>
</head>
<body>
<header><h1>Car Narc</h1><span id="status">loading...</span></header>
<main>
  <section>
    <h2>Recent plates</h2>
    <table>
      <thead><tr><th></th><th>Plate</th><th>Confidence</th><th>Seen</th><th></th></tr></thead>
      <tbody id="reads"></tbody>
    </table>
    <div id="reads-empty" class="empty" hidden>No plates yet.</div>
  </section>
  <section>
    <h2>Watchlist</h2>
    <form id="wl-form">
      <input id="wl-plate" placeholder="Plate" maxlength="10" required autocomplete="off">
      <input id="wl-label" placeholder="Label (optional)" maxlength="60" autocomplete="off">
      <button type="submit">Add</button>
    </form>
    <table><tbody id="watchlist"></tbody></table>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const n = Object.assign(document.createElement(tag), props);
  kids.forEach((k) => n.append(k));
  return n;
};
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.status === 204 ? null : r.json();
};

function readRow(r) {
  const thumb = r.crop
    ? el("a", { href: "/snapshots/" + r.snapshot, target: "_blank" }, el("img", { src: "/snapshots/" + r.crop, alt: "" }))
    : el("span");
  const seen = new Date(r.ts * 1000).toLocaleString();
  const badge = r.watchlist_hit === 1 ? el("span", { className: "badge hit", textContent: "WATCHLIST" })
              : r.watchlist_hit === 2 ? el("span", { className: "badge near", textContent: "NEAR MATCH" })
              : el("span");
  const alts = r.alternatives.length ? "also read: " + r.alternatives.map((a) => a[0]).join(", ") : "";
  return el("tr", {},
    el("td", {}, thumb),
    el("td", {}, el("span", { className: "plate", textContent: r.plate }), el("div", { className: "conf", textContent: alts })),
    el("td", { className: "conf", textContent: Math.round(r.confidence * 100) + "% (" + r.n_reads + " reads)" }),
    el("td", { className: "conf", textContent: seen }),
    el("td", {}, badge));
}

async function refresh() {
  try {
    const [status, reads, wl] = await Promise.all([api("/api/status"), api("/api/reads?limit=50"), api("/api/watchlist")]);
    $("status").textContent = status.reads + " reads logged";
    $("reads").replaceChildren(...reads.map(readRow));
    $("reads-empty").hidden = reads.length > 0;
    $("watchlist").replaceChildren(...wl.map((w) => el("tr", {},
      el("td", {}, el("span", { className: "plate", textContent: w.plate })),
      el("td", { className: "conf", textContent: w.label }),
      el("td", {}, el("button", { textContent: "Remove", onclick: async () => {
        await api("/api/watchlist/" + encodeURIComponent(w.plate), { method: "DELETE" });
        refresh();
      } })))));
  } catch (e) {
    $("status").textContent = "disconnected: " + e.message;
  }
}

$("wl-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await api("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plate: $("wl-plate").value, label: $("wl-label").value }),
  });
  ev.target.reset();
  refresh();
});

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
