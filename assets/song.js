/* =============================================================
   Koi Hor Nahi Hai Mera — song data + render
   -------------------------------------------------------------
   Roman transliteration: macrons (ā ī ū) for long vowels,
   ṛ for the Punjabi retroflex flap (ੜ), ṭ/ḍ/ḍh for retroflex
   stops where they meaningfully differ. Terminal vowel
   nasalization is dropped (no anusvāra); medial nasal-before-
   consonant is written as plain n. ch = ਚ, chh = ਛ, sh = ਸ਼.
   ============================================================= */

const LINES = {
  invocation: {
    roman: "Mā merī sachīyā jotā wālī mātā, terī sadā hī jai",
    english: "{1:My} {0,5:mother} — the {2:true} {3:sacred flames} — {6:You} are {7:eternally} {8:victorious}.",
    words: [
      { roman: "Mā",         gloss: "Mother" },
      { roman: "merī",       gloss: "my" },
      { roman: "sachīyā",    gloss: "true, genuine, eternal" },
      { roman: "jotā",       gloss: "flames, sacred lamp-flames" },
      { roman: "wālī",       gloss: "bearer of, associated with" },
      { roman: "mātā",       gloss: "mother" },
      { roman: "terī",       gloss: "Your" },
      { roman: "sadā hī",    gloss: "always, forever" },
      { roman: "jai",        gloss: "victory, glory, praise" }
    ]
  },

  refrain: {
    roman: "Main laṛ phaṛyā ae terā, koī hor nahī ae merā",
    english: "{0:I} {3:have} {2:grabbed onto} the {1:hem} of {4:Your} {1:garment}; {6,7:I have no} {5:one else}.",
    words: [
      { roman: "Main",     gloss: "I" },
      { roman: "laṛ",      gloss: "hem, edge of a garment" },
      { roman: "phaṛyā",   gloss: "have grasped, have held" },
      { roman: "ae",       gloss: "is" },
      { roman: "terā",     gloss: "Yours" },
      { roman: "koī hor",  gloss: "anyone else" },
      { roman: "nahī ae",  gloss: "there is not" },
      { roman: "merā",     gloss: "mine" }
    ]
  },

  v1a: {
    roman: "Asī sāh chhaḍ jāvānge",
    english: "{0:My} {1:breath} {3:is going to} {2:abandon} {0:me}.",
    words: [
      { roman: "Asī",        gloss: "we" },
      { roman: "sāh",        gloss: "breath" },
      { roman: "chhaḍ",      gloss: "leave, let go" },
      { roman: "jāvānge",    gloss: "we will go" }
    ]
  },

  v1b: {
    roman: "Pher bājā māroge, asī muṛ nahīyo āvānge",
    english: "{0:Then} {2:You will} {1:cry out} — and {3:I} {5,6:will not} {4:turn back}.",
    words: [
      { roman: "Pher",       gloss: "then, afterwards" },
      { roman: "bājā",       gloss: "horn, instrument (in idiom 'bājā mārnā' = to call out, to summon)" },
      { roman: "māroge",     gloss: "you will strike, you will sound" },
      { roman: "asī",        gloss: "we" },
      { roman: "muṛ",        gloss: "back, again" },
      { roman: "nahīyo",     gloss: "not (emphatic)" },
      { roman: "āvānge",     gloss: "we will come" }
    ]
  },

  v2a: {
    roman: "Is zindagī ton kī lainā, mā",
    english: "{3:What} {4:is there to get} {2:from} {0:this} {1:life} anyway, {5:Mother}?",
    words: [
      { roman: "Is",         gloss: "this" },
      { roman: "zindagī",    gloss: "life" },
      { roman: "ton",        gloss: "from" },
      { roman: "kī",         gloss: "what" },
      { roman: "lainā",      gloss: "to take, to get" },
      { roman: "mā",         gloss: "Mother" }
    ]
  },

  v2b: {
    roman: "Darshan nā hoyā, pher jī ke kī lainā",
    english: "If {1:I do not get} to {0:see You}, {4:what will I gain} {3:from living}?",
    words: [
      { roman: "Darshan",    gloss: "sacred sight, seeing" },
      { roman: "nā hoyā",    gloss: "did not happen, has not occurred" },
      { roman: "pher",       gloss: "then" },
      { roman: "jī ke",      gloss: "by living, having lived" },
      { roman: "kī lainā",   gloss: "what to take, what to get" }
    ]
  },

  v3a: {
    roman: "Asī dar tere āvānge",
    english: "{0:I} {3:will come} to {2:Your} {1:door} just like this.",
    words: [
      { roman: "Asī",        gloss: "we" },
      { roman: "dar",        gloss: "door, threshold" },
      { roman: "tere",       gloss: "Your" },
      { roman: "āvānge",     gloss: "we will come" }
    ]
  },

  v3b: {
    roman: "Saun apnī pāvengī, tainū chhaḍ ke nā jāvānge",
    english: "Even if {2:You have me swear by} {1:Your own} {0:oath}, {5:I will never} {4:leave} {3:You}.",
    words: [
      { roman: "Saun",          gloss: "oath" },
      { roman: "apnī",          gloss: "one's own, your own" },
      { roman: "pāvengī",       gloss: "you will place, you will put (in idiom 'saun pāuṇā' = to impose an oath)" },
      { roman: "tainū",         gloss: "You" },
      { roman: "chhaḍ ke",      gloss: "having left, leaving" },
      { roman: "nā jāvānge",    gloss: "we will not go" }
    ]
  },

  v4a: {
    roman: "Eh zindagī terī ae, mā",
    english: "{0:This} {1:life} {3:is} already {2:Yours}, {4:Mother}.",
    words: [
      { roman: "Eh",         gloss: "this" },
      { roman: "zindagī",    gloss: "life" },
      { roman: "terī",       gloss: "Yours" },
      { roman: "ae",         gloss: "is" },
      { roman: "mā",         gloss: "Mother" }
    ]
  },

  v4b: {
    roman: "Kado pherā ā jāve, is miṭṭī dī ḍherī ae",
    english: "{0:Who knows when} {1:the final turn} {2:will come}? {3:This} body {7:is} a {6:heap} {5:of} {4:earth}.",
    words: [
      { roman: "Kado",       gloss: "when" },
      { roman: "pherā",      gloss: "a turn, a round, a visit" },
      { roman: "ā jāve",     gloss: "may come" },
      { roman: "is",         gloss: "this" },
      { roman: "miṭṭī",      gloss: "earth, dust, clay" },
      { roman: "dī",         gloss: "of" },
      { roman: "ḍherī",      gloss: "heap, pile" },
      { roman: "ae",         gloss: "is" }
    ]
  },

  v5a: {
    roman: "Tere charnā ’ch reh lānge",
    english: "{3:I will just stay} {2:at} {0:Your} {1:feet}.",
    words: [
      { roman: "Tere",       gloss: "Your" },
      { roman: "charnā",     gloss: "feet" },
      { roman: "’ch",        gloss: "in, at (contraction of vicc)" },
      { roman: "reh lānge",  gloss: "we will stay, we will remain" }
    ]
  },

  v5b: {
    roman: "Tū sānū māf kar deyī, asī hass ke seh lānge",
    english: "{0:You} {2:forgive} {1:me}, and {3:I} {5:will do everything} {4:laughingly}.",
    words: [
      { roman: "Tū",             gloss: "You" },
      { roman: "sānū",           gloss: "us" },
      { roman: "māf kar deyī",   gloss: "please forgive (gentle imperative)" },
      { roman: "asī",            gloss: "we" },
      { roman: "hass ke",        gloss: "laughing, smiling" },
      { roman: "seh lānge",      gloss: "we will bear, we will endure" }
    ]
  },

  v6a: {
    roman: "Terā ho ke main āvāngā, mā",
    english: "{2:I} {3:will only come back} {1:belonging} {0:to You}, {4:Mother}.",
    words: [
      { roman: "Terā",       gloss: "Yours" },
      { roman: "ho ke",      gloss: "having become" },
      { roman: "main",       gloss: "I" },
      { roman: "āvāngā",     gloss: "I will come" },
      { roman: "mā",         gloss: "Mother" }
    ]
  },

  v6b: {
    roman: "Tū vī pher rovengī, je chhaḍ tainū jāvāngā",
    english: "{0:Even You} {2:will cry} {1:then}, {3:if} {6:I} ever {4:left} {5:You}.",
    words: [
      { roman: "Tū vī",      gloss: "You too" },
      { roman: "pher",       gloss: "then" },
      { roman: "rovengī",    gloss: "You will weep" },
      { roman: "je",         gloss: "if" },
      { roman: "chhaḍ",      gloss: "leaving" },
      { roman: "tainū",      gloss: "You" },
      { roman: "jāvāngā",    gloss: "I will go" }
    ]
  },

  v7a: {
    roman: "Tere reham bathere ne, mā",
    english: "{0:Your} {1:grace} {3:is} {2:infinite}, {4:Mother}.",
    words: [
      { roman: "Tere",       gloss: "Your" },
      { roman: "reham",      gloss: "mercy, grace" },
      { roman: "bathere",    gloss: "many, plentiful" },
      { roman: "ne",         gloss: "are" },
      { roman: "mā",         gloss: "Mother" }
    ]
  },

  v7b: {
    roman: "Khushīyā dikhā de vī mā, nahī te hanjū bathere ne",
    english: "{1:Show me} {0:happiness}, {3:Mother}. {4:Otherwise}, {5:tears} {6:are plentiful}.",
    words: [
      { roman: "Khushīyā",   gloss: "joys, happinesses" },
      { roman: "dikhā de",   gloss: "show, let see" },
      { roman: "vī",         gloss: "also, even" },
      { roman: "mā",         gloss: "Mother" },
      { roman: "nahī te",    gloss: "otherwise" },
      { roman: "hanjū",      gloss: "tears" },
      { roman: "bathere ne", gloss: "are many, are plentiful" }
    ]
  },

  v8a: {
    roman: "Asī pher vī nahī bolānge, mā",
    english: "{1:Even then}, {0:I} {2:will not say a word of complaint}, {3:Mother}.",
    words: [
      { roman: "Asī",            gloss: "we" },
      { roman: "pher vī",        gloss: "even then, still" },
      { roman: "nahī bolānge",   gloss: "we will not speak" },
      { roman: "mā",             gloss: "Mother" }
    ]
  },

  v8b: {
    roman: "Ikk vārī dass te jā, dukh kihde agge pholānge",
    english: "{2:Just} {1:tell} me {0:once}, {4:before who else} can I let {3:my sorrows} {5:blossom}?",
    words: [
      { roman: "Ikk vārī",   gloss: "just once" },
      { roman: "dass",       gloss: "tell" },
      { roman: "te jā",      gloss: "and go" },
      { roman: "dukh",       gloss: "sorrow, pain" },
      { roman: "kihde agge", gloss: "before whom" },
      { roman: "pholānge",   gloss: "(we) will blossom, will spread open" }
    ]
  },

  outro1: {
    roman: "Eh likh ke main jāvāngā, mā",
    english: "{1:Writing} {0:this}, {2:I} {3:will leave}, {4:Mother}:",
    words: [
      { roman: "Eh",         gloss: "this" },
      { roman: "likh ke",    gloss: "having written" },
      { roman: "main",       gloss: "I" },
      { roman: "jāvāngā",    gloss: "I will go" },
      { roman: "mā",         gloss: "Mother" }
    ]
  },

  outro2: {
    roman: "Agle janam vī mā, terā putt kahāvāngā",
    english: "{1:Even} {0:in the next life}, {2:Mother}, {5:I will be called} {3:Your} {4:son}.",
    words: [
      { roman: "Agle janam", gloss: "next birth, next life" },
      { roman: "vī",         gloss: "also, even" },
      { roman: "mā",         gloss: "Mother" },
      { roman: "terā",       gloss: "Your" },
      { roman: "putt",       gloss: "son" },
      { roman: "kahāvāngā",  gloss: "I will be called" }
    ]
  },

  closing: {
    roman: "Koī hor nahī ae merā",
    english: "{1,2:I have no} {0:one else}.",
    words: [
      { roman: "Koī hor",    gloss: "anyone else" },
      { roman: "nahī ae",    gloss: "there is not" },
      { roman: "merā",       gloss: "mine" }
    ]
  }
};

/* SEQUENCE — the song's structure, in order.
   Each entry references a line id and an optional repetition count. */
const SEQUENCE = [
  { ref: "invocation" },

  { ref: "refrain", repeats: 4 },

  { ref: "v1a", repeats: 4 },
  { ref: "v1b", repeats: 4 },

  { ref: "refrain", repeats: 2 },

  { ref: "v2a", repeats: 4 },
  { ref: "v2b", repeats: 4 },

  { ref: "refrain", repeats: 4 },

  { ref: "v3a", repeats: 4 },
  { ref: "v3b", repeats: 2 },

  { ref: "refrain", repeats: 4 },

  { ref: "v4a", repeats: 4 },
  { ref: "v4b", repeats: 2 },

  { ref: "refrain", repeats: 4 },

  { ref: "v5a", repeats: 4 },
  { ref: "v5b", repeats: 4 },

  { ref: "refrain", repeats: 2 },

  { ref: "v6a", repeats: 4 },
  { ref: "v6b", repeats: 2 },

  { ref: "refrain", repeats: 2 },

  { ref: "v7a", repeats: 4 },
  { ref: "v7b", repeats: 2 },

  { ref: "refrain", repeats: 4 },

  { ref: "v8a", repeats: 4 },
  { ref: "v8b", repeats: 4 },

  { ref: "outro1", repeats: 4 },
  { ref: "outro2", repeats: 4 },

  { ref: "refrain", repeats: 6 },

  { ref: "closing" }
];

/* =============================================================
   RENDER
   ============================================================= */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function renderEnglishWithSpans(english) {
  const re = /\{([\d,\s]+):([^}]*)\}/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(english)) !== null) {
    if (m.index > last) out += escapeHtml(english.slice(last, m.index));
    const indices = m[1].split(",").map(s => s.trim()).filter(Boolean).join(" ");
    out += `<span class="we" data-word-i="${indices}">${escapeHtml(m[2])}</span>`;
    last = m.index + m[0].length;
  }
  if (last < english.length) out += escapeHtml(english.slice(last));
  return out;
}

function renderRomanWithSpans(roman, words) {
  if (!words || !words.length) return escapeHtml(roman);
  let html = "";
  let cursor = 0;
  const lower = roman.toLowerCase();
  for (let i = 0; i < words.length; i++) {
    const token = words[i].roman;
    const idx = lower.indexOf(token.toLowerCase(), cursor);
    if (idx === -1) {
      html += escapeHtml(roman.slice(cursor));
      cursor = roman.length;
      break;
    }
    if (idx > cursor) html += escapeHtml(roman.slice(cursor, idx));
    const surface = roman.slice(idx, idx + token.length);
    html += `<span class="w" data-word-i="${i}" data-gloss="${escapeHtml(words[i].gloss)}" tabindex="0">${escapeHtml(surface)}</span>`;
    cursor = idx + token.length;
  }
  if (cursor < roman.length) html += escapeHtml(roman.slice(cursor));
  return html;
}

function renderLine(line, repeats, instanceId, defaultSourceLanguage) {
  const repBadge = repeats && repeats > 1
    ? `<span class="rep" aria-label="repeated ${repeats} times">×${repeats}</span>`
    : "";
  return `
    <article class="line" id="${instanceId}">
      ${line.source ? `<div class="line-source" lang="${escapeHtml(line.sourceLanguage || defaultSourceLanguage || "")}">${escapeHtml(line.source)}</div>` : ""}
      <div class="line-roman">${renderRomanWithSpans(line.roman, line.words)}${repBadge}</div>
      <div class="line-english">${renderEnglishWithSpans(line.english)}</div>
    </article>
  `;
}

function render() {
  const root = document.getElementById("songRoot");
  if (!root) return;
  let html = "";
  const seq = window.SONG_SEQUENCE || SEQUENCE;
  const lines = window.SONG_LINES || LINES;
  const language = (window.SONG_META?.languages || [])[0];
  const defaultSourceLanguage = { Hindi: "hi", Sanskrit: "sa", Punjabi: "pa", Kannada: "kn" }[language] || "";
  seq.forEach((entry, idx) => {
    const line = lines[entry.ref];
    if (!line) return;
    html += renderLine(line, entry.repeats, `ln-${idx}-${entry.ref}`, defaultSourceLanguage);
  });
  root.innerHTML = html;
  wireInteractions(root);
}

/* ----- Tooltip (single, reused) ----- */
let tooltipEl = null;
function ensureTooltip() {
  if (tooltipEl) return tooltipEl;
  tooltipEl = document.createElement("div");
  tooltipEl.className = "word-tooltip";
  tooltipEl.setAttribute("role", "tooltip");
  tooltipEl.hidden = true;
  document.body.appendChild(tooltipEl);
  return tooltipEl;
}
function showTooltip(span, text) {
  const tip = ensureTooltip();
  tip.textContent = text;
  tip.hidden = false;
  const r = span.getBoundingClientRect();
  tip.style.left = "0px";
  tip.style.top  = "0px";
  const tr = tip.getBoundingClientRect();
  const margin = 8;
  let left = r.left + r.width / 2 - tr.width / 2 + window.scrollX;
  let top  = r.top - tr.height - 8 + window.scrollY;
  const minLeft = window.scrollX + margin;
  const maxLeft = window.scrollX + document.documentElement.clientWidth - tr.width - margin;
  if (left < minLeft) left = minLeft;
  if (left > maxLeft) left = maxLeft;
  if (top < window.scrollY + margin) top = r.bottom + 8 + window.scrollY;
  tip.style.left = left + "px";
  tip.style.top  = top + "px";
}
function hideTooltip() { if (tooltipEl) tooltipEl.hidden = true; }

function activate(span) {
  const article = span.closest(".line");
  if (!article) return;
  const i = span.dataset.wordI;
  span.classList.add("is-hi");
  article.querySelectorAll(".we").forEach(el => {
    const idx = el.dataset.wordI.split(/\s+/);
    if (idx.includes(i)) el.classList.add("is-hi");
  });
  showTooltip(span, span.dataset.gloss || "");
}
function deactivate(span) {
  const article = span.closest(".line");
  if (!article) return;
  const i = span.dataset.wordI;
  span.classList.remove("is-hi");
  article.querySelectorAll(".we").forEach(el => {
    const idx = el.dataset.wordI.split(/\s+/);
    if (idx.includes(i)) el.classList.remove("is-hi");
  });
  hideTooltip();
}
function deactivateAll(root) {
  if (tooltipEl) tooltipEl.hidden = true;
  root.querySelectorAll(".w.is-hi, .we.is-hi").forEach(el => el.classList.remove("is-hi"));
}

function wireInteractions(root) {
  let stickyWord = null;
  let hoverWord  = null;

  root.addEventListener("mouseover", e => {
    const w = e.target.closest(".w");
    if (!w || w === hoverWord) return;
    if (hoverWord && hoverWord !== stickyWord) deactivate(hoverWord);
    hoverWord = w;
    activate(w);
  });
  root.addEventListener("mouseout", e => {
    const w = e.target.closest(".w");
    if (!w) return;
    const to = e.relatedTarget;
    if (to && w.contains(to)) return;
    if (w !== stickyWord) deactivate(w);
    if (hoverWord === w) hoverWord = null;
  });

  root.addEventListener("click", e => {
    const w = e.target.closest(".w");
    if (!w) return;
    e.stopPropagation();
    if (stickyWord === w) {
      stickyWord = null;
      deactivate(w);
      return;
    }
    if (stickyWord) deactivate(stickyWord);
    stickyWord = w;
    activate(w);
  });
  document.addEventListener("click", () => {
    if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
  });

  root.addEventListener("focusin", e => {
    const w = e.target.closest(".w");
    if (!w) return;
    activate(w);
  });
  root.addEventListener("focusout", e => {
    const w = e.target.closest(".w");
    if (!w || w === stickyWord) return;
    deactivate(w);
  });

  window.addEventListener("scroll", () => {
    if (tooltipEl) tooltipEl.hidden = true;
  }, { passive: true });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
      else deactivateAll(root);
    }
  });
}

/* =============================================================
   KARAOKE — sync line highlight to audio playback time
   ============================================================= */

function setupKaraoke() {
  const audio = document.getElementById("songAudio");
  const TIMINGS = window.SONG_TIMINGS || [];
  if (!audio || !TIMINGS.length) return;

  let activeIdx = -1;
  const seq = window.SONG_SEQUENCE || SEQUENCE;

  audio.addEventListener("timeupdate", () => {
    const t = audio.currentTime;
    const idx = TIMINGS.findIndex(seg => t >= seg.start && t < seg.end);
    if (idx === activeIdx) return;
    activeIdx = idx;

    document.querySelectorAll(".line.is-singing").forEach(el => el.classList.remove("is-singing"));
    if (idx < 0) return;

    const article = document.getElementById(`ln-${idx}-${seq[idx].ref}`);
    if (!article) return;
    article.classList.add("is-singing");

    // Always follow the song — auto-scroll the active line to the
    // vertical center on every line change. (If the listener wants
    // to scroll back, they have until the next line change.)
    article.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // Click a line to jump audio there (only if it has a timing).
  document.getElementById("songRoot").addEventListener("click", e => {
    if (e.target.closest(".w")) return;            // word click handled elsewhere
    const article = e.target.closest(".line");
    if (!article) return;
    const m = article.id.match(/^ln-(\d+)-/);
    if (!m) return;
    const i = parseInt(m[1], 10);
    const seg = TIMINGS[i];
    if (!seg) return;
    const seekAndPlay = () => {
      audio.currentTime = seg.start;
      audio.play().catch(() => {});
    };

    // A click may arrive before preload="metadata" has resolved. Setting
    // currentTime then can be silently reset to 0 by the browser, making a
    // correct timing map appear wrong. Seek only once the duration is known.
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) seekAndPlay();
    else audio.addEventListener("loadedmetadata", seekAndPlay, { once: true });
  });
}

/* =============================================================
   AUDIO PLAYER — custom controls bound to the hidden <audio>
   ============================================================= */

function fmtTime(s) {
  if (!isFinite(s)) return "—:—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60).toString().padStart(2, "0");
  return `${m}:${sec}`;
}

function setupAudioPlayer() {
  const audio   = document.getElementById("songAudio");
  const btn     = document.getElementById("apPlayPause");
  const progEl  = document.getElementById("apProgress");
  const barEl   = document.getElementById("apProgressBar");
  if (!audio || !btn) return;

  btn.addEventListener("click", () => {
    if (audio.paused) audio.play();
    else audio.pause();
  });
  audio.addEventListener("play",  () => { btn.classList.add("is-playing");    btn.setAttribute("aria-label", "Pause"); });
  audio.addEventListener("pause", () => { btn.classList.remove("is-playing"); btn.setAttribute("aria-label", "Play");  });

  audio.addEventListener("timeupdate", () => {
    if (isDragging) return;                       // don't fight the user
    const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
    barEl.style.width = pct + "%";
  });

  // Drag-to-seek on the progress bar. Pointer events unify mouse + touch.
  let isDragging = false;
  const seekFromPointer = e => {
    if (!audio.duration) return;
    const r = progEl.getBoundingClientRect();
    const x = e.clientX - r.left;
    const pct = Math.max(0, Math.min(1, x / r.width));
    audio.currentTime = pct * audio.duration;
    barEl.style.width = (pct * 100) + "%";
  };
  progEl.addEventListener("pointerdown", e => {
    isDragging = true;
    progEl.setPointerCapture(e.pointerId);
    seekFromPointer(e);
  });
  progEl.addEventListener("pointermove", e => {
    if (isDragging) seekFromPointer(e);
  });
  const endDrag = e => {
    if (!isDragging) return;
    isDragging = false;
    try { progEl.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  progEl.addEventListener("pointerup", endDrag);
  progEl.addEventListener("pointercancel", endDrag);

  // Spacebar play/pause when not focused in a form field.
  document.addEventListener("keydown", e => {
    if (e.key !== " " && e.code !== "Space") return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    e.preventDefault();
    if (audio.paused) audio.play(); else audio.pause();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  render();
  setupAudioPlayer();
  setupKaraoke();
});
