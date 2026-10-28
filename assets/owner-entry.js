// Discreet entrance only; the owner service enforces passkey authorization.
(() => {
  let taps = 0;
  let lastHeading = null;
  let opened = false;
  const reset = () => { taps = 0; lastHeading = null; };
  const openOwner = () => {
    reset();
    if (opened) return;
    opened = true;
    window.location.assign("https://owner.bhakti.eeshan.xyz/");
  };
  document.addEventListener("click", event => {
    const heading = event.target.closest?.("#aboutHeading");
    const panel = heading?.closest("#aboutPanel");
    if (!heading || !panel || panel.hidden || event.button > 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) {
      reset();
      return;
    }
    if (heading !== lastHeading) reset();
    lastHeading = heading;
    if (++taps === 5) openOwner();
  }, true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") reset();
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey || event.repeat || event.code !== "KeyO") return;
    if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    openOwner();
  });
  document.addEventListener("visibilitychange", reset);
  window.addEventListener("blur", reset);
  window.addEventListener("pageshow", () => { reset(); opened = false; });
})();
