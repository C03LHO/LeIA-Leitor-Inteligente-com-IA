(function () {
  const KEY = "leia.stats"; // { days: {YYYY-MM-DD: seconds}, goalMin }

  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch {} }
  function keyOf(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function today() { return keyOf(new Date()); }

  // Acumula tempo de leitura (escuta), gravando em lotes para não martelar o storage.
  let pending = 0;
  function addSeconds(sec) {
    pending += sec;
    if (pending < 5) return;
    const s = load();
    s.days = s.days || {};
    s.days[today()] = (s.days[today()] || 0) + pending;
    pending = 0;
    save(s);
  }

  function getGoalMin() { return load().goalMin || 15; }
  function setGoalMin(m) { const s = load(); s.goalMin = m; save(s); }

  function has(offset) {
    const d = new Date(); d.setDate(d.getDate() - offset);
    return ((load().days || {})[keyOf(d)] || 0) > 0;
  }
  function streak() {
    // Conta dias consecutivos com leitura terminando hoje (ou ontem, se hoje ainda não leu).
    const start = has(0) ? 0 : (has(1) ? 1 : -1);
    if (start < 0) return 0;
    let n = 0;
    for (let i = start; ; i++) { if (has(i)) n++; else break; }
    return n;
  }

  function summary() {
    const days = load().days || {};
    const total = Object.values(days).reduce((a, b) => a + b, 0);
    const daysActive = Object.values(days).filter((v) => v > 0).length;
    const labels = ["D", "S", "T", "Q", "Q", "S", "S"];
    const last7 = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      last7.push({ sec: days[keyOf(d)] || 0, label: labels[d.getDay()] });
    }
    return { total, daysActive, todaySec: days[today()] || 0, streak: streak(), goalMin: getGoalMin(), last7 };
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.stats = { addSeconds, getGoalMin, setGoalMin, summary };
})();
