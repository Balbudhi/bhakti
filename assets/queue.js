(() => {
  "use strict";

  const VERSION = 1;
  const SHARE_VERSION = 2;
  const SHUFFLE_DELTA_VERSION = 3;
  const SHUFFLE_ALL_CODE = 3;
  const MAX_PAYLOAD_CHARACTERS = 4096;
  const MODES = new Set(["standalone", "custom", "shuffle"]);
  const MODE_TO_CODE = Object.freeze({
    standalone: 0,
    custom: 1,
    shuffle: 2,
  });
  const CODE_TO_MODE = Object.freeze(
    Object.fromEntries(Object.entries(MODE_TO_CODE).map(([mode, code]) => [code, mode])),
  );
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

  const create = ({ mode, items, currentIndex, sessionId, shuffleSeed = null, shuffleAll = false }) => {
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
    const hasCompactShuffle = mode === "shuffle"
      && shuffleAll === true
      && Number.isInteger(shuffleSeed)
      && shuffleSeed >= 0
      && shuffleSeed <= 0xffffffff;
    return Object.freeze({
      version: VERSION,
      mode,
      items: Object.freeze(frozenItems),
      currentIndex,
      sessionId: String(sessionId),
      shuffleSeed: hasCompactShuffle ? shuffleSeed >>> 0 : null,
      shuffleAll: hasCompactShuffle,
    });
  };

  const standalone = (item, sessionId) => create({
    mode: "standalone",
    items: [item],
    currentIndex: 0,
    sessionId,
  });

  const rebuild = (state, items, currentIndex = state.currentIndex, mode = state.mode, preserveShuffle = false) => create({
    mode,
    items,
    currentIndex,
    sessionId: state.sessionId,
    shuffleSeed: preserveShuffle ? state.shuffleSeed : null,
    shuffleAll: preserveShuffle ? state.shuffleAll : false,
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
    return rebuild(state, next.items, insertionIndex, state.mode, state.shuffleAll);
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
    return rebuild(state, items, state.currentIndex, state.mode, state.shuffleAll);
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
    ], state.currentIndex, state.mode, state.shuffleAll);
  };

  const advance = state => state.currentIndex + 1 < state.items.length
    ? { state: rebuild(state, state.items, state.currentIndex + 1, state.mode, true), advanced: true }
    : { state, advanced: false };

  const fisherYates = (items, random) => {
    const shuffled = [...items];
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(random() * (index + 1));
      [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
    }
    return shuffled;
  };

  const seededRandom = seed => {
    let value = seed >>> 0;
    return () => {
      value = (value + 0x6d2b79f5) >>> 0;
      let mixed = value;
      mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
      mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 0x100000000;
    };
  };

  const shuffle = (items, random, sessionId) => {
    const fullCatalogue = isFullCatalogue(items);
    if (!fullCatalogue) return create({
      mode: "shuffle",
      items: fisherYates(items, random),
      currentIndex: 0,
      sessionId,
    });
    const sample = Math.max(0, Math.min(0.9999999999999999, Number(random()) || 0));
    const shuffleSeed = Math.floor(sample * 0x1000000) >>> 0;
    return create({
      mode: "shuffle",
      items: fisherYates(activeCatalogue(), seededRandom(shuffleSeed)),
      currentIndex: 0,
      sessionId,
      shuffleSeed,
      shuffleAll: true,
    });
  };

  const shuffleRemaining = (state, random) => rebuild(state, [
    ...state.items.slice(0, state.currentIndex + 1),
    ...fisherYates(state.items.slice(state.currentIndex + 1), random),
  ], state.currentIndex, state.mode, state.shuffleAll);

  const catalogueMap = catalogue => catalogue instanceof Map
    ? catalogue
    : new Map((catalogue || []).map(item => [item.queueId, item]));

  const activeCatalogue = catalogue => {
    if (catalogue instanceof Map) return [...catalogue.values()];
    if (Array.isArray(catalogue) && catalogue.length) return catalogue;
    const live = globalThis.window?.BHAKTI_SONGS || globalThis.BHAKTI_SONGS || [];
    return Array.isArray(live) ? live : [];
  };

  const isFullCatalogue = items => {
    const songs = activeCatalogue();
    if (!songs.length || items.length !== songs.length) return false;
    const queueIds = new Set(items.map(item => item.queueId));
    return queueIds.size === songs.length && songs.every(song => queueIds.has(song.queueId));
  };

  const catalogueFingerprint = songs => {
    let hash = 0x811c9dc5;
    for (const song of songs) {
      for (const character of String(song.queueId || "")) {
        hash ^= character.charCodeAt(0);
        hash = Math.imul(hash, 0x01000193) >>> 0;
      }
      hash ^= 0xff;
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return ((hash >>> 16) ^ hash) & 0xffff;
  };

  const catalogueIndexMap = catalogue => new Map(
    activeCatalogue(catalogue).map((item, index) => [item.queueId, index]),
  );

  const base64UrlEncodeBytes = bytes => {
    if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64url");
    let binary = "";
    bytes.forEach(byte => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  };

  const base64UrlEncode = text => {
    if (typeof Buffer !== "undefined") return Buffer.from(text, "utf8").toString("base64url");
    const bytes = new TextEncoder().encode(text);
    return base64UrlEncodeBytes(bytes);
  };

  const base64UrlDecodeBytes = payload => {
    if (!/^[A-Za-z0-9_-]+$/.test(payload)) throw new TypeError("invalid base64url payload");
    if (typeof Buffer !== "undefined") return Uint8Array.from(Buffer.from(payload, "base64url"));
    const padded = payload.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const binary = atob(padded);
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  };

  const base64UrlDecode = payload => {
    const bytes = base64UrlDecodeBytes(payload);
    if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("utf8");
    return new TextDecoder().decode(bytes);
  };

  const encodeLegacy = state => base64UrlEncode(JSON.stringify({
    v: VERSION,
    m: state.mode,
    q: state.items.map(item => item.queueId),
    i: state.currentIndex,
  }));

  const writeVarint = (value, bytes) => {
    if (!Number.isInteger(value) || value < 0) throw new RangeError("varint value must be a non-negative integer");
    let remaining = value;
    while (remaining >= 0x80) {
      bytes.push((remaining & 0x7f) | 0x80);
      remaining >>>= 7;
    }
    bytes.push(remaining);
  };

  const readVarint = (bytes, offsetRef) => {
    let value = 0;
    let shift = 0;
    while (offsetRef.index < bytes.length) {
      const byte = bytes[offsetRef.index++];
      value |= (byte & 0x7f) << shift;
      if ((byte & 0x80) === 0) return value;
      shift += 7;
      if (shift > 28) throw new RangeError("varint is too large");
    }
    throw new RangeError("truncated varint");
  };

  const writeUint32 = (value, bytes) => {
    bytes.push((value >>> 24) & 0xff, (value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff);
  };

  const readUint32 = (bytes, offsetRef) => {
    if (offsetRef.index + 4 > bytes.length) throw new RangeError("truncated uint32");
    const value = ((bytes[offsetRef.index] << 24) >>> 0)
      | (bytes[offsetRef.index + 1] << 16)
      | (bytes[offsetRef.index + 2] << 8)
      | bytes[offsetRef.index + 3];
    offsetRef.index += 4;
    return value >>> 0;
  };

  const writeUint24 = (value, bytes) => {
    bytes.push((value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff);
  };

  const readUint24 = (bytes, offsetRef) => {
    if (offsetRef.index + 3 > bytes.length) throw new RangeError("truncated uint24");
    const value = (bytes[offsetRef.index] << 16)
      | (bytes[offsetRef.index + 1] << 8)
      | bytes[offsetRef.index + 2];
    offsetRef.index += 3;
    return value >>> 0;
  };

  const encode = state => {
    const songs = activeCatalogue();
    const indexByQueueId = catalogueIndexMap(songs);
    if (!indexByQueueId.size) return encodeLegacy(state);
    const fingerprint = catalogueFingerprint(songs);
    // Share v2 is binary: version, mode, catalogue fingerprint, current index,
    // count, then catalogue-index varints. A full-library shuffle stores its
    // reproducible 32-bit seed instead of all 229 shuffled indices.
    if (state.mode === "shuffle" && state.shuffleAll && Number.isInteger(state.shuffleSeed)) {
      const baseItems = fisherYates(songs, seededRandom(state.shuffleSeed));
      const working = baseItems.map(item => item.queueId);
      const target = state.items.map(item => item.queueId);
      const moves = [];
      for (let targetIndex = 0; targetIndex < target.length; targetIndex += 1) {
        const fromIndex = working.indexOf(target[targetIndex], targetIndex);
        if (fromIndex < 0) return encodeLegacy(state);
        if (fromIndex === targetIndex) continue;
        const [queueId] = working.splice(fromIndex, 1);
        working.splice(targetIndex, 0, queueId);
        moves.push([fromIndex, targetIndex]);
      }
      if (state.shuffleSeed > 0xffffff) {
        if (moves.length) return encodeLegacy(state);
        const payload = [SHARE_VERSION, SHUFFLE_ALL_CODE, fingerprint >>> 8, fingerprint & 0xff];
        writeVarint(state.currentIndex, payload);
        writeVarint(songs.length, payload);
        writeUint32(state.shuffleSeed, payload);
        return base64UrlEncodeBytes(payload);
      }
      const payload = [SHUFFLE_DELTA_VERSION, fingerprint >>> 8, fingerprint & 0xff];
      writeVarint(state.currentIndex, payload);
      writeUint24(state.shuffleSeed, payload);
      writeVarint(moves.length, payload);
      moves.forEach(([fromIndex, toIndex]) => {
        writeVarint(fromIndex, payload);
        writeVarint(toIndex, payload);
      });
      return base64UrlEncodeBytes(payload);
    }
    const payload = [SHARE_VERSION, MODE_TO_CODE[state.mode], fingerprint >>> 8, fingerprint & 0xff];
    writeVarint(state.currentIndex, payload);
    writeVarint(state.items.length, payload);
    for (const item of state.items) {
      const catalogueIndex = indexByQueueId.get(item.queueId);
      if (!Number.isInteger(catalogueIndex) || catalogueIndex < 0) return encodeLegacy(state);
      writeVarint(catalogueIndex, payload);
    }
    return base64UrlEncodeBytes(payload);
  };

  const decodeShuffleAll = (bytes, songs, sessionId, maximum, offsetRef) => {
    const currentIndex = readVarint(bytes, offsetRef);
    const count = readVarint(bytes, offsetRef);
    const shuffleSeed = readUint32(bytes, offsetRef);
    if (offsetRef.index !== bytes.length
      || !Number.isInteger(maximum)
      || maximum < 1
      || count !== songs.length
      || count > maximum) return null;
    return create({
      mode: "shuffle",
      items: fisherYates(songs, seededRandom(shuffleSeed)),
      currentIndex,
      sessionId,
      shuffleSeed,
      shuffleAll: true,
    });
  };

  const decodeShuffleDelta = (bytes, songs, sessionId, maximum) => {
    if (bytes.length < 3 || ((bytes[1] << 8) | bytes[2]) !== catalogueFingerprint(songs)) return null;
    const offsetRef = { index: 3 };
    const currentIndex = readVarint(bytes, offsetRef);
    const shuffleSeed = readUint24(bytes, offsetRef);
    const moveCount = readVarint(bytes, offsetRef);
    if (!Number.isInteger(maximum) || maximum < 1 || songs.length > maximum || moveCount > songs.length) return null;
    const items = fisherYates(songs, seededRandom(shuffleSeed));
    for (let index = 0; index < moveCount; index += 1) {
      const fromIndex = readVarint(bytes, offsetRef);
      const toIndex = readVarint(bytes, offsetRef);
      if (fromIndex >= items.length || toIndex >= items.length) return null;
      const [item] = items.splice(fromIndex, 1);
      items.splice(toIndex, 0, item);
    }
    if (offsetRef.index !== bytes.length) return null;
    return create({
      mode: "shuffle",
      items,
      currentIndex,
      sessionId,
      shuffleSeed,
      shuffleAll: true,
    });
  };

  const decodeCompact = (bytes, catalogue, sessionId, maximum) => {
    const songs = activeCatalogue(catalogue);
    if (!songs.length) return null;
    if (bytes.length < 4 || ((bytes[2] << 8) | bytes[3]) !== catalogueFingerprint(songs)) return null;
    const offsetRef = { index: 4 };
    if (bytes[1] === SHUFFLE_ALL_CODE) return decodeShuffleAll(bytes, songs, sessionId, maximum, offsetRef);
    const mode = CODE_TO_MODE[bytes[1]];
    if (!mode) return null;
    const currentIndex = readVarint(bytes, offsetRef);
    const count = readVarint(bytes, offsetRef);
    if (!Number.isInteger(maximum) || maximum < 1 || count < 1 || count > maximum) return null;
    const items = [];
    for (let index = 0; index < count; index += 1) {
      const catalogueIndex = readVarint(bytes, offsetRef);
      if (!Number.isInteger(catalogueIndex) || catalogueIndex < 0 || catalogueIndex >= songs.length) return null;
      items.push(songs[catalogueIndex]);
    }
    if (offsetRef.index !== bytes.length) return null;
    return create({ mode, items, currentIndex, sessionId });
  };

  const decodeLegacy = (payload, catalogue, sessionId, maximum) => {
    const value = JSON.parse(base64UrlDecode(payload));
    if (value?.v !== VERSION || !MODES.has(value?.m) || !Array.isArray(value?.q)) return null;
    if (!Number.isInteger(maximum) || maximum < 1 || !value.q.length || value.q.length > maximum) return null;
    if (!value.q.every(queueId => typeof queueId === "string" && queueId)) return null;
    const byId = catalogueMap(catalogue);
    const items = value.q.map(queueId => byId.get(queueId));
    if (items.some(item => !item)) return null;
    return create({ mode: value.m, items, currentIndex: value.i, sessionId });
  };

  const decode = (payload, catalogue, sessionId, maximum) => {
    if (typeof payload !== "string" || !payload.length || payload.length > MAX_PAYLOAD_CHARACTERS) return null;
    try {
      const bytes = base64UrlDecodeBytes(payload);
      if (bytes[0] === SHUFFLE_DELTA_VERSION) return decodeShuffleDelta(bytes, activeCatalogue(catalogue), sessionId, maximum);
      if (bytes[0] === SHARE_VERSION) return decodeCompact(bytes, catalogue, sessionId, maximum);
      return decodeLegacy(payload, catalogue, sessionId, maximum);
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
        shuffleSeed: value.shuffleSeed,
        shuffleAll: value.shuffleAll,
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
