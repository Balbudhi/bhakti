(() => {
  if (!("serviceWorker" in navigator)) return;

  let hadController = Boolean(navigator.serviceWorker.controller);
  let updateReady = false;
  let reloading = false;
  let lastCheck = 0;
  let listeningStarted = false;
  const audio = document.querySelector("audio");
  const playback = audio && window.BHAKTI_READER?.playback?.(audio);

  const rememberListening = () => {
    if (audio && (!audio.paused || audio.currentTime > 0 || playback?.isPending())) {
      listeningStarted = true;
    }
  };
  rememberListening();
  audio?.addEventListener("play", () => { listeningStarted = true; });
  audio?.addEventListener("seeking", () => { listeningStarted = true; });
  audio?.addEventListener("bhakti:playback-state", rememberListening);

  const applyUpdateWhenSafe = () => {
    rememberListening();
    // Pause, track changes and returning from the lock screen are still part
    // of a listening session. The new worker can serve requests immediately;
    // adopt the new document on the next normal load without losing playback.
    if (!updateReady || reloading || document.visibilityState === "hidden" || listeningStarted) return;
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
    } catch (_) {
      // The site remains fully usable when service workers are unavailable.
    }
  });
})();
