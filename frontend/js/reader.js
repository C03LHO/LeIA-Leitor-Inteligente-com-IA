(function () {
  const SENT_SPLIT_RE = /(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ])/g;

  function splitSentences(text) {
    if (!text) return [];
    return text.split(SENT_SPLIT_RE).map((s) => s.trim()).filter(Boolean);
  }

  /**
   * Sentence model:
   *   { id, text, sectionIndex, paragraphIndex, sentenceIndexInParagraph, el }
   */
  const state = {
    sections: [],
    sentences: [],
    sentenceById: new Map(),
    activeSentenceId: null,
  };

  function renderDocument(doc) {
    document.getElementById("doc-title").textContent =
      `${doc.metadata.filename}  ·  ${doc.metadata.pages} págs`;
    document.getElementById("doc-title").classList.remove("hidden");
    document.getElementById("btn-close-doc").classList.remove("hidden");
    document.getElementById("view-welcome").classList.add("hidden");
    document.getElementById("view-processing").classList.add("hidden");
    document.getElementById("main-body").classList.remove("hidden");
    document.getElementById("player-bar").classList.remove("hidden");
    document.getElementById("app").classList.remove("no-doc");

    state.sections = [];
    state.sentences = [];
    state.sentenceById.clear();
    state.activeSentenceId = null;

    const toc = document.getElementById("toc");
    toc.innerHTML = "";
    const body = document.getElementById("reader");
    body.innerHTML = "";

    doc.sections.forEach((sec, sIdx) => {
      const sectionStartIdx = state.sentences.length;

      if (sec.title) {
        const h = document.createElement("h1");
        h.id = `sec-${sIdx}`;
        h.textContent = sec.title;
        body.appendChild(h);

        const li = document.createElement("li");
        li.className = "toc-item";
        li.dataset.sectionIndex = String(sIdx);
        li.textContent = sec.title;
        li.addEventListener("click", () => {
          h.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        toc.appendChild(li);
      }

      sec.paragraphs.forEach((p, pIdx) => {
        const para = document.createElement("p");
        // Usa as frases já divididas pelo backend (ids estáveis que casam com o
        // cache de áudio pré-gerado); cai no split do cliente só se faltarem.
        const sents =
          p.sentences && p.sentences.length
            ? p.sentences
            : splitSentences(p.text).map((t, i) => ({ id: `s${sIdx}_p${pIdx}_${i}`, text: t }));
        sents.forEach((sent, siIdx) => {
          const sid = sent.id;
          const span = document.createElement("span");
          span.className = "sentence";
          span.dataset.sid = sid;
          span.textContent = sent.text + " ";
          span.addEventListener("click", () => {
            const ev = new CustomEvent("leia:sentence-click", { detail: { sid } });
            window.dispatchEvent(ev);
          });
          para.appendChild(span);
          const s = {
            id: sid, text: sent.text, el: span,
            sectionIndex: sIdx, paragraphIndex: pIdx, indexInParagraph: siIdx,
            globalIndex: state.sentences.length,
          };
          state.sentences.push(s);
          state.sentenceById.set(sid, s);
        });
        body.appendChild(para);
      });

      state.sections.push({
        index: sIdx,
        title: sec.title || "",
        sentenceStart: sectionStartIdx,
        sentenceEnd: state.sentences.length,
      });
    });

    if (state.sections.length === 0 || state.sentences.length === 0) {
      body.innerHTML = `<p style="color: var(--fg-tertiary);">Nenhum texto extraído. Este PDF pode estar protegido ou ser uma imagem escaneada.</p>`;
    }

    window.dispatchEvent(new CustomEvent("leia:document-loaded"));
  }

  function highlight(sid) {
    if (state.activeSentenceId) {
      const prev = state.sentenceById.get(state.activeSentenceId);
      if (prev) prev.el.classList.remove("active");
    }
    state.activeSentenceId = sid;
    if (!sid) return;
    const s = state.sentenceById.get(sid);
    if (!s) return;
    s.el.classList.add("active");
    s.el.scrollIntoView({ behavior: "smooth", block: "center" });

    const sec = state.sections[s.sectionIndex];
    document.querySelectorAll(".toc-item").forEach((li) => li.classList.remove("active"));
    const activeToc = document.querySelector(`.toc-item[data-section-index="${s.sectionIndex}"]`);
    if (activeToc) activeToc.classList.add("active");
    const label = document.getElementById("section-label");
    if (label && sec) {
      label.textContent = sec.title
        ? `${sec.title}  ·  seção ${s.sectionIndex + 1} de ${state.sections.length}`
        : `Seção ${s.sectionIndex + 1} de ${state.sections.length}`;
    }
    document.getElementById("now-reading").textContent = s.text;
  }

  function setReaderFontSize(px) {
    document.documentElement.style.setProperty("--reader-fontsize", px + "px");
    try { localStorage.setItem("leia.reader.size", String(px)); } catch {}
  }

  function reset() {
    document.getElementById("doc-title").textContent = "";
    document.getElementById("doc-title").classList.add("hidden");
    document.getElementById("btn-close-doc").classList.add("hidden");
    document.getElementById("view-welcome").classList.remove("hidden");
    document.getElementById("view-processing").classList.add("hidden");
    document.getElementById("main-body").classList.add("hidden");
    document.getElementById("player-bar").classList.add("hidden");
    document.getElementById("app").classList.add("no-doc");
    state.sections = [];
    state.sentences = [];
    state.sentenceById.clear();
    state.activeSentenceId = null;
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.reader = {
    renderDocument,
    highlight,
    reset,
    setReaderFontSize,
    splitSentences,
    state,
  };
})();
