// Counts this device once per day for the owner's visitor totals. No cookie or
// identifier: only the day it was last counted. See docs/OWNER_INTAKE.md.
(() => {
  const KEY = "bhakti-visit";
  const RETRY_AFTER = 10 * 60 * 1000;
  if (location.hostname !== "bhakti.eeshan.xyz" || navigator.webdriver) return;
  let sending = false;

  const receipt = () => {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    return saved && (saved.day === null || /^\d{4}-\d{2}-\d{2}$/.test(saved.day)) && Number.isFinite(saved.until) ? saved : null;
  };
  const count = async () => {
    if (sending || document.visibilityState !== "visible") return;
    sending = true;
    try {
      let last = null;
      try { last = receipt(); } catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      if (last && Date.now() < last.until) return;
      const day = last ? last.day : null;
      // Saved before sending: a lost answer, a second window or a failing server
      // waits before another attempt, and a device that cannot remember sends nothing.
      localStorage.setItem(KEY, JSON.stringify({ day, until: Date.now() + RETRY_AFTER }));
      const response = await fetch("https://owner.bhakti.eeshan.xyz/api/visit", {
        method: "POST", mode: "cors", credentials: "omit", cache: "no-store", keepalive: true,
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify(day ? { last: day } : {}),
      });
      if (!response.ok) return;
      const answer = await response.json();
      localStorage.setItem(KEY, JSON.stringify({ day: answer.day, until: answer.until }));
    } catch (_) {
      // Counting must never affect listening; a later view tries again.
    } finally {
      sending = false;
    }
  };
  document.addEventListener("visibilitychange", count);
  void count();
})();
