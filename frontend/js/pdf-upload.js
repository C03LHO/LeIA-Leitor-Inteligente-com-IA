(function () {
  const STEPS = ["upload", "extract", "clean", "reflow", "structure"];
  const CLEANING_KEYS = [
    "remove_urls",
    "remove_footnotes",
    "remove_figure_captions",
    "remove_headers_footers",
    "remove_copyright",
  ];

  // Lê os toggles da aba "Limpeza" (gravados por settings.js em leia.cleaning.<key>)
  // e monta o objeto enviado ao backend. Só inclui chaves que o usuário tocou.
  function readCleaningConfig() {
    const cfg = {};
    for (const k of CLEANING_KEYS) {
      const v = localStorage.getItem(`leia.cleaning.${k}`);
      if (v !== null) cfg[k] = v === "1";
    }
    return cfg;
  }

  function setStep(name, status) {
    const li = document.querySelector(`.step[data-step="${name}"]`);
    if (!li) return;
    li.classList.remove("pending", "current", "done");
    li.classList.add(status);
    const mark = li.querySelector(".mark");
    if (mark) mark.textContent = status === "done" ? "✓" : status === "current" ? "→" : "○";
  }

  function setProgress(pct, sub) {
    document.getElementById("proc-fill").style.width = `${Math.max(0, Math.min(100, pct))}%`;
    if (sub) document.getElementById("processing-sub").textContent = sub;
  }

  function resetSteps() {
    STEPS.forEach((s) => setStep(s, "pending"));
    setProgress(0, "Iniciando…");
  }

  function showProcessing(filename) {
    document.getElementById("processing-title").textContent =
      `Extraindo conteúdo de ${filename}`;
    document.getElementById("view-welcome").classList.add("hidden");
    document.getElementById("view-processing").classList.remove("hidden");
    document.getElementById("main-body").classList.add("hidden");
    resetSteps();
  }

  function init() {
    const dz = document.getElementById("dropzone");
    const fileInput = document.getElementById("file-input");
    if (!dz) return;

    const prepEl = document.getElementById("prepare-on-add");
    if (prepEl) {
      prepEl.checked = localStorage.getItem("leia.prepareOnAdd") === "1";
      prepEl.addEventListener("change", () => {
        try { localStorage.setItem("leia.prepareOnAdd", prepEl.checked ? "1" : "0"); } catch {}
      });
    }

    async function handle(file) {
      const name = ((file && file.name) || "").toLowerCase();
      if (!file || !(name.endsWith(".pdf") || name.endsWith(".epub"))) {
        window.LeIA.toast("Envie um arquivo .pdf ou .epub", "warning");
        return;
      }
      try {
        showProcessing(file.name);
        setStep("upload", "current");
        setProgress(5, "Enviando arquivo…");
        const cleaning = readCleaningConfig();
        const prepareEl = document.getElementById("prepare-on-add");
        const extra = { prepare: prepareEl && prepareEl.checked ? "true" : "false" };
        if (Object.keys(cleaning).length) extra.cleaning = JSON.stringify(cleaning);
        const up = await window.LeIA.api.uploadFile(
          "/api/pdf/upload",
          file,
          (r) => setProgress(5 + r * 25, `Enviando… ${Math.round(r * 100)}%`),
          extra
        );
        setStep("upload", "done");
        setStep("extract", "current");
        setProgress(30, "Lendo PDF…");

        const result = await window.LeIA.api.pollJob(up.job_id, (s) => {
          const p = s.progress || 0;
          if (p < 0.4) {
            setStep("extract", "current");
            setProgress(30 + p * 30, "Lendo PDF…");
          } else if (p < 0.7) {
            setStep("extract", "done");
            setStep("clean", "current");
            setProgress(60 + (p - 0.4) * 50, "Detectando cabeçalhos e rodapés…");
          } else if (p < 0.9) {
            setStep("clean", "done");
            setStep("reflow", "current");
            setProgress(75 + (p - 0.7) * 50, "Reconstruindo parágrafos…");
          } else {
            setStep("reflow", "done");
            setStep("structure", "current");
            setProgress(90 + (p - 0.9) * 80, "Estruturando seções…");
          }
        });

        STEPS.forEach((s) => setStep(s, "done"));
        setProgress(100, "Pronto");

        // Não abre o leitor: o livro vai para a estante (com loading do áudio).
        window.LeIA.onBookAdded(up.job_id);
      } catch (err) {
        console.error(err);
        window.LeIA.toast("Falha: " + err.message, "danger");
        document.getElementById("view-processing").classList.add("hidden");
        document.getElementById("view-welcome").classList.remove("hidden");
      }
    }

    dz.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) handle(fileInput.files[0]);
      fileInput.value = "";
    });
    ["dragenter", "dragover"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
    );
    dz.addEventListener("drop", (e) => {
      const file = e.dataTransfer && e.dataTransfer.files[0];
      if (file) handle(file);
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.initUpload = init;
})();
