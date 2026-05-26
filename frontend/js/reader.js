(function () {
  const SENT_SPLIT_RE = /(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ])/g;

  function splitSentences(text) {
    if (!text) return [];
    return text
      .split(SENT_SPLIT_RE)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function renderDocument(doc) {
    document.getElementById("doc-title").textContent = doc.metadata.filename;
    document.getElementById("btn-close-doc").classList.remove("d-none");
    document.getElementById("view-upload").classList.add("d-none");
    document.getElementById("view-reader").classList.remove("d-none");
    document.getElementById("player-bar").classList.remove("d-none");

    const toc = document.getElementById("toc");
    toc.innerHTML = "";
    const body = document.getElementById("reader-body");
    body.innerHTML = "";

    const sentenceList = [];
    let sentenceCounter = 0;

    doc.sections.forEach((sec) => {
      if (sec.title) {
        const h = document.createElement("h1");
        h.id = sec.id;
        h.textContent = sec.title;
        body.appendChild(h);
        const li = document.createElement("li");
        const a = document.createElement("a");
        a.href = "#" + sec.id;
        a.textContent = sec.title;
        li.appendChild(a);
        toc.appendChild(li);
      }
      sec.paragraphs.forEach((p) => {
        const para = document.createElement("p");
        para.dataset.paragraphId = p.id;
        splitSentences(p.text).forEach((sentText) => {
          const span = document.createElement("span");
          span.className = "sentence";
          span.dataset.sentenceIndex = String(sentenceCounter);
          span.textContent = sentText + " ";
          para.appendChild(span);
          sentenceList.push({ index: sentenceCounter, text: sentText, el: span });
          sentenceCounter++;
        });
        body.appendChild(para);
      });
    });

    renderCleaningStats(doc.metadata);
    window.LeIA.player.setSentences(sentenceList);
  }

  function renderCleaningStats(meta) {
    const wrap = document.getElementById("cleaning-stats");
    const reasons = meta.removal_reasons || {};
    const total = meta.removed_chars || 0;
    const kept = meta.extracted_chars || 0;
    const sum = total + kept;
    const pct = sum > 0 ? ((total / sum) * 100).toFixed(1) : "0.0";
    const rows = Object.entries(reasons)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<li><span class="text-secondary">${k}:</span> ${v}</li>`)
      .join("");
    wrap.innerHTML = `
      <div>Páginas: <strong>${meta.pages}</strong></div>
      <div>Texto mantido: <strong>${kept.toLocaleString("pt-BR")}</strong> chars</div>
      <div>Removido: <strong>${total.toLocaleString("pt-BR")}</strong> chars (${pct}%)</div>
      <ul class="mt-2 mb-0 ps-3">${rows}</ul>
    `;
  }

  function reset() {
    document.getElementById("doc-title").textContent = "";
    document.getElementById("btn-close-doc").classList.add("d-none");
    document.getElementById("view-upload").classList.remove("d-none");
    document.getElementById("view-reader").classList.add("d-none");
    document.getElementById("player-bar").classList.add("d-none");
    document.getElementById("upload-progress").classList.add("d-none");
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.reader = { renderDocument, reset, splitSentences };
})();
