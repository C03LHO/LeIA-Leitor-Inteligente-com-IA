// Audiolivro para o celular: exporta o livro (M4B/MP3) e envia pro iPhone via
// QR/rede local. Reaproveita o áudio já em cache; gera o que faltar.
(function () {
  const $ = (id) => document.getElementById(id);
  let pollTimer = null;
  let mode = "download"; // "download" | "share"

  function api() { return window.LeIA.api; }
  function jobId() { return window.LeIA.currentJobId; }

  function showStep(which) {
    ["format", "progress", "share"].forEach((s) =>
      $(`ab-step-${s}`).classList.toggle("hidden", s !== which));
  }

  function open() {
    const jid = jobId();
    if (!jid) { window.LeIA.toast("Abra um livro primeiro", "warning"); return; }
    const title = document.getElementById("doc-title").textContent.split("·")[0].trim();
    $("ab-book").textContent = title || "Livro atual";
    showStep("format");
    $("audiobook-backdrop").classList.add("open");
  }

  function close() {
    $("audiobook-backdrop").classList.remove("open");
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function fmt() {
    const el = document.querySelector('input[name="ab-fmt"]:checked');
    return el ? el.value : "m4b";
  }

  async function startExport(nextMode) {
    mode = nextMode;
    const jid = jobId();
    showStep("progress");
    $("ab-prog-title").textContent = mode === "share"
      ? "Gerando audiolivro para enviar…" : "Gerando audiolivro…";
    $("ab-prog-fill").style.width = "0%";
    $("ab-prog-line").textContent = "Preparando…";
    try {
      await api().postJSON(`/api/pdf/${jid}/audiobook`, { fmt: fmt() });
    } catch (e) {
      window.LeIA.toast("Falha ao iniciar: " + e.message, "danger");
      showStep("format");
      return;
    }
    pollExport(jid);
  }

  async function pollExport(jid) {
    let s;
    try { s = await api().getJSON(`/api/pdf/${jid}/audiobook/status`); }
    catch { pollTimer = setTimeout(() => pollExport(jid), 1500); return; }

    if (s.status === "exporting") {
      const total = s.total || 0, done = s.done || 0;
      const pct = total ? Math.round((done / total) * 100) : 5;
      $("ab-prog-fill").style.width = `${Math.max(5, pct)}%`;
      $("ab-prog-line").textContent = total
        ? `${done} de ${total} trechos · ${pct}%`
        : "Carregando a voz…";
      pollTimer = setTimeout(() => pollExport(jid), 1200);
    } else if (s.status === "done") {
      $("ab-prog-fill").style.width = "100%";
      if (mode === "download") finishDownload(jid);
      else finishShare(jid);
    } else if (s.status === "error") {
      window.LeIA.toast("Erro ao gerar: " + (s.error || "desconhecido"), "danger");
      showStep("format");
    } else {
      pollTimer = setTimeout(() => pollExport(jid), 1200);
    }
  }

  function finishDownload(jid) {
    window.LeIA.toast("Audiolivro pronto! Baixando…", "success");
    const a = document.createElement("a");
    a.href = `/api/pdf/${jid}/audiobook/download`;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
    close();
  }

  async function finishShare(jid) {
    try {
      const info = await api().postJSON(`/api/pdf/${jid}/share`, { fmt: fmt() });
      $("ab-qr").src = info.qr || "";
      $("ab-share-url").textContent = info.url;
      $("ab-share-url").href = info.url;
      showStep("share");
    } catch (e) {
      window.LeIA.toast("Falha ao compartilhar: " + e.message, "danger");
      showStep("format");
    }
  }

  function init() {
    const btn = $("btn-audiobook");
    if (btn) btn.addEventListener("click", open);
    $("audiobook-close").addEventListener("click", close);
    $("audiobook-backdrop").addEventListener("click", (e) => {
      if (e.target === $("audiobook-backdrop")) close();
    });
    $("ab-download-btn").addEventListener("click", () => startExport("download"));
    $("ab-share-btn").addEventListener("click", () => startExport("share"));
    // realce visual do formato escolhido
    document.querySelectorAll('input[name="ab-fmt"]').forEach((r) => {
      r.addEventListener("change", () => {
        document.querySelectorAll(".ab-fmt").forEach((l) =>
          l.classList.toggle("active", l.querySelector("input").checked));
      });
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.audiobook = { init, open, close };
})();
