const $ = (id) => document.getElementById(id);
const AGENT_META = {
  trend: { desc: "Picks today's hottest AI/tech story" },
  script: { desc: "Writes script, title, description, tags (LLM)" },
  voice: { desc: "Generates narration via TTS" },
  video: { desc: "Assembles montage + subtitles (ffmpeg)" },
  thumbnail: { desc: "Renders a click-worthy thumbnail" },
  upload: { desc: "Publishes to YouTube (Data API v3)" },
};

const state = {
  running: false,
  agentStatus: {},
  outputDir: "",
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text) n.textContent = text;
  return n;
}

function log(message, level = "info") {
  const box = $("console");
  const line = el("div", `log-line ${level}`);
  const t = el("span", "t", `[${new Date().toLocaleTimeString()}] `);
  line.append(t, document.createTextNode(message));
  box.appendChild(line);
  while (box.children.length > 500) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

function setPill(ok, text) {
  const p = $("backend-pill");
  p.className = `pill ${ok ? "ok" : "bad"}`;
  p.textContent = text;
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 5000);
}

function buildAgents() {
  const wrap = $("agents");
  wrap.innerHTML = "";
  for (const [name, meta] of Object.entries(AGENT_META)) {
    const card = el("div", "agent-card");
    card.id = `card-${name}`;
    const st = el("div", "agent-status idle");
    const metaBox = el("div", "agent-meta");
    metaBox.append(
      el("div", "agent-name", name),
      el("div", "agent-desc", meta.desc),
      Object.assign(el("div", "agent-bar"), { innerHTML: "<div></div>" })
    );
    const btn = el("button", "agent-btn", "Run");
    btn.onclick = () => runAgent(name);
    card.append(st, metaBox, btn);
    wrap.appendChild(card);
  }
}

function setAgent(name, status, pct = 0) {
  const card = $(`card-${name}`);
  if (!card) return;
  const st = card.querySelector(".agent-status");
  st.className = `agent-status ${status}`;
  const bar = card.querySelector(".agent-bar > div");
  bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  if (status === "idle") bar.style.width = "0%";
}

function setRunning(running) {
  state.running = running;
  $("run-btn").disabled = running;
  $("cancel-btn").disabled = !running;
  $("topic").disabled = running;
  for (const b of document.querySelectorAll(".agent-btn")) b.disabled = running;
}

function params() {
  return {
    topic: $("topic").value.trim(),
    format: $("format").value,
    schedule_hours: parseInt($("schedule").value, 10) || 0,
    upload: $("upload").checked,
  };
}

async function runPipeline() {
  try {
    const r = await window.jarvis.rpc("run_pipeline", params());
    log(`Pipeline result: ${r.result.status || "ok"}`, "success");
  } catch (e) {
    log(`Pipeline error: ${e.message}`, "error");
  }
}

async function runAgent(name) {
  try {
    const p = params();
    p.agent = name;
    await window.jarvis.rpc("run_agent", p);
    refreshOutputs();
  } catch (e) {
    log(`Agent error: ${e.message}`, "error");
  }
}

async function refreshOutputs() {
  try {
    const r = await window.jarvis.rpc("list_outputs");
    renderOutputs(r.result || []);
  } catch (e) {
    log(`Could not list outputs: ${e.message}`, "warn");
  }
}

function renderOutputs(outputs) {
  const box = $("outputs");
  box.innerHTML = "";
  if (!outputs.length) {
    box.appendChild(el("div", "empty", "No videos yet — run the pipeline to generate one."));
    return;
  }
  for (const o of outputs) {
    const item = el("div", "output-item");
    const meta = el("div", "meta");
    meta.append(
      el("div", "title", o.title || o.run_id),
      el("div", "sub", `${o.created_at || ""} · ${o.has_video ? "video ✓" : "no video"}${o.youtube_id ? ` · uploaded ✓` : ""}`)
    );
    item.appendChild(meta);
    if (o.has_video) {
      const open = el("a", "link", "open");
      open.href = "#";
      open.onclick = () => window.jarvis.revealPath(o.path);
      item.appendChild(open);
    }
    if (o.youtube_id) {
      const yt = el("a", "link", "youtu.be");
      yt.href = "#";
      yt.onclick = () => window.jarvis.openPath("https://youtu.be/" + o.youtube_id);
      item.appendChild(yt);
    }
    box.appendChild(item);
  }
}

// ---- event stream --------------------------------------------------------
window.jarvis.onEvent(({ event, data }) => {
  switch (event) {
    case "backend_up":
      setPill(true, "Backend: connected");
      refreshOutputs();
      break;
    case "backend_down":
      setPill(false, "Backend: offline");
      setRunning(false);
      break;
    case "log":
      log(data.message, data.level);
      break;
    case "progress":
      setAgent(data.agent, "run", data.pct);
      break;
    case "agent_started":
      setAgent(data.agent, "run");
      break;
    case "agent_done":
      setAgent(data.agent, data.ok ? "done" : "err");
      break;
    case "pipeline_complete":
      setRunning(false);
      log(`✓ Video ready: ${data.title}`, "success");
      if (data.youtube_id) log(`✓ Published: https://youtu.be/${data.youtube_id}`, "success");
      refreshOutputs();
      break;
    case "pipeline_failed":
      setRunning(false);
      log(`Pipeline failed: ${data.error}`, "error");
      break;
    case "pipeline_cancelled":
      setRunning(false);
      log("Pipeline cancelled.", "warn");
      break;
    case "trend_selected":
      log(`Trend selected: ${data.title}`);
      break;
    case "video_uploaded":
      log(`Published: ${data.url}`, "success");
      toast(`Uploaded! ${data.url}`);
      break;
    case "auth_required":
      openAuthDialog(data.message);
      break;
    case "outputs_updated":
      refreshOutputs();
      break;
  }
});

function openAuthDialog(message) {
  $("auth-message").textContent = message + "\n\nJarvis can copy the file into config/ for you.";
  $("auth-dialog").showModal();
}

$("auth-btn").onclick = async () => {
  const r = await window.jarvis.chooseClientSecret();
  if (r.ok) {
    toast("Saved to config/client_secret.json");
    log("Saved client_secret.json. Run: python3 scripts/oauth_google.py (or just re-run the upload).", "warn");
    $("auth-dialog").close();
  }
};

$("run-btn").onclick = () => {
  log("Starting pipeline…", "warn");
  setRunning(true);
  runPipeline();
};
$("cancel-btn").onclick = () => window.jarvis.rpc("cancel", {});
$("clear-console").onclick = () => ($("console").innerHTML = "");
$("refresh-outputs").onclick = refreshOutputs;

// ---- init -----------------------------------------------------------------
buildAgents();
log("Jarvis renderer ready. Starting backend…");
