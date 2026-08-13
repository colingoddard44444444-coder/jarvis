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
    style: $("style").value,
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
      refreshVoice();
      refreshAutopilot();
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
    case "voice_event":
      handleVoiceEvent(data);
      break;
    case "autopilot_event":
      handleAutopilotEvent(data);
      break;
  }
});

// ---- voice control --------------------------------------------------------
let voiceListening = false;

function setTranscript(text, cls) {
  const t = $("transcript");
  t.textContent = text;
  t.style.color = cls ? getComputedStyle(document.documentElement).getPropertyValue(cls).trim() : "";
}

function handleVoiceEvent(data) {
  const mic = $("mic-btn");
  switch (data.type) {
    case "listening":
      voiceListening = data.on === true;
      mic.classList.toggle("recording", voiceListening);
      mic.textContent = voiceListening ? "LISTENING…" : "HOLD TO TALK";
      break;
    case "heard":
      setTranscript(`You said: "${data.text}"`);
      break;
    case "saying":
      setTranscript(`Jarvis: "${data.text}"`);
      break;
    case "action":
      log(`Voice command → ${data.action}${data.params && data.params.topic ? `: ${data.params.topic}` : ""}`, "warn");
      break;
    case "wake":
      log(data.on ? "Wake word armed — say \"" + (window.jarvis.wakeWord || "jarvis") + "\"" : "Wake word off.", "warn");
      break;
    case "error":
      log(`Voice: ${data.message}`, "error");
      setTranscript(`Voice error: ${data.message}`);
      break;
    case "no_player":
      setTranscript(`Jarvis: "${data.text}" (no audio player found)`);
      break;
    case "reply":
      setTranscript(`Jarvis: "${data.text}"`);
      break;
  }
}

async function refreshVoice() {
  try {
    const r = await window.jarvis.rpc("voice_status");
    const s = r.result || {};
    const pill = $("voice-pill");
    if (!s.available) {
      pill.className = "pill bad";
      pill.textContent = "mic: n/a";
    } else {
      pill.className = s.wake_on ? "pill on" : "pill ok";
      pill.textContent = s.wake_on ? "voice: wake on" : "voice: ready";
    }
    window.jarvis.wakeWord = s.wake_word || "jarvis";
  } catch (e) {
    log(`Voice status: ${e.message}`, "warn");
  }
}

// ---- autopilot ------------------------------------------------------------
async function refreshAutopilot() {
  try {
    const r = await window.jarvis.rpc("autopilot_status");
    renderAutopilot(r.result || {});
  } catch (e) {
    log(`Autopilot status: ${e.message}`, "warn");
  }
}

function renderAutopilot(s) {
  const pill = $("ap-pill");
  pill.className = `pill ${s.enabled ? "on" : ""}`;
  pill.textContent = s.enabled ? "autopilot: on" : "autopilot: off";
  $("ap-toggle").checked = !!s.enabled;
  if (s.interval_hours) $("ap-interval").value = s.interval_hours;
  const st = [];
  if (s.enabled) {
    st.push(`next run: ${s.next_run_at || "soon"}`);
    st.push(`runs today: ${s.runs_today || 0}/${s.max_per_day}`);
    if (s.upload) st.push("auto-upload: ON");
  } else {
    st.push("Autopilot off.");
  }
  if (s.last_run_at) st.push(`last run: ${s.last_run_at} (${s.last_result || "—"})`);
  $("ap-status").textContent = st.join("  ·  ");
}

function handleAutopilotEvent(data) {
  switch (data.type) {
    case "started":
      log("Autopilot engaged.", "success");
      refreshAutopilot();
      break;
    case "stopped":
      log("Autopilot disengaged.", "warn");
      refreshAutopilot();
      break;
    case "run_started":
      log(`Autopilot: starting production ${data.params.topic ? `on "${data.params.topic}"` : "(auto-trend)"}`, "warn");
      setRunning(true);
      break;
    case "run_done":
      log("Autopilot: production complete.", "success");
      refreshOutputs();
      refreshAutopilot();
      break;
    case "run_error":
      log(`Autopilot: run failed — ${data.error}`, "error");
      refreshAutopilot();
      break;
  }
}

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

// voice buttons
const micBtn = $("mic-btn");
micBtn.addEventListener("mousedown", () => window.jarvis.rpc("voice_listen", { on: true }));
micBtn.addEventListener("mouseup", () => window.jarvis.rpc("voice_listen", { on: false }));
micBtn.addEventListener("mouseleave", () => {
  if (voiceListening) window.jarvis.rpc("voice_listen", { on: false });
});
$("wake-toggle").onchange = (e) => {
  window.jarvis.rpc("voice_wake", { on: e.target.checked }).then(refreshVoice);
};

// autopilot buttons
$("ap-toggle").onchange = (e) => {
  window.jarvis.rpc(e.target.checked ? "autopilot_start" : "autopilot_stop", {}).then(refreshAutopilot);
};
$("ap-interval").onchange = (e) => {
  const hours = Math.max(1, parseInt(e.target.value, 10) || 6);
  window.jarvis.rpc("save_config", { updates: { autopilot: { interval_hours: hours } } })
    .then(() => { e.target.value = hours; log(`Autopilot interval set to ${hours}h.`, "warn"); refreshAutopilot(); })
    .catch((err) => log(`Could not save interval: ${err.message}`, "error"));
};
$("ap-now-btn").onclick = () => {
  log("Starting production now…", "warn");
  setRunning(true);
  runPipeline();
};

// ---- init -----------------------------------------------------------------
buildAgents();
log("Jarvis renderer ready. Starting backend…");
