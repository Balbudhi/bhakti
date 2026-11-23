// Counts this device once per day for the owner's visitor totals. No cookie or
// identifier: only the day it was last counted. See docs/OWNER_INTAKE.md.
(() => {
  const KEY = "bhakti-visit";
  if (location.hostname !== "bhakti.eeshan.xyz" || navigator.webdriver) return;
  let sending = false;

  const receipt = () => {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    return saved && /^\d{4}-\d{2}-\d{2}$/.test(saved.day) && Number.isFinite(saved.until) ? saved : null;
  };
  const count = async () => {
    if (sending || document.visibilityState !== "visible") return;
    sending = true;
    try {
      let last = null;
      try { last = receipt(); } catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      if (last && Date.now() < last.until) return;
      // Prove storage works first, so a device that cannot remember is never counted.
      localStorage.setItem(KEY, localStorage.getItem(KEY) || "null");
      const response = await fetch("https://owner.bhakti.eeshan.xyz/api/visit", {
        method: "POST", mode: "cors", credentials: "omit", cache: "no-store", keepalive: true,
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify(last ? { last: last.day } : {}),
      });
      if (!response.ok) return;
      const { day, until } = await response.json();
      localStorage.setItem(KEY, JSON.stringify({ day, until }));
    } catch (_) {
      // Counting must never affect listening; a later view tries again.
    } finally {
      sending = false;
    }
  };
  document.addEventListener("visibilitychange", count);
  void count();
})();
