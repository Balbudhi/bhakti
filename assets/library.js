(() => {
  const root = document.getElementById("songList");
  const filters = document.getElementById("tagFilters");
  const songs = window.BHAKTI_SONGS || [];
  let selectedTag = "All";

  const tags = ["All", ...new Set(songs.flatMap(song => song.tags))];

  const render = () => {
    const visibleSongs = selectedTag === "All"
      ? songs
      : songs.filter(song => song.tags.includes(selectedTag));

    filters.innerHTML = tags.map(tag => `
      <button type="button" class="tag-filter" aria-pressed="${tag === selectedTag}" data-tag="${tag}">${tag}</button>`).join("");

    root.innerHTML = visibleSongs.map(song => `
    <a class="song-card" href="songs/${song.slug}/" aria-label="Open ${song.title}">
      <span class="song-copy">
        <span class="song-title">${song.title}</span>
        <span class="credit">${song.credit}</span>
      </span>
      <span class="tags" aria-label="${song.tags.join(", ")}">
        ${song.tags.map(tag => `<span>${tag}</span>`).join("")}
      </span>
    </a>`).join("");
  };

  filters.addEventListener("click", event => {
    const button = event.target.closest(".tag-filter");
    if (!button) return;
    selectedTag = button.dataset.tag || "All";
    render();
  });

  render();
})();
