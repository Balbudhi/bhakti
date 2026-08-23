(() => {
  "use strict";

  const VERSION = 1;
  const MAX_PAYLOAD_CHARACTERS = 4096;
  const MODES = new Set(["standalone", "custom", "shuffle"]);
  let entrySequence = 0;
  const newEntryId = () => globalThis.crypto?.randomUUID?.()
    || `entry-${Date.now().toString(36)}-${(entrySequence += 1).toString(36)}`;

  const freezeItem = item => {
    if (!item || typeof item !== "object") throw new TypeError("queue item must be an object");
    const slug = String(item.slug || "").trim();
    const queueId = String(item.queueId || "").trim();
    const entryId = String(item.entryId || "").trim() || newEntryId();
    if (!slug) throw new TypeError("queue item slug must be non-empty");
    if (!queueId) throw new TypeError("queue item queueId must be non-empty");
    const audioSources = Object.freeze((item.audioSources || []).map(source => Object.freeze({
      src: String(source?.src || ""),
      type: String(source?.type || ""),
    })));
    return Object.freeze({
      slug,
      queueId,
      entryId,
      title: String(item.title || slug),
      credit: String(item.credit || ""),
      audioSources,
    });
  };

  const create = ({ mode, items, currentIndex, sessionId }) => {
    if (!MODES.has(mode)) throw new TypeError("queue mode is unsupported");
    if (!Array.isArray(items) || !items.length) throw new TypeError("queue items must be non-empty");
    const frozenItems = items.map(freezeItem);
    const entryIds = new Set(frozenItems.map(item => item.entryId));
    if (entryIds.size !== frozenItems.length) {
      throw new TypeError("queue entry IDs must be unique");
    }
    if (!Number.isInteger(currentIndex) || currentIndex < 0 || currentIndex >= frozenItems.length) {
      throw new RangeError("queue currentIndex is out of range");
    }
    if (!String(sessionId || "").trim()) throw new TypeError("queue sessionId must be non-empty");
    if (mode === "standalone" && frozenItems.length !== 1) {
      throw new TypeError("standalone queue must contain exactly one song");
    }
    return Object.freeze({
      version: VERSION,
      mode,
      items: Object.freeze(frozenItems),
      currentIndex,
      sessionId: String(sessionId),
    });
  };

  const standalone = (item, sessionId) => create({
    mode: "standalone",
    items: [item],
    currentIndex: 0,
    sessionId,
  });

  const rebuild = (state, items, currentIndex = state.currentIndex, mode = state.mode) => create({
    mode,
    items,
    currentIndex,
    sessionId: state.sessionId,
  });

  const removeExistingEntry = (state, item) => {
    const index = item.entryId
      ? state.items.findIndex(candidate => candidate.entryId === item.entryId)
      : -1;
    if (index < 0) return { items: [...state.items], currentIndex: state.currentIndex, index };
    const items = [...state.items];
    items.splice(index, 1);
    return {
      items,
      currentIndex: state.currentIndex - (index < state.currentIndex ? 1 : 0),
      index,
    };
  };

  const playNow = (state, item) => {
    if (!state) return standalone(item, globalThis.crypto?.randomUUID?.() || `queue-${Date.now()}`);
    if (item.entryId && state.items[state.currentIndex].entryId === item.entryId) return state;
    if (!item.entryId && state.items[state.currentIndex].slug === item.slug) return state;
    if (state.mode === "standalone") return standalone(item, state.sessionId);
    const next = removeExistingEntry(state, item);
    const insertionIndex = next.currentIndex + 1;
    next.items.splice(insertionIndex, 0, item);
    return rebuild(state, next.items, insertionIndex);
  };

  const append = (state, item, sessionId) => {
    if (!state) return create({ mode: "custom", items: [item], currentIndex: 0, sessionId });
    return rebuild(state, [...state.items, {...item, entryId: ""}], state.currentIndex, "custom");
  };

  const assertIndex = (state, index) => {
    if (!Number.isInteger(index) || index < 0 || index >= state.items.length) {
      throw new RangeError("queue index is out of range");
    }
  };

  const move = (state, fromIndex, toIndex) => {
    assertIndex(state, fromIndex);
    assertIndex(state, toIndex);
    if (fromIndex <= state.currentIndex || toIndex <= state.currentIndex) {
      throw new RangeError("only upcoming queue items may be moved");
    }
    if (fromIndex === toIndex) return state;
    const items = [...state.items];
    const [item] = items.splice(fromIndex, 1);
    items.splice(toIndex, 0, item);
    return rebuild(state, items);
  };

  const remove = (state, index) => {
    assertIndex(state, index);
    if (index <= state.currentIndex) throw new RangeError("current or played songs cannot be removed");
    const items = [...state.items];
    items.splice(index, 1);
    return rebuild(state, items);
  };

  const reorderUpcoming = (state, orderedEntryIds) => {
    const upcoming = state.items.slice(state.currentIndex + 1);
    if (!Array.isArray(orderedEntryIds)
      || orderedEntryIds.length !== upcoming.length
      || new Set(orderedEntryIds).size !== orderedEntryIds.length) {
      throw new TypeError("upcoming order must contain every upcoming entry exactly once");
    }
    const byEntryId = new Map(upcoming.map(item => [item.entryId, item]));
    const reordered = orderedEntryIds.map(entryId => byEntryId.get(entryId));
    if (reordered.some(item => !item)) {
      throw new TypeError("upcoming order contains an entry outside the upcoming queue");
    }
    return rebuild(state, [
      ...state.items.slice(0, state.currentIndex + 1),
      ...reordered,
    ]);
  };

  const advance = state => state.currentIndex + 1 < state.items.length
    ? { state: rebuild(state, state.items, state.currentIndex + 1), advanced: true }
    : { state, advanced: false };

  const fisherYates = (items, random) => {
    const shuffled = [...items];
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(random() * (index + 1));
      [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
    }
    return shuffled;
  };

  const shuffle = (items, random, sessionId) => create({
    mode: "shuffle",
    items: fisherYates(items, random),
    currentIndex: 0,
    sessionId,
  });

  const shuffleRemaining = (state, random) => rebuild(state, [
    ...state.items.slice(0, state.currentIndex + 1),
    ...fisherYates(state.items.slice(state.currentIndex + 1), random),
  ]);

  const catalogueMap = catalogue => catalogue instanceof Map
    ? catalogue
    : new Map((catalogue || []).map(item => [item.queueId, item]));

  const base64UrlEncode = text => {
    if (typeof Buffer !== "undefined") return Buffer.from(text, "utf8").toString("base64url");
    const bytes = new TextEncoder().encode(text);
    let binary = "";
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };

  const base64UrlDecode = payload => {
    if (!/^[A-Za-z0-9_-]+$/.test(payload)) throw new TypeError("invalid base64url payload");
    if (typeof Buffer !== "undefined") return Buffer.from(payload, "base64url").toString("utf8");
    const padded = payload.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const binary = atob(padded);
    return new TextDecoder().decode(Uint8Array.from(binary, character => character.charCodeAt(0)));
  };

  const encode = state => base64UrlEncode(JSON.stringify({
    v: VERSION,
    m: state.mode,
    q: state.items.map(item => item.queueId),
    i: state.currentIndex,
  }));

  const decode = (payload, catalogue, sessionId, maximum) => {
    if (typeof payload !== "string" || !payload.length || payload.length > MAX_PAYLOAD_CHARACTERS) return null;
    try {
      const value = JSON.parse(base64UrlDecode(payload));
      if (value?.v !== VERSION || !MODES.has(value?.m) || !Array.isArray(value?.q)) return null;
      if (!Number.isInteger(maximum) || maximum < 1 || !value.q.length || value.q.length > maximum) return null;
      if (!value.q.every(queueId => typeof queueId === "string" && queueId)) return null;
      const byId = catalogueMap(catalogue);
      const items = value.q.map(queueId => byId.get(queueId));
      if (items.some(item => !item)) return null;
      return create({ mode: value.m, items, currentIndex: value.i, sessionId });
    } catch (_) {
      return null;
    }
  };

  const restore = (serialized, catalogue) => {
    try {
      const value = JSON.parse(serialized);
      if (value?.version !== VERSION || !Array.isArray(value?.items)) return null;
      const byId = catalogueMap(catalogue);
      const items = value.items.map(item => {
        const catalogueItem = byId.get(item?.queueId);
        return catalogueItem ? {...catalogueItem, entryId: item?.entryId} : null;
      });
      if (items.some(item => !item)) return null;
      return create({
        mode: value.mode,
        items,
        currentIndex: value.currentIndex,
        sessionId: value.sessionId,
      });
    } catch (_) {
      return null;
    }
  };

  const api = Object.freeze({
    VERSION,
    create,
    standalone,
    playNow,
    append,
    move,
    remove,
    reorderUpcoming,
    advance,
    shuffle,
    shuffleRemaining,
    encode,
    decode,
    restore,
  });

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.BHAKTI_QUEUE = api;
})();
