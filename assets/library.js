(() => {
  const root = document.getElementById("songList");
  const filters = document.getElementById("tagFilters");
  const search = document.getElementById("songSearch");
  const songs = window.BHAKTI_SONGS || [];
  const selectedLanguages = new Set();
  const selectedSubjects = new Set();
  const languages = [...new Set(songs.flatMap(song => song.languageTags).sort())];
  const subjects = [...new Set(songs.flatMap(song => song.subjectTags).sort())];
  const filterTags = [
    { label: "All", kind: "all" },
    ...languages.map(label => ({ label, kind: "language" })),
    ...subjects.map(label => ({ label, kind: "subject" }))
  ];

  const render = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const visibleSongs = songs.filter(song => {
      const matchesLanguage = !selectedLanguages.size || [...selectedLanguages].some(tag => song.languageTags.includes(tag));
      const matchesSubject = !selectedSubjects.size || [...selectedSubjects].some(tag => song.subjectTags.includes(tag));
      const haystack = [song.title, song.credit, ...song.languageTags, ...song.subjectTags].join(" ").toLocaleLowerCase();
      return matchesLanguage && matchesSubject && (!query || haystack.includes(query));
    });

    const nothingSelected = !selectedLanguages.size && !selectedSubjects.size;
    filters.innerHTML = filterTags.map(tag => {
      const selected = tag.kind === "all"
        ? nothingSelected
        : tag.kind === "language" ? selectedLanguages.has(tag.label) : selectedSubjects.has(tag.label);
      return `<button type="button" class="tag-filter" aria-pressed="${selected}" data-kind="${tag.kind}" data-tag="${tag.label}">${tag.label}</button>`;
    }).join("");

    root.innerHTML = visibleSongs.map(song => `
    <a class="song-card" href="songs/${song.slug}/" aria-label="Open ${song.title}">
      <span class="song-copy">
        <span class="song-title">${song.title}</span>
        <span class="credit">${song.credit}</span>
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
