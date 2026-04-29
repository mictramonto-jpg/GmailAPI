/**
 * Cache.gs — LLM 分類結果を送信者単位でキャッシュ
 *
 * 目的: 同じ送信者からのメールに対して LLM を毎回呼ばずに済むようにする。
 *  -> API コストを大幅削減 (個人 Gmail は同じメルマガが繰り返し届くため特に有効)
 *
 * 永続化: UserProperties (ユーザーごと、永続。最大 500KB / プロパティ)
 * 構造: { "<provider>:<model>:<sender>": {category, label, archive, markRead, ts} }
 */

const LLM_CACHE_KEY = 'GMAIL_ORG_LLM_CACHE_V1';
const LLM_CACHE_MAX_ENTRIES = 1000;       // メモリ節約のため上限
const LLM_CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;  // 30 日

function _loadCache() {
  const raw = PropertiesService.getUserProperties().getProperty(LLM_CACHE_KEY);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch (e) {
    return {};
  }
}

function _saveCache(cache) {
  // 古いエントリを掃除
  const now = Date.now();
  const keys = Object.keys(cache);
  if (keys.length > LLM_CACHE_MAX_ENTRIES) {
    // 古い順に削る
    keys.sort(function(a, b) { return (cache[a].ts || 0) - (cache[b].ts || 0); });
    const toRemove = keys.slice(0, keys.length - LLM_CACHE_MAX_ENTRIES);
    toRemove.forEach(function(k) { delete cache[k]; });
  }
  // TTL 切れも削除
  Object.keys(cache).forEach(function(k) {
    if ((cache[k].ts || 0) + LLM_CACHE_TTL_MS < now) delete cache[k];
  });
  PropertiesService.getUserProperties().setProperty(LLM_CACHE_KEY, JSON.stringify(cache));
}

function _cacheKey(provider, model, sender) {
  return provider + ':' + model + ':' + (sender || '').toLowerCase();
}

function getCachedDecision(provider, model, sender) {
  if (!sender) return null;
  const cache = _loadCache();
  const entry = cache[_cacheKey(provider, model, sender)];
  if (!entry) return null;
  if ((entry.ts || 0) + LLM_CACHE_TTL_MS < Date.now()) return null;
  return entry;
}

function putCachedDecision(provider, model, sender, decision) {
  if (!sender || !decision) return;
  const cache = _loadCache();
  cache[_cacheKey(provider, model, sender)] = Object.assign({}, decision, { ts: Date.now() });
  _saveCache(cache);
}

function clearLlmCache() {
  PropertiesService.getUserProperties().deleteProperty(LLM_CACHE_KEY);
  return { cleared: true };
}

function getLlmCacheStats() {
  const cache = _loadCache();
  const keys = Object.keys(cache);
  const byProvider = {};
  keys.forEach(function(k) {
    const provider = k.split(':')[0];
    byProvider[provider] = (byProvider[provider] || 0) + 1;
  });
  return {
    total: keys.length,
    byProvider: byProvider,
  };
}
