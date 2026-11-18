/* Lazy, bounded worker ownership. Ordering never owns or mutates playback/queue
 * state: callers adopt a result only if their originating queue is still current.
 */
(() => {
  'use strict';
  const pending = new Map();
  let worker = null;
  let nextId = 0;
  let idleTimer = null;
  const asset = path => new URL(window.BHAKTI_ASSETS?.[path] || path, window.location.href).href;
  const abortError = () => Object.assign(new Error('Shuffle cancelled'), {name:'AbortError'});
  const release = () => {
    clearTimeout(idleTimer);
    idleTimer = null;
    worker?.terminate();
    worker = null;
  };
  const finish = (id, error, result) => {
    const request = pending.get(id);
    if (!request) return;
    pending.delete(id);
    clearTimeout(request.timer);
    request.signal?.removeEventListener('abort', request.abort);
    if (error) request.reject(error);
    else request.resolve(result);
    if (!pending.size && worker) idleTimer = setTimeout(release, 60000);
  };
  const fail = error => {
    release();
    for (const id of pending.keys()) finish(id, error);
  };
  const getWorker = () => {
    if (worker) return worker;
    const instance = new window.Worker(asset('/assets/shuffle-worker.js'));
    worker = instance;
    instance.onmessage = event => {
      if (worker !== instance) return;
      const data = event.data;
      const request = pending.get(data?.id);
      if (!request) return;
      if (typeof data.error === 'string') {
        finish(data.id, new Error(data.error));
        return;
      }
      const indices = data.indices;
      const seen = new Set();
      if (!Array.isArray(indices) || indices.length !== request.items.length || indices.some((index, position) => {
        if (!Number.isInteger(index) || index < 0 || index >= request.items.length || seen.has(index)
          || (position < request.fixedPrefix && position !== index)) return true;
        seen.add(index);
        return false;
      })) {
        finish(data.id, new Error('invalid shuffle permutation'));
        return;
      }
      finish(data.id, null, indices.map(index => request.items[index]));
    };
    const broken = event => {
      if (worker !== instance) return;
      event.preventDefault?.();
      fail(new Error(event.message || 'Shuffle worker communication failed'));
    };
    instance.onerror = broken;
    instance.onmessageerror = broken;
    return instance;
  };
  // Resolve to original occurrence references, preserving duplicates and prefix.
  // An AbortSignal cancels adoption; when nothing remains, terminate computation.
  const order = (items, {fixedPrefix = 0, seed = 0, revision, signal} = {}) => new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(abortError()); return; }
    if (!Array.isArray(items) || items.some(item => !item || typeof item !== 'object')) {
      reject(new TypeError('shuffle items must be occurrence objects')); return;
    }
    if (!Number.isInteger(fixedPrefix) || fixedPrefix < 0 || fixedPrefix > items.length
      || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) {
      reject(new RangeError('invalid shuffle prefix or seed')); return;
    }
    if (typeof revision !== 'string' || !revision) { reject(new Error('missing shuffle revision')); return; }
    const id = ++nextId;
    const request = {resolve, reject, items:items.slice(), fixedPrefix, signal, timer:null, abort:null};
    request.abort = () => {
      finish(id, abortError());
      if (!pending.size) release();
    };
    try {
      clearTimeout(idleTimer);
      idleTimer = null;
      const instance = getWorker();
      pending.set(id, request);
      request.timer = setTimeout(() => fail(new Error('Shuffle worker timed out')), 15000);
      signal?.addEventListener('abort', request.abort, {once:true});
      // Only queue identity affects the engine. Titles/media/glosses never cross
      // the thread boundary, avoiding large structured clones or media access.
      instance.postMessage({id, items:items.map(item => ({queueId:item.queueId})), fixedPrefix, seed, revision,
        engineUrl:asset('/assets/shuffle.js'), profilesUrl:asset('/data/shuffle-profiles.js')});
    } catch (error) {
      if (pending.has(id)) finish(id, error);
      else reject(error);
      if (!pending.size) release();
    }
  });
  window.BHAKTI_SHUFFLE_CLIENT = Object.freeze({order, dispose:() => fail(new Error('Shuffle worker disposed'))});
})();
