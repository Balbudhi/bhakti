(() => {
  "use strict";

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
  let viewRequest = 0;
  let dataLoadChain = Promise.resolve();
  let advancing = false;
  let draggedRow = null;
  let dragPointerId = null;
  let dragMoved = false;
  let rowToolsEntryId = "";
  let queueToolsExpanded = false;
  const songDataCache = new Map();

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

  const renderQueuePill = () => {
    const visible = queueIsVisible(queueState);
    queuePill.hidden = !visible;
    if (!visible) return;
    const count = activeItems(queueState).length;
    queuePill.innerHTML = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h9"/></svg><span>${count}</span>`;
    const expanded = queuePill.getAttribute("aria-expanded") === "true";
    queuePill.setAttribute("aria-label", `${expanded ? "Hide" : "Show"} playlist, ${count} song${count === 1 ? "" : "s"}`);
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
          : `<button class="queue-drag-handle" type="button" data-queue-action="row-tools" data-queue-drag="${escapeHtml(item.entryId)}" aria-label="Reorder or edit ${escapeHtml(item.title)}; drag, use arrow keys, or press for options" title="Drag to reorder; press for options">⋮⋮</button>`}
        <div class="queue-copy">${currentRow
          ? `<div class="queue-song-title">${escapeHtml(item.title)}</div>`
          : `<button class="queue-song-select" type="button" data-queue-action="play">${escapeHtml(item.title)}</button>`}${item.credit ? `<div class="queue-credit">${escapeHtml(item.credit)}</div>` : ""}</div>
        ${!currentRow && rowToolsEntryId === item.entryId
          ? `<button class="queue-remove-text" type="button" data-queue-action="remove">Remove</button>`
          : `<span aria-hidden="true"></span>`}
      </div>`;
    queueSheet.innerHTML = `
      <div class="queue-list">
        ${row(current, absoluteStart, true)}
        ${future.map((item, index) => row(item, absoluteStart + index + 1)).join("")}
        <div class="queue-inline-tools">
          <button class="queue-tools-toggle" type="button" data-queue-action="tools" aria-label="${queueToolsExpanded ? "Hide" : "Show"} playlist actions" aria-expanded="${queueToolsExpanded}">•••</button>
          <div class="queue-tools"${queueToolsExpanded ? "" : " hidden"}>
            <button class="queue-action" type="button" data-queue-action="share">Share</button>
            <button class="queue-action" type="button" data-queue-action="shuffle"${future.length < 2 ? " disabled" : ""}>Shuffle</button>
            <button class="queue-action" type="button" data-queue-action="clear">Clear</button>
          </div>
        </div>
      </div>
      `;
    queueSheet.querySelector(".queue-list").scrollTop = previousScrollTop;
  };

  const openQueue = () => {
    if (!queueIsVisible(queueState)) return;
    queueToolsExpanded = false;
    rowToolsEntryId = "";
    renderQueueSheet();
    queueSheet.hidden = false;
    document.body.classList.add("queue-open");
    queuePill.setAttribute("aria-expanded", "true");
    renderQueuePill();
  };

  const closeQueue = ({ returnFocus = false } = {}) => {
    if (queueSheet.hidden) return;
    queueSheet.hidden = true;
    document.body.classList.remove("queue-open");
    queuePill.setAttribute("aria-expanded", "false");
    renderQueuePill();
    if (returnFocus) queuePill.focus();
  };

  const shareQueue = async () => {
    const remaining = activeItems(queueState);
    const shareState = Queue.create({
      mode: queueState.mode,
      items: remaining,
      currentIndex: 0,
      sessionId: queueState.sessionId,
    });
    const url = new URL(view === "song" && currentSong ? songPath(currentSong.slug) : "/", location.origin);
    url.searchParams.set("queue", Queue.encode(shareState));
    try {
      if (navigator.share) {
        await navigator.share({ title: "Bhakti playlist", url: url.href });
        return;
      }
      await navigator.clipboard.writeText(url.href);
      showStatus("Playlist link copied");
    } catch (error) {
      if (error?.name !== "AbortError") showStatus("Could not share playlist");
    }
  };

  const clearQueue = () => {
    audio.pause();
    try { audio.currentTime = 0; } catch (_) {}
    try { sessionStorage.removeItem(SESSION_KEY); } catch (_) {}
    closeQueue();
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
  queuePill.addEventListener("click", () => queueSheet.hidden ? openQueue() : closeQueue());
  queueSheet.addEventListener("click", event => {
    const button = event.target.closest("[data-queue-action]");
    if (!button || button.disabled || !queueState) return;
    const action = button.dataset.queueAction;
    const row = button.closest("[data-queue-index]");
    const index = Number(row?.dataset.queueIndex);
    if (action === "remove") setQueueState(Queue.remove(queueState, index));
    else if (action === "play") {
      setQueueState(Queue.playNow(queueState, queueState.items[index]));
      selectAudioSong(currentSong, { autoplay: true, force: true });
      if (view === "song") showSong(currentSong.slug, { historyMode: "replace" });
    } else if (action === "shuffle") setQueueState(Queue.shuffleRemaining(queueState, Math.random));
    else if (action === "share") shareQueue();
    else if (action === "clear") clearQueue();
    else if (action === "tools") {
      queueToolsExpanded = !queueToolsExpanded;
      renderQueueSheet();
      queueSheet.querySelector("[data-queue-action='tools']")?.focus();
    } else if (action === "row-tools") {
      rowToolsEntryId = rowToolsEntryId === row.dataset.queueEntryId ? "" : row.dataset.queueEntryId;
      const entryId = row.dataset.queueEntryId;
      renderQueueSheet();
      queueSheet.querySelector(`[data-queue-drag="${CSS.escape(entryId)}"]`)?.focus();
    }
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
  queueSheet.addEventListener("pointerdown", event => {
    const handle = event.target.closest?.("[data-queue-drag]");
    if (!handle) return;
    draggedRow = handle.closest(".queue-row");
    dragPointerId = event.pointerId;
    dragMoved = false;
    handle.setPointerCapture(event.pointerId);
    draggedRow.classList.add("is-dragging");
    event.preventDefault();
  });
  queueSheet.addEventListener("pointermove", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    const list = queueSheet.querySelector(".queue-list");
    const listRect = list.getBoundingClientRect();
    if (event.clientY < listRect.top + 48) list.scrollTop -= 14;
    else if (event.clientY > listRect.bottom - 48) list.scrollTop += 14;
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".queue-row:not(.is-current)");
    if (!target || target === draggedRow || target.parentElement !== draggedRow.parentElement) return;
    const before = event.clientY < target.getBoundingClientRect().top + target.getBoundingClientRect().height / 2;
    target.parentElement.insertBefore(draggedRow, before ? target : target.nextSibling);
    dragMoved = true;
  });
  const finishDrag = event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    draggedRow.classList.remove("is-dragging");
    const moved = dragMoved;
    const orderedEntryIds = [...queueSheet.querySelectorAll(".queue-row:not(.is-current)")]
      .map(row => row.dataset.queueEntryId);
    draggedRow = null;
    dragPointerId = null;
    dragMoved = false;
    if (moved) {
      rowToolsEntryId = "";
      setQueueState(Queue.reorderUpcoming(queueState, orderedEntryIds));
      showStatus("Playlist reordered");
    }
  };
  queueSheet.addEventListener("pointerup", finishDrag);
  queueSheet.addEventListener("pointercancel", event => {
    if (!draggedRow || event.pointerId !== dragPointerId) return;
    draggedRow = null;
    dragPointerId = null;
    dragMoved = false;
    renderQueueSheet();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      if (rowToolsEntryId) {
        rowToolsEntryId = "";
        renderQueueSheet();
      } else if (!queueSheet.hidden) closeQueue({ returnFocus: true });
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
