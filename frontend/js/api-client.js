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

  async function uploadPDF(file, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", API + "/api/pdf/upload");
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && onProgress) {
          onProgress(ev.loaded / ev.total);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
        }
      };
      xhr.onerror = () => reject(new Error("Erro de rede"));
      xhr.send(fd);
    });
  }

  async function pollJob(jobId, onProgress, intervalMs = 600) {
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

  window.LeIA = window.LeIA || {};
  window.LeIA.api = { getJSON, postJSON, uploadPDF, pollJob, openTTSSocket };
})();
