(() => {
  const IAST_TO_COMMON = {
    ā: "a", ī: "i", ū: "u", ṛ: "r", ṝ: "r", ḷ: "l", ḹ: "l",
    ṅ: "ng", ñ: "ny", ṇ: "n", ṃ: "m", ṁ: "m", ḥ: "h",
    ś: "sh", ṣ: "sh", ṭ: "t", ḍ: "d", ḻ: "l",
    Ā: "A", Ī: "I", Ū: "U", Ṛ: "R", Ṝ: "R", Ḷ: "L", Ḹ: "L",
    Ṅ: "Ng", Ñ: "Ny", Ṇ: "N", Ṃ: "M", Ṁ: "M", Ḥ: "H",
    Ś: "Sh", Ṣ: "Sh", Ṭ: "T", Ḍ: "D", Ḻ: "L"
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
    ...(song.subjectTags || [])
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

  const wireAbout = () => {
    const toggle = document.getElementById("aboutToggle");
    const panel = document.getElementById("aboutPanel");
    const close = document.getElementById("aboutClose");
    if (!toggle || !panel || !close) return;
    const setOpen = open => {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) document.dispatchEvent(new Event("bhakti:clear-preface"));
      if (open) close.focus();
      else toggle.focus();
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

  const wirePreface = () => {
    if (typeof document.querySelector !== "function") return;
    const root = document.querySelector(".library-intro");
    const tooltip = document.getElementById("prefaceTooltip");
    if (!root || !tooltip) return;
    let sticky = null;
    const indicesFor = token => new Set(token.dataset.wordI.split(/\s+/).filter(Boolean));
    const linkedTokens = token => {
      const selected = indicesFor(token);
      return [...root.querySelectorAll(".preface-token")].filter(candidate =>
        [...indicesFor(candidate)].some(index => selected.has(index))
      );
    };
    const glossFor = token => {
      const selected = indicesFor(token);
      return [...new Set([...root.querySelectorAll(".preface-word")]
        .filter(word => selected.has(word.dataset.wordI))
        .map(word => word.dataset.gloss)
        .filter(Boolean))].join(" · ");
    };
    const show = token => {
      root.querySelectorAll(".preface-token.is-hi").forEach(candidate => candidate.classList.remove("is-hi"));
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
      root.querySelectorAll(".preface-token.is-hi").forEach(candidate => candidate.classList.remove("is-hi"));
      tooltip.hidden = true;
    };
    root.addEventListener("pointerover", event => {
      const token = event.target.closest(".preface-token");
      if (token) show(token);
    });
    root.addEventListener("pointerout", event => {
      const token = event.target.closest(".preface-token");
      if (token && token !== sticky && !token.contains(event.relatedTarget)) hide();
    });
    root.addEventListener("focusin", event => {
      const token = event.target.closest(".preface-token");
      if (token) show(token);
    });
    root.addEventListener("focusout", event => {
      const token = event.target.closest(".preface-token");
      if (token && token !== sticky) hide();
    });
    root.addEventListener("click", event => {
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
    root.addEventListener("keydown", event => {
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

  // Kept public for deterministic Node tests and future non-DOM consumers.
  window.BHAKTI_SEARCH = Object.freeze({ searchForms, matchesSearch });

  wireAbout();
  wirePreface();

  const root = document.getElementById("songList");
  const filters = document.getElementById("tagFilters");
  const search = document.getElementById("songSearch");
  const songs = window.BHAKTI_SONGS || [];
  if (!root || !filters || !search) return;
  const selectedLanguages = new Set();
  const selectedSubjects = new Set();
  const languages = [...new Set(songs.flatMap(song => song.languageTags).sort())];
  const subjects = [...new Set(songs.flatMap(song => song.subjectTags).sort())];
  const button = (tag, kind, selected) => `<button type="button" class="tag-filter" aria-pressed="${selected}" data-kind="${kind}" data-tag="${tag}">${tag}</button>`;

  const orderedSongs = sortSongs(songs);

  const render = () => {
    const query = search.value.trim();
    const visibleSongs = orderedSongs.filter(song => {
      const matchesLanguage = !selectedLanguages.size || [...selectedLanguages].some(tag => song.languageTags.includes(tag));
      const matchesSubject = !selectedSubjects.size || [...selectedSubjects].some(tag => song.subjectTags.includes(tag));
      return matchesLanguage && matchesSubject && matchesSearch(song, query);
    });

    const nothingSelected = !selectedLanguages.size && !selectedSubjects.size;
    filters.innerHTML = `
      <div class="tag-row">${button("All", "all", nothingSelected)}${subjects.map(tag => button(tag, "subject", selectedSubjects.has(tag))).join("")}</div>
      <div class="tag-row">${languages.map(tag => button(tag, "language", selectedLanguages.has(tag))).join("")}</div>`;

    root.innerHTML = visibleSongs.map(song => `
    <a class="song-card" href="songs/${song.slug}/" aria-label="Open ${song.title}">
      <span class="song-copy">
        <span class="song-title">${song.title}</span>
        ${song.singer || song.credit ? `<span class="credit">${song.singer || song.credit}</span>` : ""}
      </span>
      <span class="tags" aria-label="${[...song.subjectTags, ...song.languageTags].join(", ")}">
        ${song.subjectTags.map(tag => `<span class="subject-tag">${tag}</span>`).join("")}
        ${song.languageTags.map(tag => `<span class="language-tag">${tag}</span>`).join("")}
      </span>
    </a>`).join("");
  };

  filters.addEventListener("click", event => {
    const button = event.target.closest(".tag-filter");
    if (!button) return;
    const { kind, tag } = button.dataset;
    if (kind === "all") {
      selectedLanguages.clear();
      selectedSubjects.clear();
    } else {
      const selected = kind === "language" ? selectedLanguages : selectedSubjects;
      selected.has(tag) ? selected.delete(tag) : selected.add(tag);
    }
    render();
  });

  search.addEventListener("input", render);

  render();
})();
