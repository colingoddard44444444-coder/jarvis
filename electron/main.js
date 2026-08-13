const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const ROOT = path.join(__dirname, "..");
const PYTHON_SERVER = path.join(ROOT, "python", "server.py");

function findPython() {
  const candidates = [
    path.join(ROOT, ".venv", "bin", "python"),
    path.join(ROOT, "python", ".venv", "bin", "python"),
    "python3",
  ];
  for (const c of candidates) {
    if (c.includes(path.sep) && !fs.existsSync(c)) continue;
    return c;
  }
  return "python3";
}

let mainWindow = null;
let backend = null;
let backendReady = false;
let pending = new Map();
let seq = 0;

function send(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

function sendEvent(event, data) {
  send("backend:event", { event, data });
}

function startBackend() {
  const python = findPython();
  backend = spawn(python, [PYTHON_SERVER], {
    cwd: ROOT,
    env: process.env,
  });

  backend.stdout.on("data", (chunk) => {
    for (const line of chunk.toString().split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let msg;
      try {
        msg = JSON.parse(trimmed);
      } catch {
        continue;
      }
      if (msg.id !== undefined && msg.id !== null) {
        const p = pending.get(msg.id);
        if (p) {
          pending.delete(msg.id);
          if (msg.ok) p.resolve(msg.result);
          else p.reject(new Error(msg.error || "backend error"));
        }
      } else if (msg.event) {
        sendEvent(msg.event, msg.data || {});
      }
    }
  });

  backend.stderr.on("data", (chunk) => {
    const text = chunk.toString().trim();
    if (text) console.error("[backend]", text);
  });

  backend.on("exit", (code) => {
    backendReady = false;
    console.error("[backend] exited:", code);
    sendEvent("backend_down", { code });
    // Auto-restart so the UI stays usable.
    setTimeout(startBackend, 1500);
  });

  backendReady = true;
  setTimeout(() => sendEvent("backend_up", {}), 200);
}

function rpc(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    if (!backend || backend.killed) {
      reject(new Error("Backend not running"));
      return;
    }
    backend.stdin.write(JSON.stringify({ id, method, params }) + "\n");
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    backgroundColor: "#0b0e1a",
    title: "Jarvis",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(ROOT, "renderer", "index.html"));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();
  startBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (backend) backend.kill();
});

// ---- IPC: renderer -> backend RPC ----------------------------------------
ipcMain.handle("rpc", (_evt, method, params) => rpc(method, params || {}));

ipcMain.handle("open-path", async (_evt, p) => {
  if (!p || !fs.existsSync(p)) return { ok: false };
  await shell.openPath(p);
  return { ok: true };
});

ipcMain.handle("reveal-path", async (_evt, p) => {
  if (!p || !fs.existsSync(p)) return { ok: false };
  shell.showItemInFolder(p);
  return { ok: true };
});

ipcMain.handle("choose-client-secret", async () => {
  const res = await dialog.showOpenDialog(mainWindow, {
    title: "Select Google OAuth client_secret.json",
    filters: [{ name: "JSON", extensions: ["json"] }],
    properties: ["openFile"],
  });
  if (res.canceled || !res.filePaths.length) return { ok: false };
  const dest = path.join(ROOT, "config", "client_secret.json");
  fs.copyFileSync(res.filePaths[0], dest);
  return { ok: true, path: dest };
});
