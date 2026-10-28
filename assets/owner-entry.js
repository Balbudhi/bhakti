// This is only a discreet entrance. The separate service enforces owner access.
(() => {
  let press = null;
  let timer = 0;
  let opened = false;
  let suppressClick = false;
  const cancel = () => {
    clearTimeout(timer);
    timer = 0;
    press = null;
  };
  const openOwner = () => {
    cancel();
    if (opened) return;
    opened = true;
    window.location.assign("https://owner.bhakti.eeshan.xyz/");
  };
  document.addEventListener("pointerdown", event => {
    cancel();
    suppressClick = false;
    if (event.button !== 0 || event.isPrimary === false || !event.target.closest?.("#aboutToggle")) return;
    press = { id: event.pointerId, x: event.clientX, y: event.clientY };
    timer = setTimeout(() => { suppressClick = true; openOwner(); }, 2000);
  }, true);
  document.addEventListener("pointermove", event => {
    if (!press || event.pointerId !== press.id) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > 12) cancel();
  }, true);
  for (const type of ["pointerup", "pointercancel"]) document.addEventListener(type, cancel, true);
  document.addEventListener("contextmenu", event => {
    if (press && event.target.closest?.("#aboutToggle")) event.preventDefault();
  });
  document.addEventListener("click", event => {
    if (!suppressClick || !event.target.closest?.("#aboutToggle")) return;
    suppressClick = false;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  document.addEventListener("keydown", event => {
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey || event.repeat || event.code !== "KeyO") return;
    if (event.target.closest?.("input, textarea, select, [contenteditable]")) return;
    event.preventDefault();
    openOwner();
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) cancel(); });
  window.addEventListener("blur", cancel);
  window.addEventListener("resize", cancel);
  window.addEventListener("pageshow", () => { cancel(); opened = false; suppressClick = false; });
})();
