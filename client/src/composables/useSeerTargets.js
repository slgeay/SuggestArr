import axios from 'axios';

let cachedTargets = null;
let loadPromise = null;

/**
 * Load configured Seer targets from the API (cached for the session).
 *
 * @returns {Promise<Array<{id: string, label: string, configured: boolean, web_url: string}>>}
 */
export async function fetchSeerTargets(force = false) {
  if (cachedTargets && !force) {
    return cachedTargets;
  }
  if (!loadPromise || force) {
    loadPromise = axios.get('/api/seer/targets')
      .then(({ data }) => {
        cachedTargets = data.targets || [];
        return cachedTargets;
      })
      .catch(() => {
        cachedTargets = [];
        return cachedTargets;
      });
  }
  return loadPromise;
}

/**
 * Build a per-item request tracking key including the Seer target.
 *
 * @param {object} item Item with id and media_type fields.
 * @param {string} seerTarget ``primary`` or ``secondary``.
 * @returns {string}
 */
export function seerRequestKey(item, seerTarget = 'primary') {
  return `${item.id}-${item.media_type}-${seerTarget}`;
}

/**
 * Return true when two or more Seer targets are configured.
 *
 * @param {Array} targets Target list from ``fetchSeerTargets``.
 * @returns {boolean}
 */
export function hasDualSeer(targets) {
  return Array.isArray(targets) && targets.filter((target) => target.configured).length >= 2;
}
