/* Existing shuffle algorithm runs unchanged, with only verified matching public
 * profiles. Return indices rather than cloned occurrences to preserve identity.
 */
'use strict';
self.window = self; // Public profile bundle uses the browser's window namespace.
let loaded = false;
self.onmessage = event => {
  const request = event.data;
  const id = request?.id;
  try {
    if (!Number.isSafeInteger(id) || id < 1) throw new Error('invalid shuffle request');
    if (!loaded) {
      importScripts(request.engineUrl, request.profilesUrl);
      loaded = true;
    }
    const bundle = self.BHAKTI_SHUFFLE_PROFILES;
    if (bundle?.schemaVersion !== 1 || bundle.taxonomyVersion !== 1
      || typeof request.revision !== 'string' || !request.revision || bundle.revision !== request.revision
      || !bundle.profiles || typeof bundle.profiles !== 'object') {
      throw new Error('Shuffle profile revision or schema mismatch');
    }
    const items = request.items;
    const result = self.BHAKTI_SHUFFLE.order(items, {fixedPrefix:request.fixedPrefix,
      seed:request.seed, profiles:bundle.profiles});
    const positions = new Map(items.map((item,index) => [item,index]));
    self.postMessage({id, indices:result.items.map(item => positions.get(item))});
  } catch (error) {
    self.postMessage({id, error:error?.message || 'Shuffle worker failed'});
  }
};
