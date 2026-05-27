(function () {
  const API = window.location.origin;

  async function getJSON(path) {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async function postJSON(path, body) {
    const r = await fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async function del(path) {
    const r = await fetch(API + path, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  async function uploadFile(path, file, onProgress, extraFields = {}) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      for (const [k, v] of Object.entries(extraFields)) fd.append(k, v);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", API + path);
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) onProgress(ev.loaded / ev.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)); }
          catch { resolve(xhr.responseText); }
        } else {
          reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
        }
      };
      xhr.onerror = () => reject(new Error("Erro de rede"));
      xhr.send(fd);
    });
  }

  async function pollJob(jobId, onProgress, intervalMs = 500) {
    while (true) {
      const status = await getJSON(`/api/pdf/${jobId}/status`);
      if (onProgress) onProgress(status);
      if (status.status === "done") return getJSON(`/api/pdf/${jobId}/result`);
      if (status.status === "error") throw new Error(status.error || "Falha no processamento");
      await new Promise((r) => setTimeout(r, intervalMs));
    }
  }

  function openTTSSocket() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return new WebSocket(`${proto}//${window.location.host}/ws/tts`);
  }

  function previewVoiceURL(voiceId) {
    return `${API}/api/voices/${encodeURIComponent(voiceId)}/preview`;
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.api = { getJSON, postJSON, del, uploadFile, pollJob, openTTSSocket, previewVoiceURL };
})();
