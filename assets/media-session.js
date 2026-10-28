// The persistent app owns the audio/controller and queue. This adapter only
// publishes their current state and routes native media commands back to them.
export function attach({ audio, playback, getSong, canPrevious, canNext, previous, next }) {
  const session = globalThis.navigator?.mediaSession;
  if (!session) return Object.freeze({ refresh() {}, destroy() {} });

  let destroyed = false;
  let metadataKey = null;
  const registered = new Map();
  const listen = (action, handler) => {
    if (registered.has(action) && registered.get(action) === handler) return;
    try {
      session.setActionHandler(action, handler);
      registered.set(action, handler);
    } catch (_) { /* Individual native actions are not supported everywhere. */ }
  };
  const ready = () => audio.readyState >= 1 && Number.isFinite(audio.duration) && audio.duration > 0;
  const syncPosition = () => {
    if (typeof session.setPositionState !== "function") return;
    try {
      if (!getSong() || !ready() || !Number.isFinite(audio.currentTime)
        || !Number.isFinite(audio.playbackRate) || audio.playbackRate === 0) {
        session.setPositionState();
        return;
      }
      session.setPositionState({
        duration: audio.duration,
        position: Math.max(0, Math.min(audio.duration, audio.currentTime)),
        playbackRate: audio.playbackRate,
      });
    } catch (_) { /* A partially implemented platform must not stop playback. */ }
  };
  const syncPlayback = () => {
    session.playbackState = !getSong() ? "none" : playback.isPlaying() ? "playing" : "paused";
    syncPosition();
  };
  const seek = (time, fast = false) => {
    if (!getSong() || !ready() || !Number.isFinite(time)) return;
    const position = Math.max(0, Math.min(audio.duration, time));
    if (fast && typeof audio.fastSeek === "function") audio.fastSeek(position);
    else audio.currentTime = position;
    syncPosition();
  };
  const offset = details => Number.isFinite(details?.seekOffset) && details.seekOffset > 0
    ? details.seekOffset : 10;
  const handlers = {
    play: () => { if (getSong()) playback.play(null, { retry: true }); },
    pause: () => playback.pause(),
    stop: () => { playback.pause(); seek(0); },
    previoustrack: () => { if (getSong() && canPrevious()) previous(); },
    nexttrack: () => { if (getSong() && canNext()) next(); },
    seekbackward: details => seek(audio.currentTime - offset(details)),
    seekforward: details => seek(audio.currentTime + offset(details)),
    seekto: details => seek(details?.seekTime, details?.fastSeek === true),
  };

  const refresh = () => {
    if (destroyed) return;
    const song = getSong();
    const key = song ? JSON.stringify([song.slug, song.title, song.credit]) : null;
    if (key !== metadataKey) {
      metadataKey = key;
      if (!song) session.metadata = null;
      else if (typeof globalThis.MediaMetadata === "function") {
        session.metadata = new MediaMetadata({
          title: song.title || "",
          artist: song.credit || "",
          album: "Bhakti",
          artwork: [
            { src: "/assets/icon-192.png", sizes: "192x192", type: "image/png" },
            { src: "/assets/favicon.png", sizes: "512x512", type: "image/png" },
          ],
        });
      }
    }
    for (const [action, handler] of Object.entries(handlers)) {
      const enabled = Boolean(song) && (action !== "previoustrack" || canPrevious())
        && (action !== "nexttrack" || canNext());
      listen(action, enabled ? handler : null);
    }
    syncPlayback();
  };
  const stateEvents = ["bhakti:playback-state", "playing", "pause", "ended", "emptied"];
  const positionEvents = ["loadedmetadata", "durationchange", "timeupdate", "seeked", "ratechange"];
  for (const event of stateEvents) audio.addEventListener(event, syncPlayback);
  for (const event of positionEvents) audio.addEventListener(event, syncPosition);
  refresh();

  return Object.freeze({
    refresh,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      for (const event of stateEvents) audio.removeEventListener(event, syncPlayback);
      for (const event of positionEvents) audio.removeEventListener(event, syncPosition);
      for (const action of registered.keys()) listen(action, null);
      session.metadata = null;
      session.playbackState = "none";
      try { session.setPositionState?.(); } catch (_) {}
    },
  });
}
