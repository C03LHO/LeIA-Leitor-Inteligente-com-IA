(function () {
  function init() {
    const dz = document.getElementById("dropzone");
    const fileInput = document.getElementById("file-input");
    const pickBtn = document.getElementById("btn-pick");
    const progressWrap = document.getElementById("upload-progress");
    const progressBar = document.getElementById("upload-bar");
    const statusEl = document.getElementById("upload-status");

    if (!dz) return;

    function setProgress(ratio, message) {
      progressWrap.classList.remove("d-none");
      const pct = Math.round(ratio * 100);
      progressBar.style.width = pct + "%";
      if (message) statusEl.textContent = message;
    }

    async function handle(file) {
      if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
        window.LeIA.toast("Envie um arquivo .pdf", "danger");
        return;
      }
      try {
        setProgress(0, "Enviando…");
        const up = await window.LeIA.api.uploadPDF(file, (r) =>
          setProgress(r * 0.4, `Enviando… ${(r * 100).toFixed(0)}%`)
        );
        setProgress(0.5, "Extraindo texto…");
        const result = await window.LeIA.api.pollJob(up.job_id, (s) => {
          const p = 0.5 + (s.progress || 0) * 0.5;
          setProgress(p, `Extraindo… ${(s.progress * 100).toFixed(0)}%`);
        });
        setProgress(1, "Pronto");
        window.LeIA.onDocumentLoaded(result);
      } catch (err) {
        console.error(err);
        window.LeIA.toast("Falha: " + err.message, "danger");
        setProgress(0, "");
        progressWrap.classList.add("d-none");
      }
    }

    pickBtn.addEventListener("click", () => fileInput.click());
    dz.addEventListener("click", (e) => {
      if (e.target === pickBtn) return;
      fileInput.click();
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) handle(fileInput.files[0]);
    });
    ["dragenter", "dragover"].forEach((evt) =>
      dz.addEventListener(evt, (e) => {
        e.preventDefault();
        dz.classList.add("dragover");
      })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dz.addEventListener(evt, (e) => {
        e.preventDefault();
        dz.classList.remove("dragover");
      })
    );
    dz.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files[0];
      if (file) handle(file);
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.initUpload = init;
})();
