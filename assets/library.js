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

  const filterSongs = (songs, { languages = [], subjects = [], query = "" } = {}) => {
    const selectedLanguages = new Set(languages);
    const selectedSubjects = new Set(subjects);
    return songs.filter(song => {
      const matchesLanguage = !selectedLanguages.size
        || [...selectedLanguages].some(tag => song.languageTags.includes(tag));
      const matchesSubject = !selectedSubjects.size
        || [...selectedSubjects].some(tag => song.subjectTags.includes(tag));
      return matchesLanguage && matchesSubject && matchesSearch(song, query);
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
    const languages = [...new Set(songs.flatMap(song => song.languageTags || []).sort())];
    const subjects = [...new Set(songs.flatMap(song => song.subjectTags || []).sort())];
    const orderedSongs = sortSongs(songs);
    const shuffleButton = root.querySelector("#shuffleVisible");
    const aboutHeading = root.querySelector("#aboutHeading");
    if (aboutHeading) aboutHeading.textContent = `About these ${songs.length} songs`;

    let visibleSongs = [];
    const filterButton = (tag, kind, selected) => `<button type="button" class="tag-filter" aria-pressed="${selected}" data-kind="${kind}" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`;

    const render = () => {
      const query = search.value.trim();
      visibleSongs = filterSongs(orderedSongs, {
        languages: selectedLanguages,
        subjects: selectedSubjects,
        query,
      });

      filters.innerHTML = `
        <div class="tag-row">${filterButton("All", "all-subjects", !selectedSubjects.size)}${subjects.map(tag => filterButton(tag, "subject", selectedSubjects.has(tag))).join("")}</div>
        <div class="tag-row">${filterButton("All", "all-languages", !selectedLanguages.size)}${languages.map(tag => filterButton(tag, "language", selectedLanguages.has(tag))).join("")}</div>`;

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
          <button class="song-actions-trigger" type="button" data-add-to-queue="${escapeHtml(song.slug)}" aria-label="Add ${escapeHtml(song.title)} to playlist" title="Add to playlist">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4 7h10M4 12h8M4 17h6M18 11v8M14 15h8"/></svg>
          </button>
        </article>`).join("");

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
      if (kind === "all-subjects") selectedSubjects.clear();
      else if (kind === "all-languages") selectedLanguages.clear();
      else {
        const selected = kind === "language" ? selectedLanguages : selectedSubjects;
        selected.has(tag) ? selected.delete(tag) : selected.add(tag);
      }
      render();
    });
    search.addEventListener("input", render);
    shuffleButton?.addEventListener("click", () => root.dispatchEvent(new CustomEvent("bhakti:shuffle-request", {
      bubbles: true,
      detail: { songs: [...visibleSongs] },
    })));
    listRoot.addEventListener("click", event => {
      const button = event.target.closest("[data-add-to-queue]");
      if (!button) return;
      const selected = songs.find(song => song.slug === button.dataset.addToQueue);
      if (!selected) return;
      root.dispatchEvent(new CustomEvent("bhakti:add-to-queue", {
        bubbles: true,
        detail: { song: selected },
      }));
    });

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
