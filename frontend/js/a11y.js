// Acessibilidade: torna os elementos clicáveis que são <div>/<span> (abas,
// chips, cartões de livro, opções) focáveis por Tab e ativáveis por Enter/Espaço.
// Os anéis de foco já existem no CSS (:focus-visible).
(function () {
  const SEL = [
    ".modal-tab", ".chip", ".genre-chip", ".src-chip", ".ex-src",
    ".book", ".bk-card", ".collection-opt", ".voice-item", ".toc-item",
    ".popover-item", ".size-preset", ".seg-btn", ".dropzone",
  ].join(",");

  function enhance(el) {
    if (!el || el.dataset.a11y) return;
    el.dataset.a11y = "1";
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    if (!el.hasAttribute("role")) el.setAttribute("role", "button");
  }

  function scan(root) {
    (root || document).querySelectorAll(SEL).forEach(enhance);
  }

  function init() {
    scan(document);
    // Elementos criados dinamicamente (estante, chips, resultados) também.
    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;
          if (node.matches && node.matches(SEL)) enhance(node);
          if (node.querySelectorAll) scan(node);
        }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });

    // Enter/Espaço no elemento focado → clique (sem atrapalhar inputs).
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const el = document.activeElement;
      if (!el || !el.matches || !el.matches(SEL)) return;
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || el.isContentEditable) return;
      e.preventDefault();
      el.click();
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.a11y = { init, scan };
})();
