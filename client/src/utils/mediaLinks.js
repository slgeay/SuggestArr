/**
 * Helpers for building external deep links to a media item.
 */

const TMDB_BASE_URL = 'https://www.themoviedb.org';
const TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p';

/**
 * Normalises a media type to the path segment used by TMDb and Seerr.
 * @param {string} mediaType - 'movie' or 'tv'
 * @returns {string} 'movie' or 'tv'
 */
function mediaPath(mediaType) {
  return mediaType === 'tv' ? 'tv' : 'movie';
}

/**
 * Resolves the TMDb id from an entry, whose shape differs between the
 * requests, suggestions and source payloads. Synthetic source tags such as
 * 'discover' or 'trakt_recommendations' resolve to null.
 * @param {object} entry - Request, suggestion or source object
 * @returns {string|null} TMDb id, or null when the entry carries none
 */
export function resolveTmdbId(entry) {
  if (!entry) return null;
  const id = String(entry.request_id ?? entry.tmdb_id ?? entry.id ?? '');
  return /^\d+$/.test(id) && id !== '0' ? id : null;
}

/**
 * Builds the TMDb page URL for a media item.
 * @param {string} mediaType - 'movie' or 'tv'
 * @param {string|number} tmdbId - TMDb id
 * @returns {string|null} URL, or null when the id is missing
 */
export function tmdbUrl(mediaType, tmdbId) {
  if (!tmdbId) return null;
  return `${TMDB_BASE_URL}/${mediaPath(mediaType)}/${tmdbId}`;
}

/**
 * Builds the Seerr (Overseerr / Jellyseerr) page URL for a media item.
 * @param {string} baseUrl - Configured Seerr base URL
 * @param {string} mediaType - 'movie' or 'tv'
 * @param {string|number} tmdbId - TMDb id
 * @returns {string|null} URL, or null when Seerr is unconfigured or the id is missing
 */
export function seerrUrl(baseUrl, mediaType, tmdbId) {
  if (!baseUrl || !tmdbId) return null;
  return `${String(baseUrl).replace(/\/+$/, '')}/${mediaPath(mediaType)}/${tmdbId}`;
}

/**
 * Builds a poster URL. Metadata stored by SuggestArr holds a full URL while
 * TMDb payloads hold a bare path, so both forms have to be accepted.
 * @param {string} path - Full URL or TMDb poster path
 * @param {string} [size] - TMDb image size segment
 * @returns {string|null} Poster URL, or null when no path is given
 */
export function posterUrl(path, size = 'w92') {
  if (!path) return null;
  return path.startsWith('http') ? path : `${TMDB_IMAGE_BASE_URL}/${size}${path}`;
}

export default {
  resolveTmdbId,
  tmdbUrl,
  seerrUrl,
  posterUrl
};
