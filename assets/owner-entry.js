// Optional keyboard shortcut; the About panel contains the ordinary owner link.
(() => {
  let opened = false;
  document.addEventListener("keydown", event => {
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey || event.repeat || event.code !== "KeyO") return;
    if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    if (opened) return;
    opened = true;
    window.location.assign("https://owner.bhakti.eeshan.xyz/");
  });
  window.addEventListener("pageshow", () => { opened = false; });
})();
