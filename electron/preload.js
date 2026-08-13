const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvis", {
  rpc: (method, params) => ipcRenderer.invoke("rpc", method, params || {}),
  onEvent: (callback) => {
    ipcRenderer.on("backend:event", (_evt, payload) => callback(payload));
  },
  openPath: (p) => ipcRenderer.invoke("open-path", p),
  revealPath: (p) => ipcRenderer.invoke("reveal-path", p),
  chooseClientSecret: () => ipcRenderer.invoke("choose-client-secret"),
  version: "0.1.0",
});
