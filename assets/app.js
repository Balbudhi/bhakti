(() => {
  "use strict";

  const standaloneDisplay = navigator.standalone === true
    || matchMedia("(display-mode: standalone)").matches
    || matchMedia("(display-mode: fullscreen)").matches;
  document.documentElement.classList.toggle("bhakti-standalone", standaloneDisplay);

  const Queue = window.BHAKTI_QUEUE;
  const catalogue = window.BHAKTI_SONGS || [];
  if (!Queue || !catalogue.length) return;

  const SESSION_KEY = "bhakti:listening-session:v1";
  const bySlug = new Map(catalogue.map(song => [song.slug, song]));
  const byQueueId = new Map(catalogue.map(song => [song.queueId, song]));
  const audio = document.getElementById("songAudio");
  const player = document.getElementById("audioPlayer");
  const viewToggle = document.getElementById("appViewToggle") || document.querySelector(".song-home");
  if (!audio || !player || !viewToggle) return;

  const escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
  const newSessionId = () => globalThis.crypto?.randomUUID?.()
    || `queue-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const pathSlug = () => {
    const match = location.pathname.match(/^\/songs\/([^/]+)\/?$/);
    return match ? decodeURIComponent(match[1]) : "";
  };
  const songPath = slug => `/songs/${encodeURIComponent(slug)}/`;

  let view = document.querySelector("main.song-page") ? "song" : "library";
  let libraryRoot = document.querySelector("main.library-page, main#libraryView");
  let songRoot = document.querySelector("main.song-page");
  const initialRoot = document.querySelector("body > main");
  const appStage = document.createElement("div");
  appStage.className = "app-stage";
  initialRoot.replaceWith(appStage);
  appStage.append(initialRoot);
  let visibleSongSlug = view === "song" ? pathSlug() : "";
  let queueState = null;
  let currentSong = null;
  let statusTimer = 0;
  let queueCloseTimer = 0;
  let viewRequest = 0;
  let dataLoadChain = Promise.resolve();
  let advancing = false;
  const TOUCH_DRAG_HOLD_MS = 350;
  const DRAG_SLOP_PX = 12;
  let draggedRow = null;
  let dragPointerId = null;
  let dragTouchId = null;
  let dragInputType = "";
  let dragStartX = 0;
  let dragStartY = 0;
  let dragHoldTimer = 0;
  let dragActive = false;
  let dragMoved = false;
  let suppressQueueRowAction = false;
  const songDataCache = new Map();

  const pulseDragHaptic = duration => {
    if (!standaloneDisplay || !["touch", "pen"].includes(dragInputType)
      || typeof navigator.vibrate !== "function") return;
    try { navigator.vibrate(duration); } catch (_) {}
  };

  const initialData = window.BHAKTI_READER?.snapshotGlobals?.();
  const initialPageSlug = pathSlug();
  if (initialData?.meta?.title && initialPageSlug && bySlug.has(initialPageSlug)) {
    initialData.meta = {...initialData.meta, slug: initialPageSlug};
    songDataCache.set(initialPageSlug, initialData);
  }

  const queuePill = document.createElement("button");
  queuePill.className = "queue-pill";
  queuePill.type = "button";
  queuePill.hidden = true;
  queuePill.setAttribute("aria-expanded", "false");
  queuePill.setAttribute("aria-controls", "queueSheet");
  player.append(queuePill);

  const queueSheet = document.createElement("section");
  queueSheet.className = "queue-sheet";
  queueSheet.id = "queueSheet";
  queueSheet.hidden = true;
  queueSheet.setAttribute("role", "region");
  queueSheet.setAttribute("aria-label", "Playlist");
  document.body.append(queueSheet);

  const status = document.createElement("div");
  status.className = "app-status";
  status.hidden = true;
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  document.body.append(status);

  const showStatus = message => {
    clearTimeout(statusTimer);
    status.textContent = message;
    status.hidden = false;
    statusTimer = setTimeout(() => { status.hidden = true; }, 2200);
  };

  const setPlayerHeight = () => {
    const height = player.hidden ? 0 : Math.ceil(player.getBoundingClientRect().height);
    document.documentElement.style.setProperty("--app-player-height", `${height}px`);
  };

  const activeItems = state => state ? state.items.slice(state.currentIndex) : [];
  const queueIsVisible = state => Boolean(state && state.mode !== "standalone");

  const animateQueueReorder = (list, before) => {
    for (const row of list.querySelectorAll(".queue-row:not(.is-dragging)")) {
      const previous = before.get(row.dataset.queueEntryId);
      const next = row.getBoundingClientRect();
      if (!previous) continue;
      const delta = previous.top - next.top;
      if (Math.abs(delta) < 1) continue;
      row.style.transition = "none";
      row.style.transform = `translateY(${delta}px)`;
      requestAnimationFrame(() => {
        row.style.transition = "transform 180ms cubic-bezier(.2,.8,.2,1)";
        row.style.transform = "";
      });
    }
  };

  const renderQueuePill = () => {
    const visible = queueIsVisible(queueState);
    queuePill.hidden = !visible;
    if (!visible) return;
    const count = activeItems(queueState).length;
    queuePill.innerHTML = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h10"/><path d="m17 16 3 2-3 2z" fill="currentColor" stroke="none"/></svg>`;
    const expanded = queuePill.getAttribute("aria-expanded") === "true";
    const action = `${expanded ? "Hide" : "Show"} playlist, ${count} song${count === 1 ? "" : "s"}`;
    queuePill.setAttribute("aria-label", action);
    queuePill.title = action;
  };

  const updateViewToggle = () => {
    document.body.dataset.appView = view;
    if (view === "song") {
      viewToggle.href = "/";
      viewToggle.setAttribute("aria-label", "Browse songs");
      viewToggle.title = "Browse songs";
    } else if (currentSong) {
      viewToggle.href = songPath(currentSong.slug);
      viewToggle.setAttribute("aria-label", `Return to ${currentSong.title}`);
      viewToggle.title = `Return to ${currentSong.title}`;
    }
  };

  const persistQueue = () => {
    try {
      if (queueState) sessionStorage.setItem(SESSION_KEY, JSON.stringify(queueState));
      else sessionStorage.removeItem(SESSION_KEY);
    } catch (_) { /* Private-mode storage failures do not disable listening. */ }
  };

  const playlistUrl = path => {
    const url = new URL(path, location.origin);
    if (queueIsVisible(queueState)) url.searchParams.set("queue", Queue.encode(queueState));
    return `${url.pathname}${url.search}`;
  };

  const replaceHistoryMarker = () => {
    const nextState = {...(history.state || {})};
    if (queueState) nextState.bhaktiSessionId = queueState.sessionId;
    else delete nextState.bhaktiSessionId;
    nextState.bhaktiView = view;
    history.replaceState(nextState, "", playlistUrl(location.pathname));
  };

  const setQueueState = (state, { persist = true } = {}) => {
    queueState = state;
    currentSong = state?.items[state.currentIndex] || null;
    if (persist) persistQueue();
    renderQueuePill();
    updateViewToggle();
    replaceHistoryMarker();
    if (!queueSheet.hidden) renderQueueSheet();
  };

  const resolvedSources = item => (item.audioSources || []).map(source => ({
    src: new URL(source.src, new URL(songPath(item.slug), location.origin)).href,
    type: source.type || "",
  }));

  const attemptPlay = () => {
    const attempt = audio.play();
    if (!attempt?.catch) return;
    attempt.catch(error => {
      if (error?.name === "NotAllowedError") showStatus("Press Play to continue");
      else showStatus("This recording could not start");
    });
  };

  const selectAudioSong = (item, { autoplay = false, force = false } = {}) => {
    if (!item) return;
    const changed = force || audio.dataset.songSlug !== item.slug;
    if (changed) {
      audio.pause();
      audio.replaceChildren(...resolvedSources(item).map(source => {
        const element = document.createElement("source");
        element.src = source.src;
        if (source.type) element.type = source.type;
        return element;
      }));
      audio.dataset.songSlug = item.slug;
      audio.load();
      document.getElementById("apProgressBar")?.style.setProperty("width", "0%");
      const elapsed = document.getElementById("apElapsed");
      if (elapsed) elapsed.textContent = "0:00";
    }
    player.hidden = false;
    document.body.classList.add("session-player-visible");
    requestAnimationFrame(setPlayerHeight);
    if (autoplay) attemptPlay();
  };

  const hidePlayer = () => {
    player.hidden = true;
    document.body.classList.remove("session-player-visible");
    setPlayerHeight();
  };

  const snapshotCurrentGlobals = () => window.BHAKTI_READER.snapshotGlobals();
  const loadSongData = slug => {
    if (songDataCache.has(slug)) return Promise.resolve(songDataCache.get(slug));
    const load = () => new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${songPath(slug)}data.js`;
      script.async = true;
      script.addEventListener("load", () => {
        try {
          const data = snapshotCurrentGlobals();
          if (!data?.meta?.title) throw new Error(`song data metadata missing for ${slug}`);
          data.meta = {...data.meta, slug};
          songDataCache.set(slug, data);
          resolve(data);
        } catch (error) {
          reject(error);
        } finally {
          script.remove();
        }
      }, { once: true });
      script.addEventListener("error", () => {
        script.remove();
        reject(new Error(`could not load song data for ${slug}`));
      }, { once: true });
      document.head.append(script);
    });
    const result = dataLoadChain.then(load);
    dataLoadChain = result.catch(() => {});
    return result;
  };

  const fetchMain = async (url, selector) => {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`could not load ${url}`);
    const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
    const main = parsed.querySelector(selector);
    if (!main) throw new Error(`missing ${selector} in ${url}`);
    return document.importNode(main, true);
  };

  const ensureLibraryRoot = async () => {
    if (!libraryRoot) libraryRoot = await fetchMain("/", "main.library-page, main#libraryView");
    return libraryRoot;
  };

  const ensureSongRoot = async slug => {
    if (!songRoot) songRoot = await fetchMain(songPath(slug), "main.song-page");
    return songRoot;
  };

  const transitionTo = async (nextRoot, direction, prepare) => {
    const currentRoot = appStage.querySelector(":scope > main");
    if (currentRoot === nextRoot) {
      prepare?.();
      return;
    }
    closeQueue();
    const motionClasses = ["app-view-in-left", "app-view-out-right", "app-view-in-right", "app-view-out-left"];
    currentRoot?.classList.remove(...motionClasses);
    nextRoot.classList.remove(...motionClasses);
    appStage.append(nextRoot);
    prepare?.();
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      currentRoot?.remove();
      return;
    }
    const incomingClass = direction === "right" ? "app-view-in-left" : "app-view-in-right";
    const outgoingClass = direction === "right" ? "app-view-out-right" : "app-view-out-left";
    appStage.style.height = `${Math.max(currentRoot?.offsetHeight || 0, nextRoot.offsetHeight)}px`;
    appStage.classList.add("is-view-transitioning");
    nextRoot.classList.add(incomingClass);
    currentRoot?.classList.add(outgoingClass);
    await new Promise(resolve => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      nextRoot.addEventListener("animationend", finish, { once: true });
      setTimeout(finish, 280);
    });
    currentRoot?.classList.remove(outgoingClass);
    currentRoot?.remove();
    nextRoot.classList.remove(incomingClass);
    appStage.classList.remove("is-view-transitioning");
    appStage.style.height = "";
  };

  const route = (nextView, slug, mode) => {
    if (mode === "none") return;
    const path = playlistUrl(nextView === "song" ? songPath(slug) : "/");
    const state = { bhaktiView: nextView };
    if (queueState) state.bhaktiSessionId = queueState.sessionId;
    history[mode === "replace" ? "replaceState" : "pushState"](state, "", path);
  };

  const showLibrary = async ({ historyMode = "push" } = {}) => {
    const request = ++viewRequest;
    try {
      const root = await ensureLibraryRoot();
      if (request !== viewRequest) return;
      await transitionTo(root, "right", () => window.BHAKTI_LIBRARY.mount(root));
      if (request !== viewRequest) return;
      view = "library";
      document.title = "Bhakti";
      if (!queueState) {
        currentSong = null;
        hidePlayer();
      }
      route(view, "", historyMode);
      updateViewToggle();
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (error) {
      console.error("Bhakti library view failed", error);
      showStatus("The song library could not be loaded");
    }
  };

  const showSong = async (slug, { historyMode = "push" } = {}) => {
    if (!bySlug.has(slug)) return;
    if (queueState && currentSong?.slug !== slug) {
      const wasPlaying = !audio.paused;
      const selectedEntry = queueState.items.slice(queueState.currentIndex + 1)
        .find(item => item.slug === slug) || bySlug.get(slug);
      const next = queueState.mode === "standalone"
        ? Queue.standalone(bySlug.get(slug), queueState.sessionId)
        : Queue.playNow(queueState, selectedEntry);
      setQueueState(next);
      selectAudioSong(currentSong, { autoplay: wasPlaying, force: true });
    }
    const request = ++viewRequest;
    try {
      const [root, data] = await Promise.all([ensureSongRoot(slug), loadSongData(slug)]);
      if (request !== viewRequest) return;
      await transitionTo(root, "left", () => window.BHAKTI_READER.setSong(data));
      if (request !== viewRequest) return;
      view = "song";
      visibleSongSlug = slug;
      route(view, slug, historyMode);
      updateViewToggle();
      window.scrollTo({ top: 0, behavior: "auto" });
      if (!queueState) {
        const state = Queue.standalone(bySlug.get(slug), newSessionId());
        setQueueState(state, { persist: false });
        selectAudioSong(state.items[0]);
      }
    } catch (error) {
      console.error(`Bhakti song view failed for ${slug}`, error);
      showStatus("This song could not be loaded");
    }
  };

  const addSongToPlaylist = song => {
    const sessionId = queueState?.sessionId || newSessionId();
    const hadSession = Boolean(queueState);
    const next = Queue.append(queueState, song, sessionId);
    setQueueState(next);
    if (!hadSession) selectAudioSong(currentSong);
    showStatus(`${song.title} added`);
  };

  const renderQueueSheet = () => {
    if (draggedRow) resetDragGesture();
    const previousScrollTop = queueSheet.querySelector(".queue-list")?.scrollTop || 0;
    if (!queueState) {
      queueSheet.innerHTML = `<div class="queue-empty">No songs queued yet.</div>`;
      return;
    }
    const items = activeItems(queueState);
    const absoluteStart = queueState.currentIndex;
    const current = items[0];
    const future = items.slice(1);
    const row = (item, absoluteIndex, currentRow = false) => `
      <div class="queue-row${currentRow ? " is-current" : ""}" data-queue-index="${absoluteIndex}" data-queue-entry-id="${escapeHtml(item.entryId)}">
        ${currentRow
          ? `<span class="queue-current-dot" aria-hidden="true">●</span>`
          : `<button class="queue-drag-handle" type="button" data-queue-drag="${escapeHtml(item.entryId)}" aria-label="Reorder ${escapeHtml(item.title)}; drag here or hold then drag the row; use arrow keys" title="Drag to reorder; hold and drag anywhere in the row; use arrow keys">⋮⋮</button>`}
        <div class="queue-copy">${currentRow
          ? `<div class="queue-song-title">${escapeHtml(item.title)}</div>${item.credit ? `<div class="queue-credit">${escapeHtml(item.credit)}</div>` : ""}`
          : `<div class="queue-song-title">${escapeHtml(item.title)}</div>${item.credit ? `<div class="queue-credit">${escapeHtml(item.credit)}</div>` : ""}`}</div>
        ${!currentRow
          ? `<div class="queue-row-actions"><button class="queue-row-action" type="button" data-queue-action="play" aria-label="Play ${escapeHtml(item.title)} now" title="Play now"><svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg></button><button class="queue-row-action queue-row-remove" type="button" data-queue-action="remove" aria-label="Remove ${escapeHtml(item.title)} from playlist" title="Remove from playlist"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button></div>`
          : `<span aria-hidden="true"></span>`}
      </div>`;
    queueSheet.innerHTML = `
      <div class="queue-sheet-tools">
        <div class="queue-tools" role="group" aria-label="Playlist actions">
          <button class="queue-action" type="button" data-queue-action="queue-play" aria-label="Play the current queue song" title="Play current song"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg></button>
          <button class="queue-action" type="button" data-queue-action="shuffle" aria-label="Shuffle upcoming songs" title="Shuffle upcoming songs"${future.length < 2 ? " disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg></button>
          <button class="queue-action" type="button" data-queue-action="clear" aria-label="Clear this playlist" title="Clear playlist"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>
        </div>
      </div>
      <div class="queue-list">
        ${row(current, absoluteStart, true)}
        ${future.map((item, index) => row(item, absoluteStart + index + 1)).join("")}
      </div>
      `;
    queueSheet.querySelector(".queue-list").scrollTop = previousScrollTop;
  };

  const openQueue = () => {
    if (!queueIsVisible(queueState)) return;
    clearTimeout(queueCloseTimer);
    queueSheet.classList.remove("is-closing");
    renderQueueSheet();
    queueSheet.hidden = false;
    document.body.classList.add("queue-open");
    queuePill.setAttribute("aria-expanded", "true");
    renderQueuePill();
  };

  const closeQueue = ({ returnFocus = false, immediate = false } = {}) => {
    if (queueSheet.hidden || queueSheet.classList.contains("is-closing")) return;
    if (draggedRow) resetDragGesture();
    document.body.classList.remove("queue-open");
    queuePill.setAttribute("aria-expanded", "false");
    renderQueuePill();
    if (returnFocus) queuePill.focus();
    const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (immediate || reduceMotion) {
      queueSheet.hidden = true;
      return;
    }
    queueSheet.classList.add("is-closing");
    queueCloseTimer = setTimeout(() => {
      queueSheet.hidden = true;
      queueSheet.classList.remove("is-closing");
    }, 180);
  };

  const clearQueue = () => {
    audio.pause();
    try { audio.currentTime = 0; } catch (_) {}
    try { sessionStorage.removeItem(SESSION_KEY); } catch (_) {}
    closeQueue({ immediate: true });
    if (view === "song" && bySlug.has(visibleSongSlug)) {
      queueState = null;
      currentSong = null;
      renderQueuePill();
      updateViewToggle();
      replaceHistoryMarker();
      selectAudioSong(bySlug.get(visibleSongSlug), { force: true });
    } else {
      queueState = null;
      currentSong = null;
      audio.removeAttribute("src");
      audio.replaceChildren();
      audio.removeAttribute("data-song-slug");
      audio.load();
      renderQueuePill();
      updateViewToggle();
      replaceHistoryMarker();
      hidePlayer();
    }
    showStatus("Playlist cleared");
  };

  const advanceQueue = ({ failed = false } = {}) => {
    if (advancing || !queueState || queueState.mode === "standalone") return;
    advancing = true;
    const next = Queue.advance(queueState);
    if (!next.advanced) {
      advancing = false;
      showStatus(failed ? "No playable songs remain" : "Playlist finished");
      return;
    }
    setQueueState(next.state);
    selectAudioSong(currentSong, { autoplay: true, force: true });
    if (view === "song") showSong(currentSong.slug, { historyMode: "replace" });
    advancing = false;
  };

  const initializeState = () => {
    const shared = new URL(location.href).searchParams.get("queue");
    if (shared) {
      const decoded = Queue.decode(shared, byQueueId, newSessionId(), catalogue.length);
      if (decoded) {
        queueState = decoded;
        currentSong = decoded.items[decoded.currentIndex];
        persistQueue();
        showStatus("Shared playlist ready — press Play");
      } else {
        showStatus("That playlist link is not valid");
      }
    } else {
      try {
        const restored = Queue.restore(sessionStorage.getItem(SESSION_KEY), byQueueId);
        if (restored && history.state?.bhaktiSessionId === restored.sessionId) {
          queueState = restored;
          currentSong = restored.items[restored.currentIndex];
        }
      } catch (_) {}
    }

    const initialSlug = pathSlug();
    if (queueState && initialSlug && currentSong?.slug !== initialSlug && bySlug.has(initialSlug)) {
      const selectedEntry = queueState.items.slice(queueState.currentIndex + 1)
        .find(item => item.slug === initialSlug) || bySlug.get(initialSlug);
      queueState = queueState.mode === "standalone"
        ? Queue.standalone(bySlug.get(initialSlug), queueState.sessionId)
        : Queue.playNow(queueState, selectedEntry);
      currentSong = queueState.items[queueState.currentIndex];
      persistQueue();
    }
    if (!queueState && initialSlug && bySlug.has(initialSlug)) {
      queueState = Queue.standalone(bySlug.get(initialSlug), newSessionId());
      currentSong = queueState.items[0];
    }
    if (queueState) {
      if (audio.querySelector("source") && initialSlug === currentSong.slug) audio.dataset.songSlug = currentSong.slug;
      else selectAudioSong(currentSong);
      player.hidden = false;
      document.body.classList.add("session-player-visible");
    } else if (view === "library") {
      hidePlayer();
    }
    renderQueuePill();
    updateViewToggle();
    replaceHistoryMarker();
    requestAnimationFrame(setPlayerHeight);
  };

  document.addEventListener("bhakti:add-to-queue", event => addSongToPlaylist(event.detail.song));
  document.addEventListener("bhakti:shuffle-request", event => {
    const songs = event.detail?.songs || [];
    if (!songs.length) return;
    const next = Queue.shuffle(songs, Math.random, newSessionId());
    setQueueState(next);
    selectAudioSong(currentSong, { autoplay: true, force: true });
    showStatus(`Shuffled ${songs.length} song${songs.length === 1 ? "" : "s"}`);
  });
  document.addEventListener("click", event => {
    const link = event.target.closest?.(".song-card-link");
    if (link && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      const slug = link.closest("[data-song-slug]")?.dataset.songSlug;
      if (slug) showSong(slug);
      return;
    }
  });
  viewToggle.addEventListener("click", event => {
    event.preventDefault();
    if (view === "song") showLibrary();
    else if (currentSong) showSong(currentSong.slug);
  });
  queuePill.addEventListener("click", () => {
    if (queueSheet.hidden) openQueue();
    else closeQueue();
  });
  document.addEventListener("click", event => {
    if (queueSheet.hidden || queueSheet.contains(event.target) || player.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!queueSheet.classList.contains("is-closing")) closeQueue();
  }, true);
  queueSheet.addEventListener("click", event => {
    if (suppressQueueRowAction) {
      suppressQueueRowAction = false;
      event.preventDefault();
      return;
    }
    const button = event.target.closest("[data-queue-action]");
    if (!button || button.disabled || !queueState) return;
    const action = button.dataset.queueAction;
    const row = button.closest("[data-queue-index]");
    const index = Number(row?.dataset.queueIndex);
    if (action === "queue-play") attemptPlay();
    else if (action === "remove") setQueueState(Queue.remove(queueState, index));
    else if (action === "play") {
      setQueueState(Queue.playNow(queueState, queueState.items[index]));
      selectAudioSong(currentSong, { autoplay: true, force: true });
      if (view === "song") showSong(currentSong.slug, { historyMode: "replace" });
    } else if (action === "shuffle") setQueueState(Queue.shuffleRemaining(queueState, Math.random));
    else if (action === "clear") clearQueue();
  });
  queueSheet.addEventListener("keydown", event => {
    const handle = event.target.closest?.("[data-queue-drag]");
    if (!handle || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    const row = handle.closest("[data-queue-index]");
    const index = Number(row.dataset.queueIndex);
    const target = index + (event.key === "ArrowUp" ? -1 : 1);
    if (target <= queueState.currentIndex || target >= queueState.items.length) return;
    const entryId = row.dataset.queueEntryId;
    setQueueState(Queue.move(queueState, index, target));
    requestAnimationFrame(() => queueSheet.querySelector(`[data-queue-drag="${CSS.escape(entryId)}"]`)?.focus());
    showStatus(`${queueState.items[target].title} moved`);
  });
  queueSheet.addEventListener("keydown", event => {
    const handle = event.target.closest?.("[data-queue-drag]");
    if (!handle || (event.key !== "Delete" && event.key !== "Backspace")) return;
    event.preventDefault();
    const row = handle.closest("[data-queue-index]");
    const title = queueState.items[Number(row.dataset.queueIndex)].title;
    setQueueState(Queue.remove(queueState, Number(row.dataset.queueIndex)));
    showStatus(`${title} removed`);
  });
  const clearDragHold = () => {
    clearTimeout(dragHoldTimer);
    dragHoldTimer = 0;
  };
  const resetDragGesture = () => {
    const row = draggedRow;
    const pointerId = dragPointerId;
    clearDragHold();
    row?.classList.remove("is-dragging");
    draggedRow = null;
    dragPointerId = null;
    dragTouchId = null;
    dragInputType = "";
    dragStartX = 0;
    dragStartY = 0;
    dragActive = false;
    dragMoved = false;
    if (pointerId !== null && row?.hasPointerCapture?.(pointerId)) row.releasePointerCapture(pointerId);
  };
  const activateDrag = () => {
    clearDragHold();
    if (!draggedRow?.isConnected) {
      resetDragGesture();
      return;
    }
    dragActive = true;
    draggedRow.classList.add("is-dragging");
    if (dragPointerId !== null) {
      try {
        draggedRow.setPointerCapture(dragPointerId);
      } catch {
        resetDragGesture();
        return;
      }
    }
    pulseDragHaptic(18);
  };
  const moveDraggedRow = (clientX, clientY) => {
    const list = queueSheet.querySelector(".queue-list");
    const listRect = list.getBoundingClientRect();
    const edge = 56;
    if (clientY < listRect.top + edge) {
      list.scrollTop -= Math.ceil(((listRect.top + edge - clientY) / edge) * 18);
    } else if (clientY > listRect.bottom - edge) {
      list.scrollTop += Math.ceil(((clientY - (listRect.bottom - edge)) / edge) * 18);
    }
    const target = document.elementFromPoint(clientX, clientY)?.closest(".queue-row:not(.is-current)");
    if (!target || target === draggedRow || target.parentElement !== draggedRow.parentElement) return;
    const beforeRects = new Map([...list.querySelectorAll(".queue-row")]
      .map(row => [row.dataset.queueEntryId, row.getBoundingClientRect()]));
    const before = clientY < target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2;
    const alreadyPlaced = before
      ? draggedRow.nextElementSibling === target
      : target.nextElementSibling === draggedRow;
    if (alreadyPlaced) return;
    target.parentElement.insertBefore(draggedRow, before ? target : target.nextSibling);
    animateQueueReorder(list, beforeRects);
    pulseDragHaptic(8);
    dragMoved = true;
  };
  const startDragGesture = ({ row, inputType, pointerId = null, touchId = null, clientX, clientY }) => {
    draggedRow = row;
    dragPointerId = pointerId;
    dragTouchId = touchId;
    dragInputType = inputType;
    dragStartX = clientX;
    dragStartY = clientY;
    dragActive = false;
    dragMoved = false;
  };
  const dragTargetRow = (target, allowActionButtons = false) => {
    const row = target.closest?.(".queue-row:not(.is-current)");
    if (!row || target.closest(".queue-copy")) return null;
    if (!allowActionButtons && target.closest("[data-queue-action]")) return null;
    return row;
  };
  queueSheet.addEventListener("pointerdown", event => {
    if (event.pointerType === "touch" || draggedRow) return;
    const row = dragTargetRow(event.target, true);
    if (!row) return;
    startDragGesture({
      row,
      inputType: event.pointerType,
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
    });
    if (event.pointerType === "mouse") activateDrag();
    else dragHoldTimer = setTimeout(activateDrag, TOUCH_DRAG_HOLD_MS);
  });
  queueSheet.addEventListener("pointermove", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    if (!dragActive) {
      if (Math.hypot(event.clientX - dragStartX, event.clientY - dragStartY) > DRAG_SLOP_PX) {
        resetDragGesture();
      }
      return;
    }
    event.preventDefault();
    moveDraggedRow(event.clientX, event.clientY);
  });
  const touchById = touches => Array.from(touches)
    .find(touch => touch.identifier === dragTouchId);
  queueSheet.addEventListener("touchstart", event => {
    if (draggedRow || event.touches.length !== 1) return;
    const row = dragTargetRow(event.target, true);
    const touch = event.changedTouches[0];
    if (!row || !touch) return;
    startDragGesture({
      row,
      inputType: "touch",
      touchId: touch.identifier,
      clientX: touch.clientX,
      clientY: touch.clientY,
    });
    dragHoldTimer = setTimeout(activateDrag, TOUCH_DRAG_HOLD_MS);
  }, { passive: true });
  queueSheet.addEventListener("touchmove", event => {
    if (!draggedRow || dragInputType !== "touch") return;
    const touch = touchById(event.touches);
    if (!touch) return;
    if (!dragActive) {
      if (Math.hypot(touch.clientX - dragStartX, touch.clientY - dragStartY) > DRAG_SLOP_PX) {
        resetDragGesture();
      }
      return;
    }
    event.preventDefault();
    moveDraggedRow(touch.clientX, touch.clientY);
  }, { passive: false });
  const finishDragGesture = () => {
    const moved = dragMoved;
    const suppressAction = dragActive;
    const orderedEntryIds = [...queueSheet.querySelectorAll(".queue-row:not(.is-current)")]
      .map(row => row.dataset.queueEntryId);
    resetDragGesture();
    if (suppressAction) {
      suppressQueueRowAction = true;
      setTimeout(() => { suppressQueueRowAction = false; }, 0);
    }
    if (moved) {
      setQueueState(Queue.reorderUpcoming(queueState, orderedEntryIds));
      showStatus("Playlist reordered");
    }
  };
  const cancelDragGesture = () => {
    const restoreOrder = dragActive && dragMoved;
    resetDragGesture();
    if (restoreOrder) renderQueueSheet();
  };
  document.addEventListener("pointerup", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    finishDragGesture();
  });
  document.addEventListener("pointercancel", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    cancelDragGesture();
  });
  queueSheet.addEventListener("pointerleave", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    if (dragActive && draggedRow.hasPointerCapture?.(dragPointerId)) return;
    cancelDragGesture();
  });
  queueSheet.addEventListener("lostpointercapture", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    cancelDragGesture();
  });
  queueSheet.addEventListener("touchend", event => {
    if (!draggedRow || dragInputType !== "touch" || !touchById(event.changedTouches)) return;
    finishDragGesture();
  });
  queueSheet.addEventListener("touchcancel", event => {
    if (!draggedRow || dragInputType !== "touch" || !touchById(event.changedTouches)) return;
    cancelDragGesture();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      if (!queueSheet.hidden) closeQueue({ returnFocus: true });
      return;
    }
  });
  audio.addEventListener("ended", () => advanceQueue());
  audio.addEventListener("error", () => {
    if (audio.dataset.songSlug) advanceQueue({ failed: true });
  });
  audio.addEventListener("play", () => {
    if (!queueState && audio.dataset.songSlug && bySlug.has(audio.dataset.songSlug)) {
      setQueueState(Queue.standalone(bySlug.get(audio.dataset.songSlug), newSessionId()));
    } else if (queueState) {
      persistQueue();
    }
  });
  window.addEventListener("popstate", () => {
    const slug = pathSlug();
    if (slug) showSong(slug, { historyMode: "none" });
    else showLibrary({ historyMode: "none" });
  });
  window.addEventListener("resize", setPlayerHeight, { passive: true });

  initializeState();
  window.BHAKTI_APP = Object.freeze({
    showLibrary,
    showSong,
    getQueue: () => queueState,
  });
})();
