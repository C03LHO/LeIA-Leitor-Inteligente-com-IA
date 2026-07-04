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

  function showProcessing(filename, label) {
    document.getElementById("processing-title").textContent =
      (label ? label + " · " : "") + `Extraindo conteúdo de ${filename}`;
    document.getElementById("view-welcome").classList.add("hidden");
    document.getElementById("view-processing").classList.remove("hidden");
    document.getElementById("main-body").classList.add("hidden");
    resetSteps();
  }

  function isBook(file) {
    const n = ((file && file.name) || "").toLowerCase();
    return n.endsWith(".pdf") || n.endsWith(".epub") || n.endsWith(".docx") || n.endsWith(".txt");
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

    // Importa UM arquivo (extrai o texto → estante). NÃO gera áudio, a não ser
    // que o toggle "preparar narração" esteja marcado. Lança em caso de erro.
    async function handle(file, idx, total) {
      const label = total > 1 ? `Importando ${idx} de ${total}` : "";
      showProcessing(file.name, label);
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
      setProgress(30, "Lendo arquivo…");

      await window.LeIA.api.pollJob(up.job_id, (s) => {
        const p = s.progress || 0;
        if (p < 0.4) {
          setStep("extract", "current");
          setProgress(30 + p * 30, "Lendo arquivo…");
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
      return up.job_id;
    }

    // Importa VÁRIOS arquivos de uma vez (ex.: soltar 100 PDFs). Cada um vira
    // texto na estante; nenhum gera áudio sozinho — você decide depois (🎧).
    async function handleMany(fileList) {
      const files = [...(fileList || [])].filter(isBook);
      if (!files.length) {
        window.LeIA.toast("Envie arquivos .pdf, .epub, .docx ou .txt", "warning");
        return;
      }
      let ok = 0;
      for (let i = 0; i < files.length; i++) {
        try { await handle(files[i], i + 1, files.length); ok++; }
        catch (err) { console.error(err); }
      }
      window.LeIA.goHome();            // volta para a estante
      if (window.LeIA.refreshQueue) window.LeIA.refreshQueue();
      const fail = files.length - ok;
      if (!ok) window.LeIA.toast("Falha ao importar os arquivos.", "danger");
      else window.LeIA.toast(
        (ok === 1 ? "📚 Livro adicionado à estante." : `📚 ${ok} livros adicionados à estante.`) +
        (fail ? ` (${fail} falharam)` : ""),
        fail ? "warning" : "success"
      );
    }

    dz.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      handleMany(fileInput.files);
      fileInput.value = "";
    });
    ["dragenter", "dragover"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.add("dragover"); })
    );
    ["dragleave", "drop"].forEach((evt) =>
      dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.remove("dragover"); })
    );
    dz.addEventListener("drop", (e) => {
      if (e.dataTransfer && e.dataTransfer.files.length) handleMany(e.dataTransfer.files);
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.initUpload = init;
})();
