(() => {
  const root = document.getElementById("songList");
  const songs = window.BHAKTI_SONGS || [];
  root.innerHTML = songs.map((song, index) => `
    <a class="song-card" href="songs/${song.slug}/" aria-label="Open ${song.title}">
      <span class="number">${String(index + 1).padStart(2, "0")}</span>
      <span class="song-copy"><span class="song-title">${song.title}</span><span class="credit">${song.credit}</span></span>
      <span class="tags">${song.tags.map(tag => `<span>${tag}</span>`).join("")}</span>
      <span class="arrow" aria-hidden="true">↗</span>
    </a>`).join("");
})();
