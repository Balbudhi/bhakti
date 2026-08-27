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

let PAGE_META = {...(window.SONG_META || {}), ...(window.BHAKTI_EDITION_META || {})};
let PAGE_LINES = window.SONG_LINES || null;
let PAGE_SEQUENCE = window.SONG_SEQUENCE || null;
let PAGE_TIMINGS = window.SONG_TIMINGS || null;
// A long recitation can contain hundreds of individually interactive words.
// Rendering every one at once exhausts mobile Safari while navigating between
// the reader and library, so long readers reveal calm contiguous chunks as the
// listener approaches them. A direct seek still materializes its target.
const LAZY_LINE_THRESHOLD = 180;
const INITIAL_LINE_BATCH = 56;
const NEXT_LINE_BATCH = 40;
let lazyLineCount = 0;
let lazyAppendLines = null;
let lazyObserver = null;

function indicesFrom(value) {
  return String(value || "").split(/\s+/).filter(Boolean).map(Number).filter(Number.isInteger);
}

function glossFor(words, indices) {
  return [...new Set(indices.map(index => words?.[index]?.gloss).filter(Boolean))].join(" · ");
}

function linkedWord(className, surface, indices, words) {
  const value = indices.join(" ");
  return `<span class="${className} word-link" data-word-i="${value}" data-gloss="${escapeHtml(glossFor(words, indices))}" role="button" tabindex="0">${escapeHtml(surface)}</span>`;
}

function renderEnglishWithSpans(english, words) {
  const re = /\{([\d,\s]+):([^}]*)\}/g;
  let out = "";
  let last = 0;
  let m;
  while ((m = re.exec(english)) !== null) {
    if (m.index > last) out += escapeHtml(english.slice(last, m.index));
    const indices = m[1].split(",").map(value => Number(value.trim())).filter(Number.isInteger);
    out += linkedWord("we", m[2], indices, words);
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
    html += linkedWord("w", surface, [i], words);
    cursor = idx + token.length;
  }
  if (cursor < roman.length) html += escapeHtml(roman.slice(cursor));
  return html;
}

function renderSourceWithSpans(source, sourceWords, words) {
  if (!sourceWords?.length) return escapeHtml(source);
  let html = "";
  let cursor = 0;
  for (const mapped of sourceWords) {
    const surface = String(mapped.text || "");
    const index = source.indexOf(surface, cursor);
    if (index === -1) return escapeHtml(source);
    if (index > cursor) html += escapeHtml(source.slice(cursor, index));
    html += linkedWord("ws", surface, mapped.wordIndices || [], words);
    cursor = index + surface.length;
  }
  if (cursor < source.length) html += escapeHtml(source.slice(cursor));
  return html;
}

function renderLine(line, repeats, instanceId, defaultSourceLanguage, startSeconds, adapted = false) {
  const repBadge = repeats && repeats > 1
    ? `<span class="rep" aria-label="repeated ${repeats} times">×${repeats}</span>`
    : "";
  const adaptedBadge = adapted
    ? `<span class="adapted-badge" aria-label="Sai-specific adaptation">Sai adaptation</span>`
    : "";
  const startAttr = Number.isFinite(startSeconds) ? ` data-start="${startSeconds}"` : "";
  return `
    <article class="line${adapted ? " is-adapted" : ""}" id="${instanceId}"${startAttr}>
      <button class="line-seek" type="button" aria-label="Play from this line" title="Play from this line">
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path d="M7 5l12 7-12 7V5z" fill="currentColor"/></svg>
      </button>
      ${line.source ? `<div class="line-source" lang="${escapeHtml(line.sourceLanguage || defaultSourceLanguage || "")}">${renderSourceWithSpans(line.source, line.sourceWords, line.words)}</div>` : ""}
      <div class="line-roman">${renderRomanWithSpans(line.roman, line.words)}${repBadge}${adaptedBadge}</div>
      <div class="line-english">${renderEnglishWithSpans(line.english, line.words)}</div>
    </article>
  `;
}

function renderSourceNotice(notice) {
  const poet = notice.poet ? `<p class="source-notice-poet"><span>Poet</span>${escapeHtml(notice.poet)}</p>` : "";
  const detail = notice.note ? `<p class="source-notice-detail">${escapeHtml(notice.note)}</p>` : "";
  return `<aside class="source-notice"><h2>${escapeHtml(notice.title || "")}</h2>${poet}${detail}</aside>`;
}

let selectedTextEdition = null;

function selectedEdition(meta) {
  const variants = meta?.editionVariants || {};
  const fallback = meta?.editionDefault || Object.keys(variants)[0] || "";
  if (!fallback) return "";
  if (selectedTextEdition && variants[selectedTextEdition]) return selectedTextEdition;
  const storageKey = `bhakti:text-edition:${location.pathname}`;
  try {
    const stored = localStorage.getItem(storageKey);
    selectedTextEdition = variants[stored] ? stored : fallback;
  } catch (_) {
    selectedTextEdition = fallback;
  }
  return selectedTextEdition;
}

function renderEditionSwitch(meta) {
  const variants = meta?.editionVariants || {};
  const keys = Object.keys(variants);
  if (keys.length < 2) return "";
  const active = selectedEdition(meta);
  const options = keys.map(key => {
    const variant = variants[key] || {};
    const label = variant.shortLabel || variant.label || key;
    return `<option value="${escapeHtml(key)}"${key === active ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }).join("");
  return `<div class="edition-switch"><label class="visually-hidden" for="editionSelect">Text edition</label><select class="edition-select" id="editionSelect" aria-label="Text edition">${options}</select></div>`;
}

function lineForEdition(line, lineId, meta) {
  const variant = meta?.editionVariants?.[selectedEdition(meta)];
  const override = variant?.lines?.[lineId];
  if (!override) return line;
  const words = (line.words || []).map((word, index) => ({...word, ...(override.wordEdits?.[index] || {})}));
  return {...line, ...override, words};
}

function renderSongMeta() {
  const meta = PAGE_META;
  const hero = document.querySelector(".song-hero");
  if (!meta || !hero) return;

  const title = hero.querySelector(".song-title");
  if (title && meta.title) title.textContent = meta.title;
  if (meta.title) document.title = meta.title;

  hero.querySelectorAll(".song-attrib, .song-credit").forEach(element => element.remove());
  const people = new Map();
  [["writer", "Poet"], ["singer", "Singer"], ["vocalist", "Vocalist"], ["composer", "Composer"], ["ensemble", "Recital"]].forEach(([field, role]) => {
    const person = String(meta[field] || "").trim();
    if (!person) return;
    people.set(person, [...(people.get(person) || []), role]);
  });
  const displayRoles = (person, roles) => {
    const peopleCount = String(person).split(/\s+(?:&|and)\s+/i).filter(Boolean).length;
    return roles.map(role => role === "Recital" || peopleCount === 1 ? role : `${role}s`).join(" · ");
  };
  const credits = [...people].map(([person, roles]) => `
    <div class="song-credit-entry">
      <dt>${escapeHtml(displayRoles(person, roles))}</dt>
      <dd>${escapeHtml(person)}</dd>
    </div>`).join("");
  const tags = [
    ...(meta.subjectTags || []).map(tag => `<span class="song-tag subject-tag">${escapeHtml(tag)}</span>`),
    ...(meta.languages || []).map(tag => `<span class="song-tag language-tag">${escapeHtml(tag)}</span>`),
  ].join("");
  selectedEdition(meta);
  const editionSwitch = renderEditionSwitch(meta);
  let songMeta = hero.querySelector(".song-meta");
  if (!songMeta) {
    songMeta = document.createElement("div");
    songMeta.className = "song-meta";
    hero.querySelector(".song-hint")?.before(songMeta);
  }
  songMeta.innerHTML = `${credits ? `<dl class="song-credits">${credits}</dl>` : ""}${tags ? `<div class="song-meta-tags" aria-label="Tags">${tags}</div>` : ""}${editionSwitch}`;
  songMeta.hidden = !credits && !tags && !editionSwitch;
  songMeta.querySelectorAll(".edition-select").forEach(select => select.addEventListener("change", () => {
    selectedTextEdition = select.value || selectedEdition(meta);
    try { localStorage.setItem(`bhakti:text-edition:${location.pathname}`, selectedTextEdition); } catch (_) {}
    render();
  }));
}

function lineRenderContext() {
  const seq = PAGE_SEQUENCE || SEQUENCE;
  const lines = PAGE_LINES || LINES;
  const timings = PAGE_TIMINGS || [];
  const notices = new Map((PAGE_META?.sectionNotices || []).map(notice => [Number(notice.sequenceIndex), notice]));
  const adapted = new Set((PAGE_META?.adaptedSequenceIndices || []).map(Number));
  const language = (PAGE_META?.languages || [])[0];
  const defaultSourceLanguage = { Bengali: "bn", Hindi: "hi", Sanskrit: "sa", Punjabi: "pa", Kannada: "kn", Marathi: "mr", Odia: "or", Braj: "bra" }[language] || "";
  return { seq, lines, timings, notices, adapted, defaultSourceLanguage };
}

function renderLineRange(context, start, end) {
  let html = "";
  for (let idx = start; idx < end; idx++) {
    const entry = context.seq[idx];
    const line = lineForEdition(context.lines[entry.ref], entry.ref, PAGE_META);
    if (!line) continue;
    if (context.notices.has(idx)) html += renderSourceNotice(context.notices.get(idx));
    html += renderLine(line, entry.repeats, `ln-${idx}-${entry.ref}`,
      context.defaultSourceLanguage, context.timings[idx]?.start, context.adapted.has(idx));
  }
  return html;
}

function ensureRenderedThrough(index) {
  if (typeof lazyAppendLines === "function" && index >= lazyLineCount) lazyAppendLines(index + 1);
}

function render() {
  renderSongMeta();
  const root = document.getElementById("songRoot");
  if (!root) return;
  lazyObserver?.disconnect();
  lazyObserver = null;
  lazyAppendLines = null;
  lazyLineCount = 0;
  root.replaceChildren();
  const context = lineRenderContext();
  const lazy = context.seq.length > LAZY_LINE_THRESHOLD;
  const sentinel = lazy ? document.createElement("div") : null;
  if (sentinel) {
    sentinel.className = "line-load-sentinel";
    sentinel.setAttribute("aria-hidden", "true");
    root.append(sentinel);
  }
  lazyAppendLines = target => {
    const end = Math.min(context.seq.length, Math.max(target, lazyLineCount + NEXT_LINE_BATCH));
    if (end <= lazyLineCount) return;
    const html = renderLineRange(context, lazyLineCount, end);
    if (sentinel?.isConnected) sentinel.insertAdjacentHTML("beforebegin", html);
    else root.insertAdjacentHTML("beforeend", html);
    lazyLineCount = end;
    if (lazyLineCount >= context.seq.length) {
      sentinel?.remove();
      lazyObserver?.disconnect();
      lazyObserver = null;
    }
  };
  lazyAppendLines(lazy ? INITIAL_LINE_BATCH : context.seq.length);
  if (lazy && "IntersectionObserver" in window && sentinel?.isConnected) {
    lazyObserver = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) lazyAppendLines(lazyLineCount + NEXT_LINE_BATCH);
    }, { rootMargin: "900px 0px" });
    lazyObserver.observe(sentinel);
  }
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
  const selected = new Set(indicesFrom(span.dataset.wordI));
  article.querySelectorAll(".word-link").forEach(element => {
    const linked = indicesFrom(element.dataset.wordI);
    element.classList.toggle("is-hi", linked.some(index => selected.has(index)));
  });
  showTooltip(span, span.dataset.gloss || "");
}
function deactivate(span) {
  const article = span.closest(".line");
  if (!article) return;
  article.querySelectorAll(".word-link.is-hi").forEach(element => element.classList.remove("is-hi"));
  hideTooltip();
}
function deactivateAll(root) {
  if (tooltipEl) tooltipEl.hidden = true;
  root.querySelectorAll(".word-link.is-hi").forEach(el => el.classList.remove("is-hi"));
}

const WIRED_INTERACTION_ROOTS = new WeakSet();
function wireInteractions(root) {
  if (WIRED_INTERACTION_ROOTS.has(root)) return;
  WIRED_INTERACTION_ROOTS.add(root);
  let stickyWord = null;
  let hoverWord  = null;
  let keyboardFocus = false;

  // Touch Safari may synthesize mouseover when karaoke scrolling moves a word
  // beneath the last touch location. Only a device with a real fine hover
  // pointer may activate meanings without an explicit click or focus.
  const hasRealHover = window.matchMedia?.("(hover: hover) and (pointer: fine)").matches;
  if (hasRealHover) {
    root.addEventListener("mouseover", e => {
      const w = e.target.closest(".word-link");
      if (!w || w === hoverWord) return;
      if (hoverWord && hoverWord !== stickyWord) deactivate(hoverWord);
      hoverWord = w;
      activate(w);
    });
    root.addEventListener("mouseout", e => {
      const w = e.target.closest(".word-link");
      if (!w) return;
      const to = e.relatedTarget;
      if (to && w.contains(to)) return;
      if (w !== stickyWord) deactivate(w);
      if (hoverWord === w) hoverWord = null;
    });
  }

  root.addEventListener("pointerdown", e => {
    keyboardFocus = false;
    if (e.target.closest(".word-link")) return;
    if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
  }, true);

  root.addEventListener("click", e => {
    const w = e.target.closest(".word-link");
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
  document.addEventListener("click", event => {
    if (event.target.closest?.(".word-link")) return;
    if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
  });

  root.addEventListener("focusin", e => {
    const w = e.target.closest(".word-link");
    if (!w || !keyboardFocus) return;
    activate(w);
  });
  root.addEventListener("focusout", e => {
    const w = e.target.closest(".word-link");
    if (!w || !keyboardFocus || w === stickyWord) return;
    deactivate(w);
  });

  window.addEventListener("scroll", () => {
    if (tooltipEl) tooltipEl.hidden = true;
    if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
  }, { passive: true });

  document.addEventListener("keydown", e => {
    if (e.key === "Tab") keyboardFocus = true;
    const word = e.target.closest?.(".word-link");
    if (word && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      word.click();
      return;
    }
    if (e.key === "Escape") {
      if (stickyWord) { deactivate(stickyWord); stickyWord = null; }
      else deactivateAll(root);
    }
  });
}

/* =============================================================
   KARAOKE — sync line highlight to audio playback time
   ============================================================= */

// Following the currently sung line is a listening preference, not part of a
// song's data. Keep it on this device so a listener who turns it off while
// reading one song is not surprised by the next song snapping the page away.
const LYRICS_FOLLOW_STORAGE_KEY = "bhakti:lyrics-follow-playback";
function readLyricsFollowPreference() {
  try { return localStorage.getItem(LYRICS_FOLLOW_STORAGE_KEY) !== "false"; }
  catch (_) { return true; }
}
function writeLyricsFollowPreference(enabled) {
  try { localStorage.setItem(LYRICS_FOLLOW_STORAGE_KEY, enabled ? "true" : "false"); }
  catch (_) { /* A private-mode storage failure should not disable the control. */ }
}
let lyricsFollowPlayback = readLyricsFollowPreference();

const WIRED_KARAOKE_AUDIO = new WeakSet();
function setupKaraoke() {
  const audio = document.getElementById("songAudio");
  if (!audio || WIRED_KARAOKE_AUDIO.has(audio)) return;
  WIRED_KARAOKE_AUDIO.add(audio);

  let activeIdx = -1;
  let karaokeFrame = 0;

  const activeArticle = () => {
    const seq = PAGE_SEQUENCE || SEQUENCE;
    ensureRenderedThrough(activeIdx);
    return activeIdx >= 0 && seq[activeIdx]
      ? document.getElementById(`ln-${activeIdx}-${seq[activeIdx].ref}`)
      : null;
  };
  const updateKaraoke = () => {
    const timings = PAGE_TIMINGS || [];
    const nextIndex = timings.findIndex(segment => audio.currentTime >= segment.start && audio.currentTime < segment.end);
    if (nextIndex === activeIdx) return;
    activeIdx = nextIndex;
    document.querySelectorAll(".line.is-singing").forEach(element => element.classList.remove("is-singing"));
    const article = activeArticle();
    if (!article) return;
    article.classList.add("is-singing");
    if (lyricsFollowPlayback) article.scrollIntoView({ behavior: "auto", block: "center" });
  };
  const tickKaraoke = () => {
    updateKaraoke();
    if (!audio.paused && !audio.ended) karaokeFrame = requestAnimationFrame(tickKaraoke);
    else karaokeFrame = 0;
  };
  const startKaraokeClock = () => {
    updateKaraoke();
    if (!karaokeFrame) karaokeFrame = requestAnimationFrame(tickKaraoke);
  };
  const resetKaraoke = () => {
    activeIdx = -1;
    document.querySelectorAll(".line.is-singing").forEach(element => element.classList.remove("is-singing"));
    if (!audio.paused) startKaraokeClock();
  };

  audio.addEventListener("play", startKaraokeClock);
  audio.addEventListener("seeking", updateKaraoke);
  audio.addEventListener("seeked", updateKaraoke);
  audio.addEventListener("timeupdate", updateKaraoke);
  window.addEventListener("bhakti:song-change", resetKaraoke);
  window.addEventListener("bhakti:lyrics-follow-change", event => {
    if (event.detail?.enabled) activeArticle()?.scrollIntoView({ behavior: "auto", block: "center" });
  });

  // Seeking is explicit. Event delegation keeps this binding valid when the
  // reader is replaced during a persistent listening session.
  document.addEventListener("click", event => {
    const seekButton = event.target.closest?.(".line-seek");
    if (!seekButton) return;
    const article = seekButton.closest(".line");
    const start = Number(article?.dataset.start);
    if (!Number.isFinite(start)) return;
    const seekAndPlay = () => {
      audio.currentTime = start;
      audio.play().catch(() => {});
    };
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) seekAndPlay();
    else audio.addEventListener("loadedmetadata", seekAndPlay, { once: true });
  });
}

/* =============================================================
   TOP CONTROLS — share a song and link/unlink lyric following
   ============================================================= */

function canonicalSongUrl() {
  const current = new URL(window.location.href);
  const queue = current.searchParams.get("queue");
  const canonical = PAGE_META?.slug
    ? new URL(`/songs/${encodeURIComponent(PAGE_META.slug)}/`, window.location.origin)
    : new URL(document.querySelector('link[rel="canonical"]')?.href || current.href);
  const url = new URL(canonical);
  url.search = "";
  url.hash = "";
  if (queue) url.searchParams.set("queue", queue);
  return url.href;
}

let controlStatusTimer = 0;
function showControlStatus(message) {
  let status = document.getElementById("songControlStatus");
  if (!status) {
    status = document.createElement("div");
    status.id = "songControlStatus";
    status.className = "song-control-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;
    document.body.append(status);
  }
  window.clearTimeout(controlStatusTimer);
  status.textContent = message;
  status.hidden = false;
  controlStatusTimer = window.setTimeout(() => { status.hidden = true; }, 1800);
}

async function copySongUrl(url) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      return true;
    }
  } catch (_) { /* Fall through for older Safari and restrictive contexts. */ }

  const input = document.createElement("textarea");
  input.value = url;
  input.setAttribute("readonly", "");
  input.setAttribute("aria-hidden", "true");
  input.style.cssText = "position:fixed;opacity:0;pointer-events:none";
  document.body.append(input);
  input.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch (_) {}
  input.remove();
  return copied;
}

function shouldUseNativeShare() {
  if (typeof navigator.share !== "function") return false;
  // Native sharing is useful on phones, tablets, and installed PWAs. Desktop
  // browsers instead get the conventional quiet Copy link behavior.
  return window.matchMedia?.("(pointer: coarse)")?.matches
    || window.matchMedia?.("(display-mode: standalone)")?.matches
    || window.matchMedia?.("(display-mode: fullscreen)")?.matches
    || navigator.userAgentData?.mobile === true;
}

function setupTopControls() {
  // Support both the stable ids and class hooks so markup can be rendered by
  // older generated pages while the catalogue updates.
  const shareButton = document.getElementById("songShare") || document.querySelector(".song-share");
  const syncButton = document.getElementById("songSync") || document.querySelector(".song-sync");

  if (shareButton && !shareButton.dataset.bhaktiBound) {
    shareButton.dataset.bhaktiBound = "true";
    shareButton.addEventListener("click", async () => {
      const url = canonicalSongUrl();
      if (shouldUseNativeShare()) {
        try {
          await navigator.share({ title: document.title, url });
          return;
        } catch (error) {
          // Cancelling native share is intentional; do not turn it into a
          // surprising clipboard write or a modal error.
          if (error?.name === "AbortError") return;
        }
      }
      showControlStatus(await copySongUrl(url) ? "Link copied" : "Could not copy link");
    });
  }

  if (syncButton && !syncButton.dataset.bhaktiBound) {
    syncButton.dataset.bhaktiBound = "true";
    const updateSyncButton = () => {
      syncButton.classList.toggle("is-unlinked", !lyricsFollowPlayback);
      syncButton.setAttribute("aria-pressed", String(lyricsFollowPlayback));
      syncButton.setAttribute("aria-label", lyricsFollowPlayback
        ? "Unlink lyrics from playback"
        : "Link lyrics to playback");
      syncButton.title = lyricsFollowPlayback ? "Lyrics follow playback" : "Lyrics are unlinked";
    };
    updateSyncButton();
    syncButton.addEventListener("click", () => {
      lyricsFollowPlayback = !lyricsFollowPlayback;
      writeLyricsFollowPreference(lyricsFollowPlayback);
      updateSyncButton();
      window.dispatchEvent(new CustomEvent("bhakti:lyrics-follow-change", {
        detail: { enabled: lyricsFollowPlayback }
      }));
    });
  }
}

/* =============================================================
   AUDIO PLAYER — custom controls bound to the hidden <audio>
   ============================================================= */

function fmtTime(s) {
  if (!isFinite(s)) return "—:—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60).toString().padStart(2, "0");
  return h ? `${h}:${m.toString().padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

function setupAudioPlayer() {
  const audio   = document.getElementById("songAudio");
  const btn     = document.getElementById("apPlayPause");
  const progEl  = document.getElementById("apProgress");
  const barEl   = document.getElementById("apProgressBar");
  const elapsed = document.getElementById("apElapsed");
  const duration = document.getElementById("apDuration");
  if (!audio || !btn || audio.dataset.bhaktiPlayerBound) return;
  audio.dataset.bhaktiPlayerBound = "true";

  const updateTime = () => {
    if (elapsed) elapsed.textContent = fmtTime(audio.currentTime || 0);
    if (duration) duration.textContent = fmtTime(audio.duration);
  };

  btn.addEventListener("click", () => {
    if (audio.paused) audio.play();
    else audio.pause();
  });
  audio.addEventListener("play",  () => { btn.classList.add("is-playing");    btn.setAttribute("aria-label", "Pause"); });
  audio.addEventListener("pause", () => { btn.classList.remove("is-playing"); btn.setAttribute("aria-label", "Play");  });
  audio.addEventListener("loadedmetadata", updateTime);
  audio.addEventListener("durationchange", updateTime);

  audio.addEventListener("timeupdate", () => {
    if (isDragging) return;                       // don't fight the user
    const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
    barEl.style.width = pct + "%";
    updateTime();
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
    updateTime();
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
  updateTime();
}

function snapshotGlobals() {
  return {
    meta: {...(window.SONG_META || {}), ...(window.BHAKTI_EDITION_META || {})},
    lines: window.SONG_LINES || null,
    sequence: window.SONG_SEQUENCE || null,
    timings: window.SONG_TIMINGS || null,
  };
}

function setSong(data) {
  if (!data?.meta || !data?.lines || !data?.sequence || !data?.timings) {
    throw new TypeError("complete song data is required");
  }
  PAGE_META = {...data.meta};
  PAGE_LINES = data.lines;
  PAGE_SEQUENCE = data.sequence;
  PAGE_TIMINGS = data.timings;
  selectedTextEdition = null;
  render();
  setupTopControls();
  setupAudioPlayer();
  setupKaraoke();
  window.dispatchEvent(new CustomEvent("bhakti:song-change", { detail: { slug: PAGE_META.slug || "" } }));
}

function mount() {
  render();
  setupTopControls();
  setupAudioPlayer();
  setupKaraoke();
}

window.BHAKTI_READER = Object.freeze({ mount, setSong, snapshotGlobals });

document.addEventListener("DOMContentLoaded", mount, { once: true });
