(() => {
  const root = document.getElementById("songList");
  const filters = document.getElementById("tagFilters");
  const songs = window.BHAKTI_SONGS || [];
  let selectedLanguage = "All";
  let selectedSubject = "All";
  const languages = ["All", ...new Set(songs.flatMap(song => song.languageTags))];
  const subjects = ["All", ...new Set(songs.flatMap(song => song.subjectTags))];

  const filtersFor = (kind, values, selected) => values.map(tag => `
    <button type="button" class="tag-filter" aria-pressed="${tag === selected}" data-kind="${kind}" data-tag="${tag}">${tag}</button>`).join("");

  const render = () => {
    const visibleSongs = songs.filter(song =>
      (selectedLanguage === "All" || song.languageTags.includes(selectedLanguage)) &&
      (selectedSubject === "All" || song.subjectTags.includes(selectedSubject))
    );

    filters.innerHTML = `
      <div class="filter-group"><span>Language</span>${filtersFor("language", languages, selectedLanguage)}</div>
      <div class="filter-group"><span>Devotion</span>${filtersFor("subject", subjects, selectedSubject)}</div>`;

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
    if (button.dataset.kind === "language") selectedLanguage = button.dataset.tag || "All";
    if (button.dataset.kind === "subject") selectedSubject = button.dataset.tag || "All";
    render();
  });

  render();
})();
