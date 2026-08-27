(() => {
  if (!("serviceWorker" in navigator)) return;

  let hadController = Boolean(navigator.serviceWorker.controller);
  let updateReady = false;
  let reloading = false;
  let lastCheck = 0;

  const audioIsPlaying = () => {
    const audio = document.querySelector("audio");
    return Boolean(audio && !audio.paused && !audio.ended);
  };

  const applyUpdateWhenSafe = () => {
    if (!updateReady || reloading || document.visibilityState === "hidden" || audioIsPlaying()) return;
    reloading = true;
    window.location.reload();
  };

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController) {
      hadController = true;
      return;
    }
    updateReady = true;
    applyUpdateWhenSafe();
  });

  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("/sw.js?v=31", { updateViaCache: "none" });
      const checkForUpdate = () => {
        const now = Date.now();
        if (now - lastCheck < 5 * 60 * 1000) return;
        lastCheck = now;
        registration.update().catch(() => {});
      };
      checkForUpdate();
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState !== "visible") return;
        applyUpdateWhenSafe();
        checkForUpdate();
      });
      window.addEventListener("pageshow", event => {
        if (event.persisted) checkForUpdate();
      });
      document.querySelector("audio")?.addEventListener("pause", applyUpdateWhenSafe);
    } catch (_) {
      // The site remains fully usable when service workers are unavailable.
    }
  });
})();
