(() => {
  "use strict";

  const IAST_TO_COMMON = {
    ā: "a", ī: "i", ū: "u", ṛ: "r", ṝ: "r", ḷ: "l", ḹ: "l",
    ṅ: "ng", ñ: "ny", ṇ: "n", ṃ: "m", ṁ: "m", ḥ: "h",
    ś: "sh", ṣ: "sh", ṭ: "t", ḍ: "d", ḻ: "l",
    Ā: "A", Ī: "I", Ū: "U", Ṛ: "R", Ṝ: "R", Ḷ: "L", Ḹ: "L",
    Ṅ: "Ng", Ñ: "Ny", Ṇ: "N", Ṃ: "M", Ṁ: "M", Ḥ: "H",
    Ś: "Sh", Ṣ: "Sh", Ṭ: "T", Ḍ: "D", Ḻ: "L",
  };

  const searchKey = value => String(value || "")
    .toLocaleLowerCase()
    .replace(/[’‘`]/g, "'")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");

  const searchForms = value => {
    const source = String(value || "");
    const common = [...source].map(character => IAST_TO_COMMON[character] || character).join("")
      .replace(/ngg/g, "ng").replace(/Ngg/g, "Ng");
    const unaccented = source.normalize("NFKD").replace(/\p{M}/gu, "");
    return [...new Set([searchKey(source), searchKey(common), searchKey(unaccented)].filter(Boolean))];
  };

  const searchableValues = song => [
    song.slug,
    song.title,
    song.subtitle,
    song.credit,
    song.singer,
    song.writer,
    ...(song.searchAliases || []),
    ...(song.languageTags || []),
    ...(song.subjectTags || []),
  ].filter(Boolean);

  const sortKey = value => searchKey(value).normalize("NFKD").replace(/\p{M}/gu, "");
  const singerSort = song => song.singer || song.writer || song.credit || song.title || song.slug;
  const tagSort = values => (values || []).join(" ");
  const sortSongs = list => [...list].sort((left, right) =>
    sortKey(singerSort(left)).localeCompare(sortKey(singerSort(right)))
    || sortKey(tagSort(left.subjectTags)).localeCompare(sortKey(tagSort(right.subjectTags)))
    || sortKey(tagSort(left.languageTags)).localeCompare(sortKey(tagSort(right.languageTags)))
    || sortKey(left.title).localeCompare(sortKey(right.title))
    || sortKey(left.slug).localeCompare(sortKey(right.slug))
  );

  const matchesSearch = (song, query) => {
    const queryForms = searchForms(query);
    if (!queryForms.length) return true;
    const songForms = searchableValues(song).flatMap(searchForms);
    return queryForms.some(queryForm => songForms.some(songForm => songForm.includes(queryForm)));
  };

  // Split explicit joint credits only; retain each credited spelling as supplied.
  const poetsFor = song => typeof song.writer === "string" ? song.writer
    .split(/\s*(?:·|;|&|,|\band\b)\s*/iu)
    .map(name => name.trim())
    .filter(name => name && !/^(?:others?|other poets|traditional)$/i.test(name)) : [];

  const filterSongs = (songs, { languages = [], subjects = [], poets = [], singers = [], query = "" } = {}) => {
    const selectedLanguages = new Set(languages);
    const selectedSubjects = new Set(subjects);
    const selectedSingers = new Set(singers);
    const selectedPoets = new Set(poets);
    return songs.filter(song => {
      const matchesLanguage = !selectedLanguages.size
        || [...selectedLanguages].some(tag => song.languageTags.includes(tag));
      const matchesSubject = !selectedSubjects.size
        || [...selectedSubjects].some(tag => song.subjectTags.includes(tag));
      const matchesSinger = !selectedSingers.size || selectedSingers.has(song.singer);
      const matchesPoet = !selectedPoets.size || poetsFor(song).some(poet => selectedPoets.has(poet));
      return matchesLanguage && matchesSubject && matchesPoet && matchesSinger && matchesSearch(song, query);
    });
  };

  const escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const controllers = new WeakMap();

  const wireAbout = root => {
    const toggle = root.querySelector("#aboutToggle");
    const panel = root.querySelector("#aboutPanel");
    const close = root.querySelector("#aboutClose");
    if (!toggle || !panel || !close) return;
    const setOpen = open => {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) document.dispatchEvent(new Event("bhakti:clear-preface"));
      (open ? close : toggle).focus();
    };
    toggle.addEventListener("click", event => {
      event.stopPropagation();
      setOpen(panel.hidden);
    });
    close.addEventListener("click", () => setOpen(false));
    panel.addEventListener("click", event => event.stopPropagation());
    document.addEventListener("click", () => {
      if (!panel.hidden) setOpen(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !panel.hidden) setOpen(false);
    });
  };

  const wirePreface = root => {
    const preface = root.querySelector(".library-intro");
    const tooltip = root.querySelector("#prefaceTooltip");
    if (!preface || !tooltip) return;
    let sticky = null;
    const indicesFor = token => new Set(token.dataset.wordI.split(/\s+/).filter(Boolean));
    const linkedTokens = token => {
      const selected = indicesFor(token);
      return [...preface.querySelectorAll(".preface-token")].filter(candidate =>
        [...indicesFor(candidate)].some(index => selected.has(index))
      );
    };
    const glossFor = token => {
      const selected = indicesFor(token);
      return [...new Set([...preface.querySelectorAll(".preface-word")]
        .filter(word => selected.has(word.dataset.wordI))
        .map(word => word.dataset.gloss)
        .filter(Boolean))].join(" · ");
    };
    const show = token => {
      preface.querySelectorAll(".preface-token.is-hi").forEach(candidate => candidate.classList.remove("is-hi"));
      linkedTokens(token).forEach(candidate => candidate.classList.add("is-hi"));
      tooltip.textContent = glossFor(token);
      tooltip.hidden = false;
      const rect = token.getBoundingClientRect();
      const tipRect = tooltip.getBoundingClientRect();
      const margin = 8;
      const left = Math.max(margin, Math.min(
        window.innerWidth - tipRect.width - margin,
        rect.left + rect.width / 2 - tipRect.width / 2,
      ));
      const above = rect.top - tipRect.height - 8;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${above >= margin ? above : rect.bottom + 8}px`;
    };
    const hide = () => {
      preface.querySelectorAll(".preface-token.is-hi").forEach(candidate => candidate.classList.remove("is-hi"));
      tooltip.hidden = true;
    };
    preface.addEventListener("pointerover", event => {
      const token = event.target.closest(".preface-token");
      if (token) show(token);
    });
    preface.addEventListener("pointerout", event => {
      const token = event.target.closest(".preface-token");
      if (token && token !== sticky && !token.contains(event.relatedTarget)) hide();
    });
    preface.addEventListener("focusin", event => {
      const token = event.target.closest(".preface-token");
      if (token) show(token);
    });
    preface.addEventListener("focusout", event => {
      const token = event.target.closest(".preface-token");
      if (token && token !== sticky) hide();
    });
    preface.addEventListener("click", event => {
      const token = event.target.closest(".preface-token");
      if (!token) return;
      event.stopPropagation();
      if (sticky === token) {
        sticky = null;
        hide();
        return;
      }
      if (sticky) hide();
      sticky = token;
      show(token);
    });
    preface.addEventListener("keydown", event => {
      const token = event.target.closest(".preface-token");
      if (token && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        token.click();
      }
    });
    document.addEventListener("click", event => {
      if (event.target.closest?.(".preface-token")) return;
      if (sticky) hide();
      sticky = null;
    });
    document.addEventListener("bhakti:clear-preface", () => {
      if (sticky) hide();
      sticky = null;
      tooltip.hidden = true;
    });
    window.addEventListener("scroll", () => { tooltip.hidden = true; }, { passive: true });
  };

  const mount = (root = document) => {
    if (controllers.has(root)) return controllers.get(root);
    const listRoot = root.querySelector?.("#songList");
    const filters = root.querySelector?.("#tagFilters");
    const search = root.querySelector?.("#songSearch");
    if (!listRoot || !filters || !search) return null;

    const songs = window.BHAKTI_SONGS || [];
    const selectedLanguages = new Set();
    const selectedSubjects = new Set();
    const selectedSingers = new Set();
    const selectedPoets = new Set();
    const languages = [...new Set(songs.flatMap(song => song.languageTags || []).sort())];
    const subjects = [...new Set(songs.flatMap(song => song.subjectTags || []).sort())];
    const singers = [...new Set(songs.map(song => song.singer).filter(singer => typeof singer === "string" && singer.trim()))]
      .sort((left, right) => sortKey(left).localeCompare(sortKey(right)));
    const poets = [...new Set(songs.flatMap(poetsFor))]
      .sort((left, right) => sortKey(left).localeCompare(sortKey(right)));
    const orderedSongs = sortSongs(songs);
    const shuffleButton = root.querySelector("#shuffleVisible");
    const filterToggle = root.querySelector("#filterToggle");
    const filterCount = root.querySelector("#filterCount");
    const aboutHeading = root.querySelector("#aboutHeading");
    if (aboutHeading) aboutHeading.textContent = `About these ${songs.length} songs`;

    let visibleSongs = [];
    const filterButton = (tag, kind, selected, label = tag) => `<button type="button" class="tag-filter" aria-pressed="${selected}" data-kind="${kind}" data-tag="${escapeHtml(tag)}">${escapeHtml(label)}</button>`;
    const facets = [
      { kind: "subject", all: "all-subjects", label: "Subjects", tags: subjects, selected: selectedSubjects },
      { kind: "language", all: "all-languages", label: "Languages", tags: languages, selected: selectedLanguages },
      { kind: "poet", all: "all-poets", label: "Poets", tags: poets, selected: selectedPoets },
      { kind: "singer", all: "all-singers", label: "Singers", tags: singers, selected: selectedSingers },
    ];
    // Keep the actual controls mounted: replacing a scrolled row moves another
    // tag underneath the finger and discards keyboard focus after selection.
    filters.innerHTML = facets.map(facet => `
      <div class="tag-row" role="group" aria-label="${facet.label}">${filterButton("All", facet.all, true, `All ${facet.label.toLowerCase()}`)}${facet.tags.map(tag => filterButton(tag, facet.kind, false)).join("")}</div>`).join("");

    const render = () => {
      const query = search.value.trim();
      visibleSongs = filterSongs(orderedSongs, {
        languages: selectedLanguages,
        subjects: selectedSubjects,
        singers: selectedSingers,
        poets: selectedPoets,
        query,
      });

      filters.querySelectorAll(".tag-filter").forEach(button => {
        const facet = facets.find(item => item.kind === button.dataset.kind || item.all === button.dataset.kind);
        const pressed = button.dataset.kind === facet.all ? !facet.selected.size : facet.selected.has(button.dataset.tag);
        button.setAttribute("aria-pressed", String(pressed));
      });
      const selections = facets.flatMap(facet => [...facet.selected]);
      if (filterCount) {
        filterCount.textContent = String(selections.length);
        filterCount.hidden = !selections.length;
      }
      if (filterToggle) filterToggle.title = selections.length
        ? `Filters: ${selections.join(" · ")}` : "Filter by subject, language, poet or singer";
      closeQueueChoices();

      listRoot.innerHTML = visibleSongs.map(song => `
        <article class="song-card" data-song-slug="${escapeHtml(song.slug)}">
          <a class="song-card-link" href="/songs/${encodeURIComponent(song.slug)}/" aria-label="Open ${escapeHtml(song.title)}">
            <span class="song-copy">
              <span class="library-song-title">${escapeHtml(song.title)}</span>
              ${song.singer || song.credit ? `<span class="credit">${escapeHtml(song.singer || song.credit)}</span>` : ""}
            </span>
            <span class="tags" aria-label="${escapeHtml([...(song.subjectTags || []), ...(song.languageTags || [])].join(", "))}">
              ${(song.subjectTags || []).map(tag => `<span class="subject-tag">${escapeHtml(tag)}</span>`).join("")}
              ${(song.languageTags || []).map(tag => `<span class="language-tag">${escapeHtml(tag)}</span>`).join("")}
            </span>
          </a>
          <button class="song-actions-trigger" type="button" data-queue-choices="${escapeHtml(song.slug)}" aria-haspopup="menu" aria-expanded="false" aria-controls="queue-choices-${escapeHtml(song.slug)}" aria-label="Playlist options for ${escapeHtml(song.title)}" title="Playlist options">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
          </button>
          <div class="song-queue-actions" role="menu" aria-label="Playlist options for ${escapeHtml(song.title)}" id="queue-choices-${escapeHtml(song.slug)}" hidden>
            <button class="song-queue-choice" role="menuitem" tabindex="-1" type="button" data-add-to-queue="${escapeHtml(song.slug)}" data-queue-position="next"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 5 10 7-10 7zM19 5v14"/></svg>Play next</button>
            <button class="song-queue-choice" role="menuitem" tabindex="-1" type="button" data-add-to-queue="${escapeHtml(song.slug)}" data-queue-position="end"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 11h12M4 16h7M17 14v7M13.5 17.5h7"/></svg>Add to end</button>
          </div>
        </article>`).join("") || '<p class="library-empty">No songs match. Try changing your search or filters.</p>';

      if (shuffleButton) {
        shuffleButton.disabled = !visibleSongs.length;
        shuffleButton.setAttribute("aria-label", visibleSongs.length
          ? `Shuffle ${visibleSongs.length} visible songs`
          : "No visible songs to shuffle");
        shuffleButton.title = visibleSongs.length
          ? `Shuffle ${visibleSongs.length} visible songs`
          : "No visible songs to shuffle";
      }
      root.dispatchEvent(new CustomEvent("bhakti:visible-songs", {
        bubbles: true,
        detail: { songs: [...visibleSongs] },
      }));
    };

    filters.addEventListener("click", event => {
      const button = event.target.closest(".tag-filter");
      if (!button) return;
      const { kind, tag } = button.dataset;
      const facet = facets.find(item => item.kind === kind || item.all === kind);
      if (!facet) return;
      if (kind === facet.all) facet.selected.clear();
      else facet.selected.has(tag) ? facet.selected.delete(tag) : facet.selected.add(tag);
      render();
    });
    search.addEventListener("input", render);
    filterToggle?.addEventListener("click", () => {
      filters.hidden = !filters.hidden;
      filterToggle.setAttribute("aria-expanded", String(!filters.hidden));
    });
    shuffleButton?.addEventListener("click", () => root.dispatchEvent(new CustomEvent("bhakti:shuffle-request", {
      bubbles: true,
      detail: { songs: [...visibleSongs] },
    })));
    const closeQueueChoices = ({ returnFocus = false } = {}) => {
      const trigger = listRoot.querySelector('[data-queue-choices][aria-expanded="true"]');
      if (!trigger) return;
      trigger.setAttribute("aria-expanded", "false");
      const menu = trigger.closest(".song-card").querySelector(".song-queue-actions");
      const restoreFocus = returnFocus || menu.contains(document.activeElement);
      menu.hidden = true;
      if (restoreFocus) trigger.focus({preventScroll: true});
    };
    const openQueueChoices = (trigger, last = false) => {
      closeQueueChoices();
      const menu = trigger.closest(".song-card").querySelector(".song-queue-actions");
      trigger.setAttribute("aria-expanded", "true");
      menu.hidden = false;
      const anchor = trigger.getBoundingClientRect();
      const box = menu.getBoundingClientRect();
      const player = document.getElementById("audioPlayer");
      const bottom = player && !player.hidden ? player.getBoundingClientRect().top : window.innerHeight;
      menu.style.left = `${Math.max(8, Math.min(anchor.right - box.width, window.innerWidth - box.width - 8))}px`;
      const top = anchor.bottom + box.height + 6 <= bottom - 8 ? anchor.bottom + 6 : anchor.top - box.height - 6;
      menu.style.top = `${Math.max(8, Math.min(top, bottom - box.height - 8))}px`;
      const choices = menu.querySelectorAll("[role=menuitem]");
      choices[last ? choices.length - 1 : 0].focus({preventScroll: true});
    };
    listRoot.addEventListener("click", event => {
      const trigger = event.target.closest("[data-queue-choices]");
      if (trigger) {
        const wasOpen = trigger.getAttribute("aria-expanded") === "true";
        closeQueueChoices();
        if (!wasOpen) openQueueChoices(trigger);
        return;
      }
      const button = event.target.closest("[data-add-to-queue]");
      if (!button) return;
      const selected = songs.find(song => song.slug === button.dataset.addToQueue);
      if (!selected) return;
      closeQueueChoices({ returnFocus: true });
      root.dispatchEvent(new CustomEvent("bhakti:add-to-queue", {
        bubbles: true,
        detail: { song: selected, position: button.dataset.queuePosition },
      }));
    });
    listRoot.addEventListener("keydown", event => {
      const trigger = event.target.closest("[data-queue-choices]");
      if (trigger && ["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        openQueueChoices(trigger, event.key === "ArrowUp");
        return;
      }
      const menu = event.target.closest(".song-queue-actions");
      if (menu && ["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const choices = [...menu.querySelectorAll("[role=menuitem]")];
        const index = choices.indexOf(event.target);
        const next = event.key === "Home" ? 0 : event.key === "End" ? choices.length - 1
          : (index + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length;
        choices[next].focus();
      }
      if (menu && event.key === "Tab") closeQueueChoices({returnFocus: true});
      if (event.key === "Escape" && event.target.closest(".song-card")) {
        event.preventDefault?.();
        closeQueueChoices({ returnFocus: true });
      }
    });
    const dismissOutside = event => {
      if (!event.target.closest?.(".song-queue-actions, [data-queue-choices]")) closeQueueChoices();
    };
    document.addEventListener("click", dismissOutside);
    document.addEventListener("focusin", dismissOutside);
    window.addEventListener("scroll", () => closeQueueChoices(), {capture: true, passive: true});
    window.addEventListener("resize", () => closeQueueChoices());
    window.addEventListener("popstate", () => closeQueueChoices());
    window.addEventListener("bhakti:song-change", () => closeQueueChoices());

    wireAbout(root);
    wirePreface(root);
    const controller = Object.freeze({
      render,
      getVisibleSongs: () => [...visibleSongs],
    });
    controllers.set(root, controller);
    render();
    return controller;
  };

  window.BHAKTI_SEARCH = Object.freeze({ searchForms, matchesSearch, filterSongs });
  window.BHAKTI_LIBRARY = Object.freeze({ mount });

  const autoMount = () => {
    if (typeof document.querySelector === "function") mount(document.querySelector("main") || document);
  };
  if (typeof document.addEventListener === "function") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoMount, { once: true });
    else autoMount();
  }
})();
