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
    .replace(/[^\p{L}\p{M}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");

  const searchForms = value => {
    const source = String(value || "");
    const common = [...source].map(character => IAST_TO_COMMON[character] || character).join("")
      .replace(/ngg/g, "ng").replace(/Ngg/g, "Ng")
      .replace(/\b(?:krshna|krsna|krisna)\b/gi, "krishna");
    const unaccented = source.normalize("NFKD").replace(/(\p{Script=Latin})\p{M}+/gu, "$1");
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

  // A loaded release owns immutable catalogue objects. Weak keys let a replaced
  // catalogue be collected without retaining another full set of search data.
  const songSearchForms = new WeakMap();
  const formsForSong = song => {
    if (!songSearchForms.has(song)) songSearchForms.set(song, searchableValues(song).flatMap(searchForms));
    return songSearchForms.get(song);
  };
  const matchesTerms = (song, queryTerms, lyricIndex = null) => {
    const songForms = formsForSong(song);
    const lyricForms = lyricIndex?.[song.slug] || [];
    return queryTerms.some(terms => terms.every(term =>
      songForms.some(songForm => songForm.includes(term)) || lyricForms.some(form => form.includes(term))
    ));
  };
  const matchesSearch = (song, query) => {
    const queryForms = searchForms(query);
    return !queryForms.length || matchesTerms(song, queryForms.map(form => form.split(" ")));
  };

  // Approximation is a last resort. These forms never change exact search or
  // the published index, and apply only to Latin spellings remembered by ear.
  const phoneticKey = token => token.replace(/aa+/g, "a").replace(/ee+/g, "i")
    .replace(/oo+/g, "u").replace(/ng(?=[kg])/g, "n")
    .replace(/^(.{4,})a$/, "$1");
  const editDistance = (left, right, limit) => {
    if (Math.abs(left.length - right.length) > limit) return limit + 1;
    if (limit === 1) {
      if (left === right) return 0;
      let i = 0;
      while (i < left.length && left[i] === right[i]) i++;
      if (left.length === right.length) {
        if (left.slice(i + 1) === right.slice(i + 1)) return 1;
        return left[i] === right[i + 1] && left[i + 1] === right[i]
          && left.slice(i + 2) === right.slice(i + 2) ? 1 : 2;
      }
      return left.length < right.length
        ? (left.slice(i) === right.slice(i + 1) ? 1 : 2)
        : (left.slice(i + 1) === right.slice(i) ? 1 : 2);
    }
    let previous = Array.from({ length: right.length + 1 }, (_, i) => i);
    let older = previous;
    for (let i = 1; i <= left.length; i++) {
      const row = [i];
      let minimum = i;
      for (let j = 1; j <= right.length; j++) {
        row[j] = Math.min(row[j - 1] + 1, previous[j] + 1,
          previous[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1));
        if (i > 1 && j > 1 && left[i - 1] === right[j - 2] && left[i - 2] === right[j - 1]) {
          row[j] = Math.min(row[j], older[j - 2] + 1);
        }
        minimum = Math.min(minimum, row[j]);
      }
      if (minimum > limit) return limit + 1;
      older = previous;
      previous = row;
    }
    return previous[right.length];
  };
  const fallbackCaches = new WeakMap();
  const fallbackIndex = (songs, lyrics) => {
    let caches = fallbackCaches.get(songs);
    if (!caches) { caches = { metadata: null, lyrics: new WeakMap() }; fallbackCaches.set(songs, caches); }
    let index = lyrics ? caches.lyrics.get(lyrics) : caches.metadata;
    if (index) return index;
    const vocabulary = new Map();
    const add = (forms, songIndex, field) => {
      const tokens = new Set(forms.flatMap(form => form.split(" ")));
      for (const token of tokens) {
        if (!/^[a-z0-9]+$/.test(token)) continue;
        let entry = vocabulary.get(token);
        if (!entry) {
          entry = { token, key: /^[a-z]+$/.test(token) ? phoneticKey(token) : null, metadata: [], lyrics: [] };
          vocabulary.set(token, entry);
        }
        entry[field].push(songIndex);
      }
    };
    songs.forEach((song, i) => {
      add(formsForSong(song), i, "metadata");
      if (lyrics) add(lyrics[song.slug] || [], i, "lyrics");
    });
    index = { vocabulary: [...vocabulary.values()], hits: new Map() };
    if (lyrics) caches.lyrics.set(lyrics, index); else caches.metadata = index;
    return index;
  };
  const fallbackSongs = (songs, queryTerms, lyrics) => {
    const index = fallbackIndex(songs, lyrics);
    const hitsFor = term => {
      if (index.hits.has(term)) return index.hits.get(term);
      const hits = { all: new Uint8Array(songs.length).fill(255), metadata: new Uint8Array(songs.length).fill(255) };
      const key = /^[a-z]+$/.test(term) ? phoneticKey(term) : null;
      // Native/diacritic terms in a mixed query remain exact. They need no
      // duplicate token index alongside the already-normalized field strings.
      if (!/^[a-z0-9]+$/.test(term)) {
        const startsWord = form => form.startsWith(term) || form.includes(" " + term);
        songs.forEach((song, i) => {
          if (formsForSong(song).some(startsWord)) hits.metadata[i] = hits.all[i] = 0;
          else if ((lyrics?.[song.slug] || []).some(startsWord)) hits.all[i] = 0;
        });
      }
      for (const entry of /^[a-z0-9]+$/.test(term) ? index.vocabulary : []) {
        let cost = term.length < 3 ? (entry.token === term ? 0 : 255) : (entry.token.startsWith(term) ? 0 : 255);
        if (cost && key && entry.key && term.length >= 3) {
          if (key === entry.key) cost = 1;
          else if (key.length >= 4 && entry.key.length >= 4 && key.length <= 48 && entry.key.length <= 48) {
            const limit = Math.min(key.length, entry.key.length) >= 8 ? 2 : 1;
            const distance = editDistance(key, entry.key, limit);
            if (distance <= limit) cost = distance + 1;
          }
        }
        if (cost === 255) continue;
        for (const i of entry.metadata) { hits.metadata[i] = Math.min(hits.metadata[i], cost); hits.all[i] = Math.min(hits.all[i], cost); }
        for (const i of entry.lyrics) hits.all[i] = Math.min(hits.all[i], cost);
      }
      if (index.hits.size >= 64) index.hits.delete(index.hits.keys().next().value);
      index.hits.set(term, hits);
      return hits;
    };
    const ranked = new Map();
    for (const terms of queryTerms) {
      const hits = terms.map(hitsFor);
      songs.forEach((song, i) => {
        if (hits.some(hit => hit.all[i] === 255)) return;
        const rank = { song, metadata: hits.every(hit => hit.metadata[i] !== 255), cost: hits.reduce((sum, hit) => sum + hit.all[i], 0) };
        const previous = ranked.get(i);
        if (!previous || rank.metadata > previous.metadata || (rank.metadata === previous.metadata && rank.cost < previous.cost)) ranked.set(i, rank);
      });
    }
    return [...ranked.values()].sort((a, b) => Number(b.metadata) - Number(a.metadata) || a.cost - b.cost).map(rank => rank.song);
  };
  const hasWordPrefixMatch = (song, queryTerms, lyrics) => {
    const forms = formsForSong(song).concat(lyrics?.[song.slug] || []);
    return queryTerms.some(terms => terms.every(term => forms.some(form => form.startsWith(term) || form.includes(" " + term))));
  };

  // Split explicit joint credits only; retain each credited spelling as supplied.
  const poetsFor = song => typeof song.writer === "string" ? song.writer
    .split(/\s*(?:·|;|&|,|\band\b)\s*/iu)
    .map(name => name.trim())
    .filter(name => name && !/^(?:others?|other poets|traditional)$/i.test(name)) : [];

  // A bare name does not say whether it is the poet or the singer.
  const creditLine = song => {
    const [writer, singer, ensemble] = [song.writer, song.singer, song.ensemble].map(name => String(name || "").trim());
    if (!writer && !singer && !ensemble) return String(song.credit || "").trim();
    if (writer && writer === singer) return `Written and sung by ${writer}`;
    const performed = singer ? `sung by ${singer}` : ensemble ? `sung at ${ensemble}` : "";
    return [writer && `By ${writer}`, writer ? performed : performed.replace(/^s/, "S")].filter(Boolean).join(" · ");
  };

  const filterSongs = (songs, { languages = [], subjects = [], poets = [], singers = [], query = "", lyricIndex = null } = {}) => {
    const selectedLanguages = new Set(languages);
    const selectedSubjects = new Set(subjects);
    const selectedSingers = new Set(singers);
    const selectedPoets = new Set(poets);
    const queryForms = searchForms(query);
    // Prefer a known title/name phrase across the full catalogue before applying
    // facets. Otherwise unrelated credits can accidentally assemble a person's
    // name, or changing a facet can turn an exact name into such a false match.
    const phraseMatches = queryForms.length ? songs.filter(song => {
      const songForms = formsForSong(song);
      return queryForms.some(queryForm => songForms.some(songForm => songForm.includes(queryForm)));
    }) : songs;
    const queryTerms = queryForms.map(form => form.split(" "));
    const phraseSlugs = new Set(phraseMatches.map(song => song.slug));
    // Exact title/name phrases retain priority. Lyrics can add genuine phrase
    // matches, but cannot manufacture a person's name from scattered words.
    const lyricMatches = queryForms.length ? songs.filter(song => !phraseSlugs.has(song.slug)
      && queryForms.some(queryForm => (lyricIndex?.[song.slug] || []).some(form => form.includes(queryForm)))) : [];
    let searchMatches = phraseMatches.length ? phraseMatches.concat(lyricMatches)
      : songs.filter(song => matchesTerms(song, queryTerms, lyricIndex));
    // Internal fragments such as hnad inside krshnadamodaram must not block a
    // remembered English "hand". Known metadata phrases remain authoritative.
    if (queryForms.length && !phraseMatches.length
        && !searchMatches.some(song => hasWordPrefixMatch(song, queryTerms, lyricIndex))) {
      const exact = new Set(searchMatches);
      searchMatches = searchMatches.concat(fallbackSongs(songs, queryTerms, lyricIndex).filter(song => !exact.has(song)));
    }
    return searchMatches.filter(song => {
      const matchesLanguage = !selectedLanguages.size
        || [...selectedLanguages].some(tag => song.languageTags.includes(tag));
      const matchesSubject = !selectedSubjects.size
        || [...selectedSubjects].some(tag => song.subjectTags.includes(tag));
      const matchesSinger = !selectedSingers.size || selectedSingers.has(song.singer);
      const matchesPoet = !selectedPoets.size || poetsFor(song).some(poet => selectedPoets.has(poet));
      return matchesLanguage && matchesSubject && matchesPoet && matchesSinger;
    });
  };

  const escapeHtml = value => String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  // A release has one deferred index. Failed requests retain metadata search;
  // a later input can retry. Strings have already been folded by assembly.
  const lyricSearch = { status: "idle", forms: null, pending: null };
  const loadLyrics = () => {
    if (lyricSearch.status === "ready") return Promise.resolve();
    if (lyricSearch.pending) return lyricSearch.pending;
    lyricSearch.status = "loading";
    const url = window.BHAKTI_ASSETS?.["/data/search-index.json"] || "/data/search-index.json";
    lyricSearch.pending = Promise.resolve().then(() => window.fetch(url)).then(response => {
      if (!response.ok) throw new Error("Lyric search unavailable");
      return response.json();
    }).then(index => {
      if (index?.schemaVersion !== 1 || !index.songs || typeof index.songs !== "object"
          || Array.isArray(index.songs) || !Object.values(index.songs).every(forms =>
            Array.isArray(forms) && forms.every(form => typeof form === "string"))
          || !(window.BHAKTI_SONGS || []).every(song => Object.hasOwn(index.songs, song.slug))) {
        throw new Error("Invalid lyric search index");
      }
      lyricSearch.forms = index.songs;
      lyricSearch.status = "ready";
    }).catch(() => { lyricSearch.status = "error"; })
      .finally(() => { lyricSearch.pending = null; });
    return lyricSearch.pending;
  };

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
      // Every scrolled frame of every scroller arrives here.
      if (!sticky && tooltip.hidden) return;
      sticky = null;
      preface.querySelectorAll(".preface-token.is-hi").forEach(candidate => candidate.classList.remove("is-hi"));
      tooltip.hidden = true;
    };
    preface.addEventListener("pointerover", event => {
      const token = event.target.closest(".preface-token");
      if (token && !sticky && event.pointerType !== "touch"
          && window.matchMedia?.("(hover: hover) and (pointer: fine)").matches) show(token);
    });
    preface.addEventListener("pointerout", event => {
      const token = event.target.closest(".preface-token");
      if (token && !sticky && !token.contains(event.relatedTarget)) hide();
    });
    preface.addEventListener("focusin", event => {
      const token = event.target.closest(".preface-token");
      if (token?.matches(":focus-visible")) {
        hide();
        show(token);
      }
    });
    preface.addEventListener("focusout", event => {
      const token = event.target.closest(".preface-token");
      if (token) hide();
    });
    preface.addEventListener("click", event => {
      const token = event.target.closest(".preface-token");
      if (!token) return;
      event.stopPropagation();
      if (sticky === token) {
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
      hide();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") hide();
    });
    document.addEventListener("bhakti:clear-preface", hide);
    window.addEventListener("scroll", hide, { capture: true, passive: true });
    window.addEventListener("resize", hide);
    window.addEventListener("popstate", hide);
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
    const filterButton = (tag, kind, selected, label = tag) => `<button type="button" class="tag-filter" aria-pressed="${selected}" data-kind="${kind}" data-tag="${escapeHtml(tag)}"><span>${escapeHtml(label)}</span></button>`;
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

    listRoot.innerHTML = orderedSongs.map(song => `
        <article class="song-card" data-song-slug="${escapeHtml(song.slug)}">
          <a class="song-card-link" href="/songs/${encodeURIComponent(song.slug)}/" aria-label="Open ${escapeHtml(song.title)}">
            <span class="song-copy">
              <span class="library-song-title">${escapeHtml(song.title)}</span>
              ${creditLine(song) ? `<span class="credit">${escapeHtml(creditLine(song))}</span>` : ""}
            </span>
            <span class="tags" aria-label="${escapeHtml([...(song.subjectTags || []), ...(song.languageTags || [])].join(", "))}">
              ${(song.subjectTags || []).map(tag => `<span class="subject-tag">${escapeHtml(tag)}</span>`).join("")}
              ${(song.languageTags || []).map(tag => `<span class="language-tag">${escapeHtml(tag)}</span>`).join("")}
            </span>
          </a>
          <button class="song-actions-trigger" type="button" data-queue-choices="${escapeHtml(song.slug)}" aria-haspopup="menu" aria-expanded="false" aria-controls="library-queue-choices" aria-label="Playlist options for ${escapeHtml(song.title)}" title="Playlist options">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
          </button>
        </article>`).join("") + `<p class="library-empty" hidden>No songs match. Try changing your search or filters.</p>
          <div class="song-queue-actions" role="menu" aria-label="Playlist options" id="library-queue-choices" hidden>
            <button class="song-queue-choice" role="menuitem" tabindex="-1" type="button" data-add-to-queue="" data-queue-position="next"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 5 10 7-10 7zM19 5v14"/></svg>Play next</button>
            <button class="song-queue-choice" role="menuitem" tabindex="-1" type="button" data-add-to-queue="" data-queue-position="end"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 11h12M4 16h7M17 14v7M13.5 17.5h7"/></svg>Add to end</button>
          </div>`;
    const cards = [...listRoot.querySelectorAll(".song-card")];
    const cardsBySlug = new Map(cards.map(card => [card.dataset.songSlug, card]));
    const emptyMessage = listRoot.querySelector(".library-empty");
    const queueMenu = listRoot.querySelector(".song-queue-actions");
    const queueChoices = [...queueMenu.querySelectorAll("[role=menuitem]")];
    let menuTrigger = null;
    // Index once on mount, before input starts; search never refolds the catalogue.
    orderedSongs.forEach(formsForSong);

    const render = () => {
      const query = search.value.trim();
      visibleSongs = filterSongs(orderedSongs, {
        languages: selectedLanguages,
        subjects: selectedSubjects,
        singers: selectedSingers,
        poets: selectedPoets,
        query,
        lyricIndex: lyricSearch.forms,
      });

      filters.querySelectorAll(".tag-filter").forEach(button => {
        const facet = facets.find(item => item.kind === button.dataset.kind || item.all === button.dataset.kind);
        const pressed = button.dataset.kind === facet.all ? !facet.selected.size : facet.selected.has(button.dataset.tag);
        if (button.getAttribute("aria-pressed") !== String(pressed)) button.setAttribute("aria-pressed", String(pressed));
      });
      const selections = facets.flatMap(facet => [...facet.selected]);
      if (filterCount) {
        filterCount.textContent = String(selections.length);
        filterCount.hidden = !selections.length;
      }
      if (filterToggle) filterToggle.title = selections.length
        ? `Filters: ${selections.join(" · ")}` : "Filter by subject, language, poet or singer";
      closeQueueChoices();

      const visibleSlugs = new Set(visibleSongs.map(song => song.slug));
      for (const card of cards) {
        const hidden = !visibleSlugs.has(card.dataset.songSlug);
        if (card.hidden !== hidden) card.hidden = hidden;
      }
      // Keep result order aligned with the search ranking without replacing
      // controls. Moving a focused row must not discard keyboard focus.
      const ranked = query ? visibleSongs.concat(orderedSongs.filter(song => !visibleSlugs.has(song.slug))) : orderedSongs;
      const focused = listRoot.contains(document.activeElement) ? document.activeElement : null;
      let position = listRoot.firstElementChild;
      for (const song of ranked) {
        const card = cardsBySlug.get(song.slug);
        if (card !== position) listRoot.insertBefore(card, position);
        position = card.nextElementSibling;
      }
      if (focused && document.activeElement !== focused && !focused.closest(".song-card")?.hidden) {
        focused.focus({preventScroll: true});
      }
      emptyMessage.hidden = visibleSongs.length > 0;
      emptyMessage.textContent = query && lyricSearch.status === "loading"
        ? "No songs match your search or filters yet. Searching lyrics…"
        : query && lyricSearch.status === "error"
          ? "No songs match your search or filters. Lyrics are unavailable; edit your search to retry."
          : "No songs match. Try changing your search or filters.";

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
    let awaitingLyrics = false;
    const searchChanged = () => {
      if (search.value.trim() && lyricSearch.status !== "ready" && !awaitingLyrics) {
        awaitingLyrics = true;
        loadLyrics().then(() => {
          awaitingLyrics = false;
          render(); // Read the current input and facets, never the initiating query.
        });
      }
      render();
    };
    search.addEventListener("input", searchChanged);
    filterToggle?.addEventListener("click", () => {
      filters.hidden = !filters.hidden;
      filterToggle.setAttribute("aria-expanded", String(!filters.hidden));
    });
    shuffleButton?.addEventListener("click", () => root.dispatchEvent(new CustomEvent("bhakti:shuffle-request", {
      bubbles: true,
      detail: { songs: [...visibleSongs] },
    })));
    const closeQueueChoices = ({ returnFocus = false } = {}) => {
      const trigger = menuTrigger;
      if (!trigger) return;
      trigger.setAttribute("aria-expanded", "false");
      const menu = queueMenu;
      const restoreFocus = returnFocus || menu.contains(document.activeElement);
      menu.hidden = true;
      menuTrigger = null;
      if (restoreFocus) trigger.focus({preventScroll: true});
    };
    const openQueueChoices = (trigger, last = false) => {
      closeQueueChoices();
      const menu = queueMenu;
      menuTrigger = trigger;
      menu.setAttribute("aria-label", trigger.getAttribute("aria-label"));
      queueChoices.forEach(choice => { choice.dataset.addToQueue = trigger.dataset.queueChoices; });
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
      if (event.key === "Escape" && (menu || event.target.closest(".song-card"))) {
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
      render: searchChanged,
      getVisibleSongs: () => [...visibleSongs],
    });
    controllers.set(root, controller);
    searchChanged();
    return controller;
  };

  window.BHAKTI_SEARCH = Object.freeze({ searchForms, matchesSearch, filterSongs, creditLine });
  window.BHAKTI_LIBRARY = Object.freeze({ mount });

  const autoMount = () => {
    if (typeof document.querySelector === "function") mount(document.querySelector("main") || document);
  };
  if (typeof document.addEventListener === "function") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoMount, { once: true });
    else autoMount();
  }
})();
