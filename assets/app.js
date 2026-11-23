(() => {
  "use strict";

  const standaloneDisplay = navigator.standalone === true
    || matchMedia("(display-mode: standalone)").matches
    || matchMedia("(display-mode: fullscreen)").matches;
  document.documentElement.classList.toggle("bhakti-standalone", standaloneDisplay);

  // CSS viewport units can lag the visible viewport after iOS rotation or
  // keyboard dismissal. All fixed overlays share measured layout coordinates.
  const visualViewport = window.visualViewport;
  let viewportFrame = 0;
  const viewportSettleTimers = new Set();
  let viewportHeight = null;
  let viewportTop = null;
  const query = q => typeof matchMedia === "function" && matchMedia(q).matches === true;
  const installedApp = () => query("(display-mode: standalone)") || window.navigator?.standalone === true;
  const editingText = () => {
    const el = document.activeElement;
    return !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || "") && el.type !== "range";
  };
  const fullScreenHeight = () => {
    const s = window.screen;
    if (!s || !(s.width > 0) || !(s.height > 0)) return 0;
    return query("(orientation: landscape)") ? Math.min(s.width, s.height) : Math.max(s.width, s.height);
  };
  const setViewportBounds = () => {
    viewportFrame = 0;
    if (document.visibilityState === "hidden") return;
    const usableHeight = value => Number.isFinite(value) && value > 0;
    // VisualViewport dimensions and offsets use CSS pixels at every zoom level.
    // Keep native magnification; only track the visible edge.
    const useVisual = visualViewport && usableHeight(visualViewport.height);
    let height = useVisual ? visualViewport.height
      : usableHeight(window.innerHeight) ? window.innerHeight
        : document.documentElement.clientHeight;
    // An installed iPhone app can report a stale, short viewport after launch or resume, and
    // no later event corrects it; the player is then pinned partway up the screen. The app fills
    // the screen, so when no text field is focused (a real keyboard) and the page is not zoomed,
    // a height well short of the screen is stale: use the screen's height instead.
    if (installedApp() && !editingText() && !(useVisual && visualViewport.scale > 1.01)) {
      const screenHeight = fullScreenHeight();
      if (screenHeight > 0 && usableHeight(height) && height < screenHeight * 0.92) height = screenHeight;
    }
    // Background/restore transitions can briefly report no usable dimensions.
    // Retain the previous bounds (or the CSS fallback) until a valid event.
    if (!usableHeight(height)) return;
    const top = useVisual && Number.isFinite(visualViewport.offsetTop)
      ? Math.max(0, visualViewport.offsetTop) : 0;
    if (height !== viewportHeight) {
      document.documentElement.style.setProperty("--app-viewport-height", `${height}px`);
      viewportHeight = height;
    }
    if (top !== viewportTop) {
      document.documentElement.style.setProperty("--app-viewport-top", `${top}px`);
      viewportTop = top;
    }
  };
  const scheduleViewportBounds = () => {
    if (document.visibilityState === "hidden") return;
    if (!viewportFrame) viewportFrame = requestAnimationFrame(setViewportBounds);
  };
  const cancelViewportRefresh = () => {
    if (viewportFrame) cancelAnimationFrame(viewportFrame);
    viewportFrame = 0;
    viewportSettleTimers.forEach(clearTimeout);
    viewportSettleTimers.clear();
  };
  const settleViewportBounds = () => {
    cancelViewportRefresh();
    if (document.visibilityState === "hidden") return;
    scheduleViewportBounds();
    // Restore, rotation and keyboard dismissal can report the old positive
    // dimensions first, then settle without a further visualViewport event.
    // Re-read actual bounds for a finite window; never infer keyboard geometry.
    for (const delay of [100, 300, 1000]) {
      const timer = setTimeout(() => {
        viewportSettleTimers.delete(timer);
        scheduleViewportBounds();
      }, delay);
      viewportSettleTimers.add(timer);
    }
  };
  visualViewport?.addEventListener("resize", scheduleViewportBounds, { passive: true });
  visualViewport?.addEventListener("scroll", scheduleViewportBounds, { passive: true });
  window.addEventListener("resize", scheduleViewportBounds, { passive: true });
  window.addEventListener("scroll", scheduleViewportBounds, { passive: true });
  window.addEventListener("scrollend", scheduleViewportBounds, { passive: true });
  window.addEventListener("pageshow", settleViewportBounds);
  window.addEventListener("orientationchange", settleViewportBounds);
  document.addEventListener("focusout", settleViewportBounds);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") settleViewportBounds();
    else cancelViewportRefresh();
  });
  setViewportBounds();

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
  const playback = window.BHAKTI_READER.playback(audio);

  const escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
  const newSessionId = () => globalThis.crypto?.randomUUID?.()
    || `queue-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let shuffleRequest = null;
  const cancelShuffle = () => {
    shuffleRequest?.abort();
    shuffleRequest = null;
  };
  const runShuffle = (operation, ...args) => {
    // Match the existing engine's seeded Fisher-Yates baseline exactly. Its
    // first occurrence is fixed, so playback can start in the original gesture.
    const seed = Math.floor(args[1]() * 0x100000000) >>> 0;
    let randomState = seed;
    const random = () => {
      randomState = (randomState + 0x6d2b79f5) >>> 0;
      let mixed = randomState;
      mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
      mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 0x100000000;
    };
    let occurrences, prefix;
    const baseline = operation(...args, (items, fixedPrefix) => {
      occurrences = items;
      prefix = fixedPrefix;
      const ordered = items.slice();
      for (let index = ordered.length - 1; index > fixedPrefix; index--) {
        const other = fixedPrefix + Math.floor(random() * (index - fixedPrefix + 1));
        [ordered[index], ordered[other]] = [ordered[other], ordered[index]];
      }
      return ordered;
    });
    // The caller installs the baseline synchronously. A later queue edit (even
    // repeat changes) invalidates this request and cancels its worker work.
    Promise.resolve().then(async () => {
      if (queueState !== baseline || typeof window.BHAKTI_SHUFFLE_CLIENT?.order !== "function"
        || typeof window.BHAKTI_SHUFFLE_REVISION !== "string" || !window.BHAKTI_SHUFFLE_REVISION) return;
      const request = new AbortController();
      shuffleRequest = request;
      try {
        const ordered = await window.BHAKTI_SHUFFLE_CLIENT.order(occurrences, {
          seed, fixedPrefix: prefix, revision: window.BHAKTI_SHUFFLE_REVISION, signal: request.signal,
        });
        if (request.signal.aborted || queueState !== baseline) return;
        const fixedCount = baseline.currentIndex + 1;
        if (!Array.isArray(ordered) || ordered.length !== baseline.items.length
          || baseline.items.slice(0, fixedCount).some((item, index) => item.entryId !== ordered[index]?.entryId)) {
          throw new Error("Shuffle must preserve the playing occurrence and history");
        }
        // Queue validates exact unique upcoming membership. Rebuild from its
        // existing items; never replace audio or adopt worker-cloned metadata.
        const next = Queue.reorderUpcoming(baseline, ordered.slice(fixedCount).map(item => item.entryId));
        shuffleRequest = null;
        setQueueState(next);
      } catch (error) {
        if (!request.signal.aborted) console.warn("Shuffle ordering unavailable; retaining random order", error);
      } finally {
        if (shuffleRequest === request) shuffleRequest = null;
      }
    });
    return baseline;
  };
  const pathSlug = () => {
    const match = location.pathname.match(/^\/songs\/([^/]+)\/?$/);
    return match ? decodeURIComponent(match[1]) : "";
  };
  const songPath = slug => `/songs/${encodeURIComponent(slug)}/`;
  const assetPath = path => window.BHAKTI_ASSETS?.[path] || path;

  let view = document.querySelector("main.song-page") ? "song" : "library";
  let libraryRoot = document.querySelector("main.library-page, main#libraryView");
  let songRoot = document.querySelector("main.song-page");
  const initialRoot = document.querySelector("body > main");
  const appStage = document.createElement("div");
  appStage.className = "app-stage";
  initialRoot.replaceWith(appStage);
  appStage.append(initialRoot);
  // A normal-flow player avoids WebKit's drifting fixed-position attachment.
  // Keep its audio subtree exactly where it is; only the page stage is wrapped.
  const mobileStandalone = navigator.standalone === true
    || matchMedia("(display-mode: standalone) and (any-pointer: coarse)").matches;
  let contentScroller = null;
  if (mobileStandalone) {
    contentScroller = document.createElement("div");
    contentScroller.className = "app-scroll";
    contentScroller.tabIndex = 0;
    contentScroller.setAttribute("role", "region");
    contentScroller.setAttribute("aria-label", "Library and lyrics");
    appStage.replaceWith(contentScroller);
    contentScroller.append(appStage);
    document.documentElement.classList.add("bhakti-scroll-shell");
    document.body.classList.add("app-shell");
    const syncKeyboardFocus = () => {
      const focused = document.activeElement;
      const formEditing = focused?.matches?.('textarea, select, input:not([type="button"]):not([type="submit"]):not([type="reset"]):not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"]):not([type="hidden"])')
        && !focused.readOnly && !focused.disabled;
      const editable = focused?.closest?.('[contenteditable]');
      const editing = formEditing || (editable && editable.getAttribute("contenteditable") !== "false");
      document.body.classList.toggle("has-keyboard-focus", Boolean(editing));
      settleViewportBounds();
    };
    document.addEventListener("focusin", syncKeyboardFocus);
    document.addEventListener("focusout", syncKeyboardFocus);
    window.addEventListener("pageshow", syncKeyboardFocus);
    document.addEventListener("visibilitychange", syncKeyboardFocus);
    syncKeyboardFocus();
    const measureShell = () => {
      const height = document.body.clientHeight;
      if (height > 0) document.body.style.setProperty("--app-shell-height", `${height}px`);
    };
    if ("ResizeObserver" in window) new ResizeObserver(measureShell).observe(document.body);
    window.addEventListener("resize", measureShell, { passive: true });
    measureShell();
  }
  const contentScrollY = () => contentScroller ? contentScroller.scrollTop : window.scrollY;
  const scrollContentTo = top => (contentScroller || window).scrollTo({ top, behavior: "auto" });
  let visibleSongSlug = view === "song" ? pathSlug() : "";
  let readerScrollY = view === "song" ? contentScrollY() : 0;
  let queueState = null;
  let currentSong = null;
  let systemMedia = null;
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
  let dragGrabOffsetY = 0;
  let dragVisualY = 0;
  let dragHoldTimer = 0;
  let dragPressTimer = 0;
  let dragActive = false;
  let dragMoved = false;
  let dragMoveFrame = 0;
  let pendingDragPoint = null;
  let suppressQueueRowAction = false;
  const songDataCache = new Map();
  const pendingSongData = new Map();

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

  const repeatButton = document.createElement("button");
  repeatButton.className = "queue-pill repeat-toggle";
  repeatButton.type = "button";
  player.append(repeatButton);

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
  if ("ResizeObserver" in window) new ResizeObserver(setPlayerHeight).observe(player);

  const queueIsVisible = state => Boolean(state && state.mode !== "standalone");

  const animateQueueReorder = (list, before) => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    // Finish every layout read before changing a transform. Only rows already
    // visible in the scrollport participate; skipped content stays skipped.
    const moves = [];
    for (const [row, previous] of before) {
      if (row.parentElement !== list || row.classList.contains("is-dragging")) continue;
      const delta = previous.top - row.getBoundingClientRect().top;
      if (Math.abs(delta) >= 1) moves.push({ row, delta });
    }
    for (const { row, delta } of moves) {
      row.style.transition = "none";
      row.style.transform = `translateY(${delta}px)`;
    }
    if (moves.length) requestAnimationFrame(() => {
      for (const { row } of moves) {
        if (!row.isConnected || row.classList.contains("is-dragging")) continue;
        row.style.transition = "transform 180ms cubic-bezier(.2,.8,.2,1)";
        row.style.transform = "";
      }
    });
  };

  const renderQueuePill = () => {
    const repeat = queueState?.repeat || "off";
    const repeatLabel = {
      off: "Repeat off. Repeat this song",
      one: "Repeating this song. Repeat playlist",
      all: "Repeating playlist. Turn repeat off",
    }[repeat];
    repeatButton.disabled = !queueState;
    repeatButton.setAttribute("aria-pressed", String(repeat !== "off"));
    repeatButton.setAttribute("aria-label", repeatLabel);
    repeatButton.title = repeatLabel;
    repeatButton.innerHTML = `<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><use href="/assets/player-icons.svg#icon-repeat${repeat === "one" ? "-one" : ""}"/></svg>`;
    const visible = queueIsVisible(queueState);
    queuePill.hidden = !visible;
    if (!visible) return;
    const count = queueState.items.length;
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

  const setQueueState = state => {
    if (state !== queueState) cancelShuffle();
    queueState = state;
    currentSong = state?.items[state.currentIndex] || null;
    persistQueue();
    renderQueuePill();
    updateViewToggle();
    replaceHistoryMarker();
    if (!queueSheet.hidden) renderQueueSheet();
    systemMedia?.refresh();
  };

  const resolvedSources = item => (item.audioSources || []).map(source => ({
    src: new URL(source.src, new URL(songPath(item.slug), location.origin)).href,
    type: source.type || "",
  }));

  const attemptPlay = () => playback.play(null, { retry: true });

  const selectAudioSong = (item, { autoplay = false, force = false } = {}) => {
    if (!item) return;
    const changed = force || audio.dataset.songSlug !== item.slug;
    if (changed) {
      playback.reset();
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
    systemMedia?.refresh();
    if (autoplay) playback.play();
  };

  const hidePlayer = () => {
    player.hidden = true;
    document.body.classList.remove("session-player-visible");
    setPlayerHeight();
  };

  const snapshotCurrentGlobals = () => window.BHAKTI_READER.snapshotGlobals();
  const cacheSongData = (slug, data) => {
    songDataCache.delete(slug);
    songDataCache.set(slug, data);
    // Retain the mounted reader even while the library is visible, plus three
    // recent readers. The serialized loader bounds concurrent script globals.
    while (songDataCache.size > 4) {
      const oldest = [...songDataCache.keys()].find(key => key !== visibleSongSlug);
      songDataCache.delete(oldest);
    }
    return data;
  };
  const loadSongData = slug => {
    if (songDataCache.has(slug)) return Promise.resolve(cacheSongData(slug, songDataCache.get(slug)));
    if (pendingSongData.has(slug)) return pendingSongData.get(slug);
    const load = () => new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = assetPath(`${songPath(slug)}data.js`);
      const digest = new URL(script.src, window.location.href).searchParams.get("v");
      if (/^[a-f0-9]{64}$/i.test(digest || "")) {
        const bytes = digest.match(/../g).map(byte => parseInt(byte, 16));
        script.integrity = `sha256-${window.btoa(String.fromCharCode(...bytes))}`;
        script.crossOrigin = "anonymous";
      }
      script.async = true;
      script.addEventListener("load", () => {
        try {
          const data = snapshotCurrentGlobals();
          if (!data?.meta?.title) throw new Error(`song data metadata missing for ${slug}`);
          data.meta = {...data.meta, slug};
          cacheSongData(slug, data);
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
    const result = dataLoadChain.then(load).finally(() => pendingSongData.delete(slug));
    pendingSongData.set(slug, result);
    dataLoadChain = result.catch(() => {});
    return result;
  };

  const fetchMain = async (url, selector) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`could not load ${url}`);
    const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
    const main = parsed.querySelector(selector);
    if (!main) throw new Error(`missing ${selector} in ${url}`);
    return document.importNode(main, true);
  };

  let libraryRootLoad = null;
  let songRootLoad = null;
  const ensureLibraryRoot = async () => {
    if (!libraryRoot) {
      libraryRootLoad ||= fetchMain("/", "main.library-page, main#libraryView");
      try { libraryRoot = await libraryRootLoad; }
      finally { libraryRootLoad = null; }
    }
    return libraryRoot;
  };

  const ensureSongRoot = async slug => {
    if (!songRoot) {
      songRootLoad ||= fetchMain(songPath(slug), "main.song-page");
      try { songRoot = await songRootLoad; }
      finally { songRootLoad = null; }
    }
    return songRoot;
  };

  let finishViewTransition = null;
  const transitionTo = async (nextRoot, direction, prepare) => {
    // A rapid reversal must settle the old DOM ownership before choosing its
    // outgoing root. Old animation callbacks cannot remove the new view.
    finishViewTransition?.();
    const currentRoot = appStage.querySelector(":scope > main");
    if (currentRoot === nextRoot) {
      prepare?.();
      return;
    }
    // A detached focused search input may not dispatch blur on every browser.
    // Finish its keyboard state while it still belongs to the outgoing page.
    if (currentRoot?.contains?.(document.activeElement)) document.activeElement.blur?.();
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
    /* The song's fixed top controls are measured from <main> rather than the
       viewport for as long as <main> carries a transform, which drops them by
       the scroll offset. The document does not scroll until after this await,
       so one reading holds for the whole transition. */
    const controlHost = currentRoot?.querySelector("#songSync") ? currentRoot : nextRoot;
    const hostBox = controlHost.getBoundingClientRect();
    appStage.style.setProperty("--app-swipe-scroll", `${Math.round(contentScrollY())}px`);
    appStage.style.setProperty("--app-swipe-inset-left", `${Math.round(hostBox.left)}px`);
    appStage.style.setProperty("--app-swipe-inset-right",
      `${Math.round(document.documentElement.clientWidth - hostBox.right)}px`);
    nextRoot.classList.add(incomingClass);
    currentRoot?.classList.add(outgoingClass);
    await new Promise(resolve => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        nextRoot.removeEventListener("animationend", onAnimationEnd);
        clearTimeout(timer);
        currentRoot?.classList.remove(outgoingClass);
        currentRoot?.remove();
        nextRoot.classList.remove(incomingClass);
        appStage.classList.remove("is-view-transitioning");
        appStage.style.removeProperty("--app-swipe-scroll");
        appStage.style.removeProperty("--app-swipe-inset-left");
        appStage.style.removeProperty("--app-swipe-inset-right");
        appStage.style.height = "";
        finishViewTransition = null;
        resolve();
      };
      /* animationend bubbles. The lyric layers inside an arriving song finish
         at 180ms and 210ms, before the page's own 220ms slide, so an unfiltered
         listener here ended the transition at whichever descendant finished
         first and cut the slide short. Only the page's own animation counts. */
      const onAnimationEnd = event => {
        if (event.target === nextRoot) finish();
      };
      nextRoot.addEventListener("animationend", onAnimationEnd);
      const timer = setTimeout(finish, 280);
      finishViewTransition = finish;
    });
  };

  const route = (nextView, slug, mode) => {
    if (mode === "none") return;
    const path = playlistUrl(nextView === "song" ? songPath(slug) : "/");
    const state = { bhaktiView: nextView };
    if (queueState) state.bhaktiSessionId = queueState.sessionId;
    history[mode === "replace" ? "replaceState" : "pushState"](state, "", path);
  };

  const showLibrary = async ({ historyMode = "push" } = {}) => {
    if (view === "song") readerScrollY = contentScrollY();
    const request = ++viewRequest;
    try {
      const root = await ensureLibraryRoot();
      if (request !== viewRequest) return;
      await transitionTo(root, "right", () => {
        window.BHAKTI_READER.setVisible(false);
        window.BHAKTI_LIBRARY.mount(root);
      });
      if (request !== viewRequest) return;
      view = "library";
      document.title = "Bhakti";
      if (!queueState) {
        currentSong = null;
        hidePlayer();
      }
      route(view, "", historyMode);
      updateViewToggle();
      scrollContentTo(0);
    } catch (error) {
      console.error("Bhakti library view failed", error);
      showStatus("The song library could not be loaded");
    }
  };

  const showSong = async (slug, { historyMode = "push" } = {}) => {
    if (!bySlug.has(slug)) return;
    if (queueState && currentSong?.slug !== slug) {
      const wasPlaying = playback.isPlaying() || playback.isPending();
      const selectedEntry = queueState.items.slice(queueState.currentIndex + 1)
        .find(item => item.slug === slug) || bySlug.get(slug);
      const next = Queue.playNow(queueState, selectedEntry);
      setQueueState(next);
      selectAudioSong(currentSong, { autoplay: wasPlaying, force: true });
    }
    const request = ++viewRequest;
    try {
      const [root, data] = await Promise.all([ensureSongRoot(slug), loadSongData(slug)]);
      if (request !== viewRequest) return;
      const sameSong = visibleSongSlug === slug;
      const scrollTop = sameSong ? (view === "song" ? contentScrollY() : readerScrollY) : 0;
      await transitionTo(root, "left", () => {
        if (!sameSong) window.BHAKTI_READER.setSong(data);
        visibleSongSlug = slug;
        cacheSongData(slug, data);
        window.BHAKTI_READER.setVisible(true);
      });
      if (request !== viewRequest) return;
      view = "song";
      visibleSongSlug = slug;
      document.title = data.meta.title;
      readerScrollY = scrollTop;
      route(view, slug, historyMode);
      updateViewToggle();
      scrollContentTo(scrollTop);
      if (!queueState) {
        const state = Queue.standalone(bySlug.get(slug), newSessionId());
        setQueueState(state);
        selectAudioSong(state.items[0]);
      }
    } catch (error) {
      console.error(`Bhakti song view failed for ${slug}`, error);
      showStatus("This song could not be loaded");
    }
  };

  const addSongToPlaylist = (song, position = "end") => {
    const sessionId = queueState?.sessionId || newSessionId();
    const hadSession = Boolean(queueState);
    const next = position === "next"
      ? Queue.playNext(queueState, song, sessionId)
      : Queue.append(queueState, song, sessionId);
    setQueueState(next);
    if (!hadSession) selectAudioSong(currentSong);
    showStatus(`${song.title} ${position === "next" && hadSession ? "plays next" : "added"}`);
  };

  const playIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg>';
  const pauseIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor"/></svg>';
  const updateQueuePlayback = () => {
    const button = queueSheet.querySelector('[data-queue-action="queue-play"]');
    if (!button) return;
    const playing = playback.isPlaying();
    const pending = playback.isPending();
    const label = pending ? "Cancel loading" : `${playing ? "Pause" : "Play"} current song`;
    button.setAttribute("aria-busy", String(pending));
    const icon = playing ? pauseIcon : playIcon;
    if (button.dataset.playing !== String(playing)) {
      button.innerHTML = icon;
      button.dataset.playing = String(playing);
    }
    button.setAttribute("aria-label", label);
    button.title = label;
  };

  // Occurrence IDs own retained rows; reordering never recreates their controls.
  const queueRows = new Map();
  const visibleQueueRows = new Set();
  let queueRowObserver = null;
  const renderQueueSheet = () => {
    if (draggedRow) resetDragGesture();
    const previousScrollTop = queueSheet.querySelector(".queue-list")?.scrollTop || 0;
    const focused = queueSheet.contains(document.activeElement) ? document.activeElement : null;
    const focusedRow = focused?.closest("[data-queue-entry-id]");
    const focusEntryId = focusedRow?.dataset.queueEntryId;
    const focusIndex = focusedRow?.dataset.queueIndex;
    const focusAction = focused?.dataset.queueAction;
    const focusDrag = focused?.hasAttribute("data-queue-drag");
    if (!queueState) {
      queueRowObserver?.disconnect();
      queueRowObserver = null;
      visibleQueueRows.clear();
      queueRows.clear();
      queueSheet.innerHTML = `<div class="queue-empty">No songs queued yet.</div>`;
      return;
    }
    const futureCount = queueState.items.length - queueState.currentIndex - 1;
    const row = (item, index) => {
      const current = index === queueState.currentIndex;
      const played = index < queueState.currentIndex;
      return `
      <div class="queue-row ${current ? "is-current" : played ? "is-played" : "is-upcoming"}" data-queue-index="${index}" data-queue-entry-id="${escapeHtml(item.entryId)}"${current ? ' aria-current="true"' : ""}>
        ${current || played
          ? `<span class="queue-position" aria-hidden="true">${index + 1}</span>`
          : `<button class="queue-drag-handle" type="button" data-queue-drag="${escapeHtml(item.entryId)}" aria-label="Reorder ${escapeHtml(item.title)}; drag or use arrow keys" title="Drag or use arrow keys to reorder"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M8 7h.01M16 7h.01M8 12h.01M16 12h.01M8 17h.01M16 17h.01"/></svg></button>`}
        <div class="queue-copy"><div class="queue-song-title">${escapeHtml(item.title)}</div>${item.credit ? `<div class="queue-credit">${escapeHtml(item.credit)}</div>` : ""}</div>
        ${current
          ? ''
          : `<div class="queue-row-actions"><button class="queue-row-action" type="button" data-queue-action="${played ? "history" : "play"}" aria-label="Play ${escapeHtml(item.title)} ${played ? "again" : "now"}" title="${played ? "Play again" : "Play now"}">${playIcon}</button><button class="queue-row-action queue-row-remove" type="button" data-queue-action="remove" aria-label="Remove ${escapeHtml(item.title)} from playlist" title="Remove from playlist"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button></div>`}
      </div>`;
    };
    let list = queueSheet.querySelector(".queue-list");
    if (!list) {
      queueSheet.innerHTML = `
      <div class="queue-sheet-tools">
        <span class="queue-progress" aria-label="Song ${queueState.currentIndex + 1} of ${queueState.items.length}">${queueState.currentIndex + 1} / ${queueState.items.length}</span>
        <div class="queue-tools" role="group" aria-label="Playlist actions">
          <button class="queue-action" type="button" data-queue-action="previous" aria-label="Play previous song" title="Play previous song"${queueState.currentIndex === 0 ? " disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14M19 5 8 12l11 7V5z" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg></button>
          <button class="queue-action" type="button" data-queue-action="queue-play" aria-label="Play current song" title="Play current song">${playIcon}</button>
          <button class="queue-action" type="button" data-queue-action="next" aria-label="Play next song" title="Play next song"${futureCount || queueState.repeat === "all" ? "" : " disabled"}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 5v14M5 5l11 7-11 7V5z" fill="currentColor" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg></button>
          <button class="queue-action" type="button" data-queue-action="shuffle" aria-label="Shuffle upcoming songs" title="Shuffle upcoming songs"${futureCount < 2 ? " disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg></button>
          <button class="queue-action" type="button" data-queue-action="clear" aria-label="Clear upcoming songs" title="Clear upcoming songs"${futureCount ? "" : " disabled"}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>
        </div>
      </div>
      <div class="queue-list"></div>`;
      list = queueSheet.querySelector(".queue-list");
      if (typeof IntersectionObserver === "function") {
        queueRowObserver = new IntersectionObserver(entries => {
          for (const entry of entries) {
            if (entry.isIntersecting) visibleQueueRows.add(entry.target);
            else visibleQueueRows.delete(entry.target);
          }
        }, { root: list });
      }
    }
    const retained = new Set(queueState.items.map(item => item.entryId));
    for (const [entryId, record] of queueRows) {
      if (retained.has(entryId)) continue;
      queueRowObserver?.unobserve(record.node);
      visibleQueueRows.delete(record.node);
      record.node.remove();
      queueRows.delete(entryId);
    }
    const entries = queueState.items.map((item, index) => {
      const role = index === queueState.currentIndex ? "current" : index < queueState.currentIndex ? "played" : "upcoming";
      return { item, index, role, signature: JSON.stringify([item.title, item.credit, role]) };
    });
    const changed = entries.filter(entry => queueRows.get(entry.item.entryId)?.signature !== entry.signature);
    const prepared = new Map();
    if (changed.length) {
      // Parse one fragment even when starting/replacing a whole-library queue.
      const template = document.createElement("template");
      template.innerHTML = changed.map(({ item, index }) => row(item, index)).join("");
      for (const node of template.content.children) prepared.set(node.dataset.queueEntryId, node);
    }
    let cursor = list.firstElementChild;
    entries.forEach(({ item, index, role, signature }) => {
      let record = queueRows.get(item.entryId);
      if (!record || record.signature !== signature) {
        const rendered = prepared.get(item.entryId);
        if (record) {
          record.node.className = rendered.className;
          record.node.replaceChildren(...rendered.childNodes);
          if (role === "current") record.node.setAttribute("aria-current", "true");
          else record.node.removeAttribute("aria-current");
          record.signature = signature;
        } else {
          record = { node: rendered, signature };
          queueRows.set(item.entryId, record);
          queueRowObserver?.observe(record.node);
        }
      }
      const node = record.node;
      if (node.dataset.queueIndex !== String(index)) {
        node.dataset.queueIndex = String(index);
        const position = node.querySelector(".queue-position");
        if (position) position.textContent = String(index + 1);
      }
      if (node !== cursor) list.insertBefore(node, cursor);
      cursor = node.nextElementSibling;
    });
    const progress = queueSheet.querySelector(".queue-progress");
    progress.textContent = `${queueState.currentIndex + 1} / ${queueState.items.length}`;
    progress.setAttribute("aria-label", `Song ${queueState.currentIndex + 1} of ${queueState.items.length}`);
    for (const [action, disabled] of Object.entries({
      previous: queueState.currentIndex === 0,
      next: !futureCount && queueState.repeat !== "all",
      shuffle: futureCount < 2,
      clear: !futureCount,
    })) queueSheet.querySelector(`[data-queue-action="${action}"]`).disabled = disabled;
    list.scrollTop = previousScrollTop;
    updateQueuePlayback();
    if (focused) {
      const rowSelector = focusEntryId ? `[data-queue-entry-id="${CSS.escape(focusEntryId)}"] ` : "";
      const controlSelector = focusDrag ? "[data-queue-drag]" : `[data-queue-action="${CSS.escape(focusAction || "")}"]`;
      const restoredFocus = queueSheet.querySelector(`${rowSelector}${controlSelector}:not(:disabled)`)
        || (focusIndex && queueSheet.querySelector(`[data-queue-index="${focusIndex}"] ${controlSelector}:not(:disabled)`))
        || queueSheet.querySelector('[data-queue-action="queue-play"]');
      restoredFocus?.focus({ preventScroll: true });
    }
  };

  const revealCurrentQueueRow = () => {
    const list = queueSheet.querySelector(".queue-list");
    const current = list?.querySelector(".is-current");
    if (list && current) list.scrollTop = current.offsetTop - list.offsetTop - list.clientHeight / 3;
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
    revealCurrentQueueRow();
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
    if (!queueState) return;
    setQueueState(Queue.clearUpcoming(queueState));
    queueSheet.querySelector('[data-queue-action="queue-play"]')?.focus();
    showStatus("Upcoming songs cleared");
  };

  const previousQueue = () => {
    const previous = Queue.previous(queueState);
    if (!previous.moved) return;
    setQueueState(previous.state);
    revealCurrentQueueRow();
    selectAudioSong(currentSong, { autoplay: true, force: true });
    if (view === "song") void showSong(currentSong.slug, { historyMode: "replace" });
  };

  const advanceQueue = ({ reason = "next" } = {}) => {
    if (advancing || !queueState) return;
    advancing = true;
    const previousEntryId = currentSong.entryId;
    const next = Queue.advance(queueState, { reason });
    if (!next.advanced) {
      advancing = false;
      if (reason === "failed") showStatus("No playable songs remain");
      else if (queueIsVisible(queueState)) showStatus("Playlist finished");
      return;
    }
    setQueueState(next.state);
    // play() can synchronously report unavailable media; allow that failure to
    // advance too. Same-occurrence repeats retain sources and reading position.
    advancing = false;
    if (currentSong.entryId === previousEntryId) {
      playback.play(0);
      return;
    }
    revealCurrentQueueRow();
    selectAudioSong(currentSong, { autoplay: true, force: true });
    if (view === "song") showSong(currentSong.slug, { historyMode: "replace" });
  };

  const initializeState = () => {
    let restored = null;
    try { restored = Queue.restore(sessionStorage.getItem(SESSION_KEY), byQueueId); } catch (_) {}
    const shared = new URL(location.href).searchParams.get("queue");
    if (shared) {
      const decoded = restored && Queue.encode(restored) === shared
        ? restored
        : Queue.decode(shared, byQueueId, newSessionId());
      if (decoded) {
        queueState = decoded;
        currentSong = decoded.items[decoded.currentIndex];
        persistQueue();
      } else {
        showStatus("That playlist link is not valid");
      }
    } else if (restored) {
      queueState = restored;
      currentSong = restored.items[restored.currentIndex];
    }

    const initialSlug = pathSlug();
    if (queueState && initialSlug && currentSong?.slug !== initialSlug && bySlug.has(initialSlug)) {
      const selectedEntry = queueState.items.slice(queueState.currentIndex + 1)
        .find(item => item.slug === initialSlug) || bySlug.get(initialSlug);
      queueState = Queue.playNow(queueState, selectedEntry);
      currentSong = queueState.items[queueState.currentIndex];
      persistQueue();
    }
    if (!queueState && initialSlug && bySlug.has(initialSlug)) {
      queueState = Queue.standalone(bySlug.get(initialSlug), newSessionId());
      currentSong = queueState.items[0];
    }
    if (queueState) {
      persistQueue();
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

  document.addEventListener("bhakti:add-to-queue", event => addSongToPlaylist(event.detail.song, event.detail.position));
  document.addEventListener("bhakti:shuffle-request", event => {
    const songs = event.detail?.songs || [];
    if (!songs.length) return;
    const next = runShuffle(Queue.shuffle, songs, Math.random, newSessionId());
    setQueueState(next);
    selectAudioSong(currentSong, { force: true });
    attemptPlay();
    void showSong(currentSong.slug);
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
  queuePill.addEventListener("click", async () => {
    if (!queueSheet.hidden) {
      closeQueue();
      return;
    }
    if (view === "library" && currentSong) {
      await showSong(currentSong.slug);
      if (view !== "song") return;
    }
    openQueue();
  });
  repeatButton.addEventListener("click", () => {
    if (!queueState) return;
    setQueueState(Queue.cycleRepeat(queueState));
    showStatus({ off: "Repeat off", one: "Repeating this song", all: "Repeating playlist" }[queueState.repeat]);
  });
  document.addEventListener("click", event => {
    if (queueSheet.hidden || queueSheet.contains(event.target) || player.contains(event.target)) return;
    if (matchMedia("(min-width: 1101px)").matches) return;
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
    if (action === "queue-play") {
      if (playback.isPlaying() || playback.isPending()) playback.pause();
      else attemptPlay();
    }
    else if (action === "next") advanceQueue();
    else if (action === "history") {
      setQueueState(Queue.selectHistory(queueState, index));
      revealCurrentQueueRow();
      selectAudioSong(currentSong, { autoplay: true, force: true });
      if (currentSong && view === "song") void showSong(currentSong.slug, { historyMode: "replace" });
    }
    else if (action === "previous") previousQueue();
    else if (action === "remove") setQueueState(Queue.remove(queueState, index));
    else if (action === "play") {
      setQueueState(Queue.playNow(queueState, queueState.items[index]));
      revealCurrentQueueRow();
      selectAudioSong(currentSong, { autoplay: true, force: true });
      if (currentSong) void showSong(currentSong.slug, { historyMode: "replace" });
    } else if (action === "shuffle") {
      setQueueState(runShuffle(Queue.shuffleRemaining, queueState, Math.random));
      if (view === "library" && currentSong) void showSong(currentSong.slug, { historyMode: "replace" });
    }
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
  });
  queueSheet.addEventListener("keydown", event => {
    const handle = event.target.closest?.("[data-queue-drag]");
    if (!handle || (event.key !== "Delete" && event.key !== "Backspace")) return;
    event.preventDefault();
    const row = handle.closest("[data-queue-index]");
    setQueueState(Queue.remove(queueState, Number(row.dataset.queueIndex)));
  });
  const clearDragHold = () => {
    clearTimeout(dragHoldTimer);
    dragHoldTimer = 0;
    clearTimeout(dragPressTimer);
    dragPressTimer = 0;
  };
  const resetDragGesture = () => {
    if (dragMoveFrame) cancelAnimationFrame(dragMoveFrame);
    dragMoveFrame = 0;
    pendingDragPoint = null;
    const row = draggedRow;
    const pointerId = dragPointerId;
    clearDragHold();
    row?.classList.remove("is-pressing", "is-dragging");
    row?.style.removeProperty("--queue-drag-y");
    draggedRow = null;
    dragPointerId = null;
    dragTouchId = null;
    dragInputType = "";
    dragStartX = 0;
    dragStartY = 0;
    dragGrabOffsetY = 0;
    dragVisualY = 0;
    dragActive = false;
    dragMoved = false;
    if (pointerId !== null && queueSheet.hasPointerCapture?.(pointerId)) queueSheet.releasePointerCapture(pointerId);
  };
  const activateDrag = () => {
    clearDragHold();
    if (!draggedRow?.isConnected) {
      resetDragGesture();
      return;
    }
    if (dragPointerId !== null) {
      try {
        queueSheet.setPointerCapture(dragPointerId);
      } catch {
        resetDragGesture();
        return;
      }
    }
    dragActive = true;
    draggedRow.classList.remove("is-pressing");
    draggedRow.classList.add("is-dragging");
    pulseDragHaptic(18);
  };
  const positionDraggedRow = clientY => {
    const rect = draggedRow.getBoundingClientRect();
    const layoutTop = rect.top - dragVisualY;
    const desiredTop = clientY - dragGrabOffsetY;
    dragVisualY = desiredTop - layoutTop;
    draggedRow.style.setProperty("--queue-drag-y", `${dragVisualY}px`);
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
    positionDraggedRow(clientY);
    const target = document.elementFromPoint(clientX, clientY)?.closest(".queue-row.is-upcoming");
    if (!target || target === draggedRow || target.parentElement !== draggedRow.parentElement) return;
    const targetRect = target.getBoundingClientRect();
    const before = clientY < targetRect.top + targetRect.height / 2;
    const alreadyPlaced = before
      ? draggedRow.nextElementSibling === target
      : target.nextElementSibling === draggedRow;
    if (alreadyPlaced) return;
    const beforeRects = new Map();
    for (const row of visibleQueueRows) {
      if (row !== draggedRow && row.parentElement === list) beforeRects.set(row, row.getBoundingClientRect());
    }
    // The hit-tested row is visible even if the observer has not delivered yet.
    beforeRects.set(target, targetRect);
    target.parentElement.insertBefore(draggedRow, before ? target : target.nextSibling);
    animateQueueReorder(list, beforeRects);
    positionDraggedRow(clientY);
    pulseDragHaptic(8);
    dragMoved = true;
  };
  const flushDragMove = () => {
    if (dragMoveFrame) cancelAnimationFrame(dragMoveFrame);
    dragMoveFrame = 0;
    const point = pendingDragPoint;
    pendingDragPoint = null;
    if (point && draggedRow && dragActive) moveDraggedRow(point.x, point.y);
  };
  const scheduleDragMove = (x, y) => {
    pendingDragPoint = { x, y };
    if (!dragMoveFrame) dragMoveFrame = requestAnimationFrame(flushDragMove);
  };
  const startDragGesture = ({ row, inputType, pointerId = null, touchId = null, clientX, clientY }) => {
    draggedRow = row;
    dragPointerId = pointerId;
    dragTouchId = touchId;
    dragInputType = inputType;
    dragStartX = clientX;
    dragStartY = clientY;
    dragGrabOffsetY = clientY - row.getBoundingClientRect().top;
    dragVisualY = 0;
    dragActive = false;
    dragMoved = false;
  };
  const dragTargetRow = target => {
    const row = target.closest?.(".queue-row.is-upcoming");
    if (!row || target.closest("[data-queue-action]")) return null;
    return row;
  };
  const scheduleDragFeedback = () => {
    dragPressTimer = setTimeout(() => {
      if (draggedRow?.isConnected && !dragActive) draggedRow.classList.add("is-pressing");
    }, 90);
  };
  queueSheet.addEventListener("pointerdown", event => {
    if (event.pointerType === "touch" || draggedRow) return;
    const row = dragTargetRow(event.target);
    if (!row) return;
    startDragGesture({
      row,
      inputType: event.pointerType,
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
    });
    if (event.pointerType === "mouse") activateDrag();
    else {
      scheduleDragFeedback();
      dragHoldTimer = setTimeout(activateDrag, TOUCH_DRAG_HOLD_MS);
    }
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
    scheduleDragMove(event.clientX, event.clientY);
  });
  const touchById = touches => Array.from(touches)
    .find(touch => touch.identifier === dragTouchId);
  queueSheet.addEventListener("touchstart", event => {
    if (draggedRow || event.touches.length !== 1) return;
    const row = dragTargetRow(event.target);
    const touch = event.changedTouches[0];
    if (!row || !touch) return;
    startDragGesture({
      row,
      inputType: "touch",
      touchId: touch.identifier,
      clientX: touch.clientX,
      clientY: touch.clientY,
    });
    scheduleDragFeedback();
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
    scheduleDragMove(touch.clientX, touch.clientY);
  }, { passive: false });
  const finishDragGesture = () => {
    // Pointer-up may arrive before the scheduled frame; commit its final move.
    flushDragMove();
    const moved = dragMoved;
    const suppressAction = dragActive;
    const orderedEntryIds = [...queueSheet.querySelectorAll(".queue-row.is-upcoming")]
      .map(row => row.dataset.queueEntryId);
    resetDragGesture();
    if (suppressAction) {
      suppressQueueRowAction = true;
      setTimeout(() => { suppressQueueRowAction = false; }, 0);
    }
    if (moved) {
      setQueueState(Queue.reorderUpcoming(queueState, orderedEntryIds));
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
    if (dragActive && queueSheet.hasPointerCapture?.(dragPointerId)) return;
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
  audio.addEventListener("bhakti:playback-state", updateQueuePlayback);
  audio.addEventListener("ended", () => advanceQueue({ reason: "ended" }));
  audio.addEventListener("bhakti:playback-problem", event => {
    event.preventDefault();
    showStatus(event.detail.message);
    if (event.detail.advance && audio.dataset.songSlug) advanceQueue({ reason: "failed" });
  });
  audio.addEventListener("playing", () => {
    if (!queueState && audio.dataset.songSlug && bySlug.has(audio.dataset.songSlug)) {
      setQueueState(Queue.standalone(bySlug.get(audio.dataset.songSlug), newSessionId()));
    } else if (queueState) {
      persistQueue();
    }
    if (view === "library" && currentSong) void showSong(currentSong.slug);
  });
  window.addEventListener("popstate", () => {
    const slug = pathSlug();
    if (slug) showSong(slug, { historyMode: "none" });
    else showLibrary({ historyMode: "none" });
  });
  window.addEventListener("resize", setPlayerHeight, { passive: true });

  initializeState();
  window.BHAKTI_READER.setVisible(view === "song");
  import(assetPath("/assets/owner-entry.js")).catch(error => console.warn("Owner entry could not be initialized", error));
  import(assetPath("/assets/visit.js")).catch(() => {});
  if ("mediaSession" in navigator) {
    import(assetPath("/assets/media-session.js")).then(({ attach }) => {
      systemMedia = attach({
        audio,
        playback,
        getSong: () => currentSong,
        canPrevious: () => Boolean(queueState && queueState.currentIndex > 0),
        canNext: () => Boolean(queueState && (queueState.repeat === "all"
          || queueState.currentIndex + 1 < queueState.items.length)),
        previous: previousQueue,
        next: () => advanceQueue(),
      });
    }).catch(error => console.warn("System media controls could not be initialized", error));
  }
  window.BHAKTI_APP = Object.freeze({
    showLibrary,
    showSong,
    getQueue: () => queueState,
  });
})();
