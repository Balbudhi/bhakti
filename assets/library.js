(() => {
  const root = document.getElementById("songList");
  const songs = window.BHAKTI_SONGS || [];

  root.innerHTML = songs.map(song => `
    <a class="song-card" href="songs/${song.slug}/" aria-label="Open ${song.title}">
      <span class="song-copy">
        <span class="song-title">${song.title}</span>
        <span class="credit">${song.credit}</span>
      </span>
      <span class="tags" aria-label="${song.tags.join(", ")}">
        ${song.tags.map(tag => `<span>${tag}</span>`).join("")}
      </span>
    </a>`).join("");
})();
