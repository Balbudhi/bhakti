/* Seeded full-occurrence ordering. Accepted metadata supplies preferences only.
 * MMAS-derived search is optional; default ILS shares the same bounded local search.
 * Scores and weights are engineering hypotheses, not listener qualification.
 */
(() => {
  'use strict';
  const MAX_MATRIX_SIZE = 512;
  const FIELDS = ['integratedLufs', 'truePeakDbfs', 'rmsDbfs', 'centroidHz'];
  const clamp = (x, low, high) => Math.max(low, Math.min(high, x));
  const finite = value => {
    if (!Number.isFinite(value)) throw new TypeError('shuffle cost must be finite');
    return value;
  };
  const integer = (value, low, high, name) => {
    if (!Number.isInteger(value) || value < low || value > high) throw new RangeError(`invalid shuffle ${name}`);
    return value;
  };
  const randomSource = seed => {
    let state = seed >>> 0;
    return () => {
      state = (state + 0x6d2b79f5) >>> 0;
      let mixed = state;
      mixed = Math.imul(mixed ^ (mixed >>> 15), mixed | 1);
      mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
      return ((mixed ^ (mixed >>> 14)) >>> 0) / 0x100000000;
    };
  };
  const shuffleSuffix = (order, prefix, random) => {
    const result = order.slice();
    for (let i = result.length - 1; i > prefix; i--) {
      const j = prefix + Math.floor(random() * (i - prefix + 1));
      [result[i], result[j]] = [result[j], result[i]];
    }
    return result;
  };
  const tagMap = (values, roles = false) => {
    const tags = new Map();
    for (const value of Array.isArray(values) ? values : []) {
      if (!value || typeof value.id !== 'string' || !value.id || !Number.isFinite(value.weight) || value.weight <= 0) continue;
      if (roles && (typeof value.role !== 'string' || !value.role)) continue;
      const key = roles ? JSON.stringify([value.role, value.id]) : value.id;
      tags.set(key, Math.max(tags.get(key) || 0, Math.min(1, value.weight)));
    }
    return tags;
  };
  const overlap = (left, right) => {
    if (!left.size || !right.size) return null;
    let intersection = 0;
    let union = 0;
    for (const [key, value] of left) {
      intersection += Math.min(value, right.get(key) || 0);
      union += Math.max(value, right.get(key) || 0);
    }
    for (const [key, value] of right) if (!left.has(key)) union += value;
    return intersection / union;
  };
  const normalizePhysical = source => FIELDS.map(field => {
    const value = source?.[field];
    if (!Number.isFinite(value)) return null;
    if (field === 'centroidHz') return value > 0 ? clamp(Math.log(value / 20) / Math.log(1000), 0, 1) : null;
    // Scales are clipping ranges, not claims that measurements outside them are invalid.
    return clamp((value + 60) / (field === 'truePeakDbfs' ? 63 : 60), 0, 1);
  });
  const project = profile => {
    const semantic = profile?.semantic?.status === 'accepted' ? profile.semantic : {};
    const physical = profile?.audio?.status === 'accepted' ? profile.audio.physical : null;
    const result = {
      themes: tagMap(semantic.themes),
      actions: tagMap(semantic.actions),
      subjects: tagMap(semantic.subjects, true),
      body: normalizePhysical({...physical?.whole, ...physical?.profiles?.body}),
      beginning: normalizePhysical(physical?.profiles?.beginning),
      end: normalizePhysical(physical?.profiles?.end),
    };
    result.known = Boolean(result.themes.size || result.actions.size || result.subjects.size
      || [...result.body, ...result.beginning, ...result.end].some(x => x !== null));
    return result;
  };
  const physicalCost = (left, right) => {
    let total = 0;
    for (let i = 0; i < FIELDS.length; i++) {
      if (left[i] !== null && right[i] !== null) total += 2 * Math.abs(left[i] - right[i]) - 1;
    }
    // Missing fields remain neutral on a fixed denominator.
    return total / FIELDS.length;
  };
  const validate = (items, options) => {
    if (!Array.isArray(items)) throw new TypeError('shuffle items must be an array');
    for (const item of items) if (!item || typeof item !== 'object') throw new TypeError('shuffle occurrence must be an object');
    const config = {
      ...options,
      seed: integer(options.seed ?? 0, 0, 0xffffffff, 'seed'),
      fixedPrefix: integer(options.fixedPrefix ?? 0, 0, items.length, 'prefix'),
      windowSize: integer(options.windowSize ?? 4, 0, 16, 'window size'),
      archiveSize: integer(options.archiveSize ?? 8, 1, 32, 'archive size'),
      qualitySlack: options.qualitySlack ?? 0.02,
      algorithm: options.algorithm ?? 'ils',
      constructions: integer(options.budget?.constructions ?? 8, 0, 64, 'construction budget'),
      proposals: integer(options.budget?.localProposals ?? 256, 0, 20000, 'local budget'),
    };
    if (!Number.isFinite(config.qualitySlack) || config.qualitySlack < 0 || config.qualitySlack > 1) throw new RangeError('invalid shuffle quality slack');
    if (!['random', 'ils', 'mmas'].includes(config.algorithm)) throw new TypeError('invalid shuffle algorithm');
    for (const name of ['transitionCost', 'windowCost']) if (config[name] !== undefined && typeof config[name] !== 'function') throw new TypeError(`invalid ${name}`);
    return config;
  };
  const context = (items, config, stats) => {
    const n = items.length;
    const features = items.map(item => project(config.profiles?.[item.queueId]));
    const informative = Boolean(config.transitionCost || config.windowCost || features.some(f => f.known));
    // Small fixed-size cache only. Large queues use bounded linear scans.
    const cache = n <= MAX_MATRIX_SIZE ? new Float64Array(n * n).fill(NaN) : null;
    const pair = (a, b) => {
      const key = a * n + b;
      if (cache && !Number.isNaN(cache[key])) return cache[key];
      stats.pairEvaluations++;
      let cost;
      if (config.transitionCost) cost = finite(config.transitionCost(items[a], items[b]));
      else {
        const left = features[a], right = features[b];
        cost = 0;
        for (const [name, weight] of [['themes', 0.5], ['actions', 0.2], ['subjects', 0.2]]) {
          const common = overlap(left[name], right[name]);
          if (common !== null) cost += weight * (1 - 2 * common);
        }
        cost += 0.1 * physicalCost(left.body, right.body) + 0.2 * physicalCost(left.end, right.beginning);
      }
      if (cache) cache[key] = cost;
      return cost;
    };
    const window = (order, position, next) => {
      const start = Math.max(0, position - config.windowSize);
      if (config.windowCost) return finite(config.windowCost(order.slice(start, position).map(i => items[i]), items[next]));
      if (!features[next].known) return 0;
      let repeats = 0, related = 0;
      for (let index = start; index < position; index++) {
        const previous = order[index];
        if (features[previous].known && items[previous].queueId === items[next].queueId) repeats++;
        if ((overlap(features[previous].themes, features[next].themes) || 0) > 0) related++;
      }
      return 0.4 * repeats + 0.25 * Math.max(0, related - 1);
    };
    const extension = (order, next) => (order.length ? pair(order[order.length - 1], next) : 0) + window(order, order.length, next);
    const evaluate = order => {
      stats.fullEvaluations++;
      let total = 0;
      for (let i = config.fixedPrefix; i < order.length; i++) total += (i ? pair(order[i - 1], order[i]) : 0) + window(order, i, order[i]);
      return finite(total);
    };
    return {informative, evaluate, extension};
  };
  const newStats = () => ({constructions:0, extensionEvaluations:0, pairEvaluations:0, fullEvaluations:0, localProposals:0, acceptedMoves:0, archiveSize:0, bestScore:0, fallback:null});
  const score = (items, options = {}) => {
    const config = validate(items, options);
    return context(items, config, newStats()).evaluate(items.map((_, i) => i));
  };
  const order = (items, options = {}) => {
    const config = validate(items, options);
    const stats = newStats();
    const random = randomSource(config.seed);
    const indices = items.map((_, i) => i);
    const baseline = shuffleSuffix(indices, config.fixedPrefix, random);
    // Hold the uniformly sampled fresh starter (up to finite-PRNG discretization).
    const prefix = Math.max(config.fixedPrefix, items.length ? 1 : 0);
    const movable = items.length - prefix;
    const ctx = context(items, config, stats);
    const baselineScore = ctx.evaluate(baseline);
    let best = {order:baseline, score:baselineScore};
    let archive = [best];
    const archiveKeys = new Set([baseline.join(',')]);
    const remember = candidate => {
      if (candidate.score < best.score) best = candidate;
      const threshold = Math.min(baselineScore, best.score + config.qualitySlack * movable);
      archive = archive.filter(value => value.score <= threshold + 1e-12);
      archiveKeys.clear();
      archive.forEach(value => archiveKeys.add(value.order.join(',')));
      const key = candidate.order.join(',');
      if (candidate.score <= threshold + 1e-12 && !archiveKeys.has(key)) archive.push(candidate);
      archive.sort((a, b) => a.score - b.score);
      archive = archive.slice(0, config.archiveSize);
    };
    const mutate = candidate => {
      const changed = candidate.slice();
      if (movable < 2) return changed;
      const a = prefix + Math.floor(random() * movable);
      let b = prefix + Math.floor(random() * (movable - 1));
      if (b >= a) b++;
      if (random() < 0.5) [changed[a], changed[b]] = [changed[b], changed[a]];
      else changed.splice(b, 0, changed.splice(a, 1)[0]);
      return changed;
    };
    const improve = (candidate, allowance) => {
      let current = {order:candidate, score:ctx.evaluate(candidate)};
      for (let trial = 0; trial < allowance && movable > 1; trial++) {
        stats.localProposals++;
        const changed = mutate(current.order);
        const value = ctx.evaluate(changed);
        if (value < current.score - 1e-12) {
          current = {order:changed, score:value};
          stats.acceptedMoves++;
        }
      }
      return current;
    };
    if (items.length > MAX_MATRIX_SIZE && config.algorithm !== 'random') {
      stats.fallback = config.algorithm === 'mmas' ? 'mmas-to-local-budget' : 'large-local-budget';
      if (ctx.informative && config.constructions > 0) remember(improve(baseline, Math.min(config.proposals, 16)));
    } else if (config.algorithm !== 'random' && ctx.informative && movable > 1 && config.constructions > 0) {
      const allowance = slot => Math.floor((config.proposals - stats.localProposals) / (config.constructions - slot));
      if (config.algorithm === 'ils') {
        for (let slot = 0; slot < config.constructions; slot++) {
          const candidate = slot === 0 ? baseline : (slot % 4 === 0 ? shuffleSuffix(baseline, prefix, random) : mutate(mutate(best.order)));
          stats.constructions++;
          remember(improve(candidate, allowance(slot)));
        }
      } else {
        // MMAS-derived adaptation: frozen generation, best-ant rank deposit,
        // positive clipping, and deterministic stagnation reset. Not ACS.
        const n = items.length;
        const pheromone = new Float64Array(n * n).fill(1);
        let stagnation = 0;
        for (let first = 0; first < config.constructions; first += 4) {
          const previousBest = best.score;
          let generationBest = null;
          for (let slot = first; slot < Math.min(first + 4, config.constructions); slot++) {
            const candidate = baseline.slice(0, prefix);
            const remaining = baseline.slice(prefix);
            while (remaining.length) {
              const previous = candidate[candidate.length - 1];
              const logits = remaining.map(next => {
                stats.extensionEvaluations++;
                const trail = config.disablePheromone ? 0 : Math.log(pheromone[previous * n + next]);
                return clamp(trail - 2 * ctx.extension(candidate, next), -700, 700);
              });
              const largest = Math.max(...logits);
              const weights = logits.map(value => Math.exp(value - largest));
              let chosen;
              if (random() < 0.05) chosen = Math.floor(random() * remaining.length);
              else {
                let draw = random() * weights.reduce((sum, value) => sum + value, 0);
                chosen = weights.length - 1;
                for (let index = 0; index < weights.length; index++) {
                  draw -= weights[index];
                  if (draw <= 0) { chosen = index; break; }
                }
              }
              candidate.push(remaining.splice(chosen, 1)[0]);
            }
            stats.constructions++;
            const improved = improve(candidate, allowance(slot));
            if (!generationBest || improved.score < generationBest.score) generationBest = improved;
            remember(improved);
          }
          for (let i = 0; i < pheromone.length; i++) pheromone[i] = Math.max(0.05, pheromone[i] * 0.8);
          for (let i = prefix; i < generationBest.order.length; i++) {
            const key = generationBest.order[i - 1] * n + generationBest.order[i];
            pheromone[key] = Math.min(4, pheromone[key] + 0.5);
          }
          stagnation = best.score < previousBest - 1e-12 ? 0 : stagnation + 1;
          if (stagnation >= 3) { pheromone.fill(1); stagnation = 0; }
        }
      }
    }
    const selected = archive[Math.floor(random() * archive.length)];
    stats.archiveSize = archive.length;
    stats.bestScore = best.score;
    return {items:selected.order.map(index => items[index]), score:selected.score, baselineScore, stats};
  };
  const api = Object.freeze({order, score});
  globalThis.BHAKTI_SHUFFLE = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
