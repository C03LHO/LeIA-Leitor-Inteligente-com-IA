// Busca de texto dentro do livro aberto — varre as frases do leitor, realça e
// permite pular entre as ocorrências (Ctrl+F, Enter / Shift+Enter, Esc).
(function () {
  let matches = [];
  let current = -1;
  let query = "";
  let debounce = null;

  // Ignora acentos e maiúsculas → "José" acha "jose".
  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  const $ = (id) => document.getElementById(id);
  const bar = () => $("find-bar");
  const input = () => $("find-input");

  function clearMarks() {
    document.querySelectorAll(".sentence.find-hit, .sentence.find-current")
      .forEach((el) => el.classList.remove("find-hit", "find-current"));
  }

  function run() {
    clearMarks();
    matches = [];
    current = -1;
    const q = norm(query.trim());
    const r = window.LeIA.reader && window.LeIA.reader.state;
    if (q.length >= 2 && r && r.sentences.length) {
      r.sentences.forEach((s) => {
        if (norm(s.text).includes(q)) {
          s.el.classList.add("find-hit");
          matches.push(s);
        }
      });
    }
    if (matches.length) { current = 0; focusCurrent(); }
    updateCount();
  }

  function focusCurrent() {
    matches.forEach((s) => s.el.classList.remove("find-current"));
    const s = matches[current];
    if (!s) return;
    s.el.classList.add("find-current");
    s.el.scrollIntoView({ behavior: "smooth", block: "center" });
    updateCount();
  }

  function updateCount() {
    const el = $("find-count");
    if (!el) return;
    el.textContent = matches.length
      ? `${current + 1}/${matches.length}`
      : (query.trim().length >= 2 ? "0/0" : "");
  }

  function step(delta) {
    if (!matches.length) return;
    current = (current + delta + matches.length) % matches.length;
    focusCurrent();
  }

  function open() {
    const r = window.LeIA.reader && window.LeIA.reader.state;
    if (!r || !r.sentences.length) return;
    bar().classList.remove("hidden");
    input().focus();
    input().select();
    if (query.trim()) run();
  }

  function close() {
    bar().classList.add("hidden");
    clearMarks();
    matches = [];
    current = -1;
  }

  function toggle() {
    bar().classList.contains("hidden") ? open() : close();
  }

  function init() {
    input().addEventListener("input", () => {
      query = input().value;
      clearTimeout(debounce);
      debounce = setTimeout(run, 180);
    });
    input().addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : +1); }
      else if (e.key === "Escape") { e.preventDefault(); close(); }
    });
    $("find-next").addEventListener("click", () => step(+1));
    $("find-prev").addEventListener("click", () => step(-1));
    $("find-close").addEventListener("click", close);
    $("btn-find").addEventListener("click", toggle);

    const sc = window.LeIA.shortcuts;
    sc.on("Mod+f", open);
    sc.on("Mod+F", open);

    // Some quando o documento troca (ou fecha).
    window.addEventListener("leia:document-loaded", close);
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.find = { init, open, close };
})();
