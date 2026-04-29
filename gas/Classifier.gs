/**
 * Classifier.gs — ルールベースのメール分類
 *
 * Gmail Advanced Service (Gmail.Users.Messages.get) を使ってヘッダを取得し、
 * ルールにマッチしたら最初の 1 件を返す。
 */

function _compile(pattern) {
  if (!pattern) return null;
  return new RegExp(pattern, 'i');
}

function _header(headers, name) {
  if (!headers) return '';
  const lower = name.toLowerCase();
  for (let i = 0; i < headers.length; i++) {
    if (headers[i].name.toLowerCase() === lower) return headers[i].value || '';
  }
  return '';
}

function parseListUnsubscribe(value) {
  const urls = [];
  const mailtos = [];
  if (!value) return { urls: urls, mailtos: mailtos };
  const tokens = value.match(/<([^>]+)>/g) || [];
  tokens.forEach(function(t) {
    const inner = t.slice(1, -1).trim();
    if (/^mailto:/i.test(inner)) mailtos.push(inner);
    else if (/^https?:/i.test(inner)) urls.push(inner);
  });
  return { urls: urls, mailtos: mailtos };
}

function normalizeSender(raw) {
  if (!raw) return '';
  const m = raw.match(/<([^>]+)>/);
  return (m ? m[1] : raw).trim().toLowerCase();
}

function senderDomain(addr) {
  const at = addr.indexOf('@');
  return at >= 0 ? addr.slice(at + 1) : addr;
}

/**
 * settings.whitelist (改行区切り) の各行を、送信者のメアドまたはドメインと一致するか確認。
 * - 完全一致 (foo@bar.com)
 * - ドメイン一致 (@bar.com or bar.com)
 * - 正規表現 (/^foo.*@bar\.com$/i のように / で囲む)
 */
function isWhitelisted(senderAddr, settings) {
  const text = (settings && settings.whitelist) || '';
  if (!text || !senderAddr) return false;
  const lower = senderAddr.toLowerCase();
  const dom = senderDomain(lower);
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.charAt(0) === '#') continue;
    if (line.charAt(0) === '/' && line.lastIndexOf('/') > 0) {
      // /pattern/flags
      const last = line.lastIndexOf('/');
      const pattern = line.slice(1, last);
      const flags = line.slice(last + 1) || 'i';
      try {
        if (new RegExp(pattern, flags).test(lower)) return true;
      } catch (e) { /* invalid regex, skip */ }
      continue;
    }
    const norm = line.toLowerCase().replace(/^@/, '');
    if (norm.indexOf('@') >= 0) {
      if (norm === lower) return true;
    } else {
      if (norm === dom) return true;
    }
  }
  return false;
}

/**
 * 1 件のメッセージ (Gmail API のリソース) をルールに照らして判定する。
 * @return {{rule: object|null, headers: object}}
 */
function classifyMessage(msg, rules) {
  const headers = msg.payload && msg.payload.headers ? msg.payload.headers : [];
  const ctx = {
    from: _header(headers, 'From'),
    subject: _header(headers, 'Subject'),
    listUnsubscribe: _header(headers, 'List-Unsubscribe'),
    listUnsubscribePost: _header(headers, 'List-Unsubscribe-Post'),
  };

  for (let i = 0; i < rules.length; i++) {
    const r = rules[i];
    const m = r.match || {};
    const fromRe = _compile(m.from);
    const subjectRe = _compile(m.subject);
    if (fromRe && !fromRe.test(ctx.from)) continue;
    if (subjectRe && !subjectRe.test(ctx.subject)) continue;
    if (m.hasListUnsubscribe === true && !ctx.listUnsubscribe) continue;
    if (m.hasListUnsubscribe === false && ctx.listUnsubscribe) continue;
    return { rule: r, ctx: ctx };
  }
  return { rule: null, ctx: ctx };
}

/**
 * 受信トレイから対象メールを取得して分類する。dryRun=true なら適用しない。
 * @return 結果サマリと unsubscribe 一覧
 */
function runClassification(opts) {
  opts = opts || {};
  const settings = loadSettings();
  const rulesData = loadRules();
  const rules = rulesData.rules || [];
  const defaultLabel = rulesData.defaultLabel;

  const query = opts.query || settings.query;
  const max = Math.min(parseInt(opts.max || settings.maxMessages, 10) || 200, 500);
  const dryRun = !!opts.dryRun;
  const provider = settings.llmProvider || 'none';
  const useLLM = (provider === 'gemini' && !!settings.geminiApiKey)
              || (provider === 'claude' && !!settings.claudeApiKey);

  const list = Gmail.Users.Messages.list('me', { q: query, maxResults: max });
  const messages = list.messages || [];

  const counts = {};
  const unsubIndex = {};   // sender -> {subjects, urls, mailtos, oneClick}
  const previews = [];

  for (let i = 0; i < messages.length; i++) {
    const id = messages[i].id;
    let msg;
    try {
      msg = Gmail.Users.Messages.get('me', id, {
        format: 'metadata',
        metadataHeaders: ['From', 'Subject', 'List-Unsubscribe', 'List-Unsubscribe-Post'],
      });
    } catch (e) {
      continue;
    }
    const result = classifyMessage(msg, rules);
    let rule = result.rule;
    const ctx = result.ctx;

    // ホワイトリスト判定 (最優先・LLM もルールも適用しない)
    const senderAddr = normalizeSender(ctx.from);
    if (isWhitelisted(senderAddr, settings)) {
      counts['Whitelist (skipped)'] = (counts['Whitelist (skipped)'] || 0) + 1;
      if (previews.length < 100) {
        previews.push({
          id: id, from: ctx.from, subject: ctx.subject,
          rule: 'Whitelist', action: '(no-op)', llm: false, provider: '',
        });
      }
      continue;
    }

    // LLM フォールバック (ルールにマッチしなかった & プロバイダ有効)
    let llmUsed = false;
    let llmProviderUsed = '';
    let llmCacheHit = false;
    if (!rule && useLLM) {
      try {
        const model = (provider === 'claude') ? settings.claudeModel : settings.geminiModel;
        let decision = getCachedDecision(provider, model, senderAddr);
        if (decision) {
          llmCacheHit = true;
        } else {
          decision = (provider === 'claude')
            ? classifyWithClaude(ctx, settings)
            : classifyWithGemini(ctx, settings);
          if (decision) putCachedDecision(provider, model, senderAddr, decision);
        }
        if (decision && decision.label) {
          rule = {
            name: provider + ': ' + decision.category + (llmCacheHit ? ' (cached)' : ''),
            action: {
              label: decision.label,
              archive: !!decision.archive,
              markRead: !!decision.markRead,
            },
          };
          llmUsed = true;
          llmProviderUsed = provider + (llmCacheHit ? '*' : '');
        }
      } catch (e) {
        // 失敗時は default に流す
      }
    }

    if (!rule && defaultLabel) {
      rule = { name: '(default)', action: { label: defaultLabel } };
    }

    if (!rule) {
      counts['__skip__'] = (counts['__skip__'] || 0) + 1;
      continue;
    }

    const action = rule.action || {};
    const summary = applyAction(id, action, dryRun);
    counts[rule.name] = (counts[rule.name] || 0) + 1;

    if (previews.length < 100) {
      previews.push({
        id: id,
        from: ctx.from,
        subject: ctx.subject,
        rule: rule.name,
        action: summary,
        llm: llmUsed,
        provider: llmProviderUsed,
      });
    }

    // Unsubscribe index 収集
    if (ctx.listUnsubscribe) {
      const parsed = parseListUnsubscribe(ctx.listUnsubscribe);
      const sender = normalizeSender(ctx.from);
      if (!unsubIndex[sender]) {
        unsubIndex[sender] = { subjects: {}, urls: {}, mailtos: {}, oneClick: false };
      }
      unsubIndex[sender].subjects[ctx.subject.slice(0, 80)] = true;
      parsed.urls.forEach(function(u) { unsubIndex[sender].urls[u] = true; });
      parsed.mailtos.forEach(function(m) { unsubIndex[sender].mailtos[m] = true; });
      if ((ctx.listUnsubscribePost || '').toLowerCase().indexOf('one-click') >= 0) {
        unsubIndex[sender].oneClick = true;
      }
    }
  }

  // Set 化していたものを配列に戻す
  const unsubList = Object.keys(unsubIndex).map(function(sender) {
    const e = unsubIndex[sender];
    return {
      sender: sender,
      oneClick: e.oneClick,
      urls: Object.keys(e.urls),
      mailtos: Object.keys(e.mailtos),
      subjects: Object.keys(e.subjects),
    };
  }).sort(function(a, b) { return b.subjects.length - a.subjects.length; });

  return {
    query: query,
    total: messages.length,
    dryRun: dryRun,
    counts: counts,
    previews: previews,
    unsubscribe: unsubList,
  };
}

/**
 * action オブジェクトを適用する。dryRun なら DOM 変更せず文字列だけ返す。
 */
function applyAction(messageId, action, dryRun) {
  const parts = [];
  let labelObj = null;
  if (action.label) {
    parts.push('+' + action.label);
    if (!dryRun) labelObj = ensureLabel(action.label);
  }
  if (action.archive) parts.push('archive');
  if (action.markRead) parts.push('read');
  if (action.trash) parts.push('TRASH');

  if (dryRun) return parts.join(',') || '(no-op)';

  if (action.trash) {
    Gmail.Users.Messages.trash('me', messageId);
    return parts.join(',');
  }

  const addLabelIds = labelObj ? [labelObj.getId()] : [];
  const removeLabelIds = [];
  if (action.archive) removeLabelIds.push('INBOX');
  if (action.markRead) removeLabelIds.push('UNREAD');

  if (addLabelIds.length || removeLabelIds.length) {
    Gmail.Users.Messages.modify({
      addLabelIds: addLabelIds,
      removeLabelIds: removeLabelIds,
    }, 'me', messageId);
  }
  return parts.join(',') || '(no-op)';
}

const _LABEL_CACHE = {};
function ensureLabel(name) {
  if (_LABEL_CACHE[name]) return _LABEL_CACHE[name];
  let lbl = GmailApp.getUserLabelByName(name);
  if (!lbl) lbl = GmailApp.createLabel(name);
  _LABEL_CACHE[name] = lbl;
  return lbl;
}

/**
 * 受信トレイの送信者統計を返す (UI のダッシュボード用)。
 */
function collectInboxStats(opts) {
  opts = opts || {};
  const settings = loadSettings();
  const query = opts.query || settings.query;
  const max = Math.min(parseInt(opts.max || settings.maxMessages, 10) || 200, 500);

  const list = Gmail.Users.Messages.list('me', { q: query, maxResults: max });
  const messages = list.messages || [];

  const senderCount = {};
  const domainCount = {};
  const unsubCount = {};

  for (let i = 0; i < messages.length; i++) {
    let msg;
    try {
      msg = Gmail.Users.Messages.get('me', messages[i].id, {
        format: 'metadata',
        metadataHeaders: ['From', 'List-Unsubscribe'],
      });
    } catch (e) { continue; }
    const headers = msg.payload && msg.payload.headers ? msg.payload.headers : [];
    const sender = normalizeSender(_header(headers, 'From'));
    if (!sender) continue;
    senderCount[sender] = (senderCount[sender] || 0) + 1;
    const dom = senderDomain(sender);
    domainCount[dom] = (domainCount[dom] || 0) + 1;
    if (_header(headers, 'List-Unsubscribe')) {
      unsubCount[sender] = (unsubCount[sender] || 0) + 1;
    }
  }

  const top = function(obj, n) {
    return Object.keys(obj)
      .map(function(k) { return { key: k, count: obj[k] }; })
      .sort(function(a, b) { return b.count - a.count; })
      .slice(0, n);
  };

  return {
    query: query,
    total: messages.length,
    uniqueSenders: Object.keys(senderCount).length,
    uniqueDomains: Object.keys(domainCount).length,
    promoSenders: Object.keys(unsubCount).length,
    topSenders: top(senderCount, 20).map(function(x) {
      return Object.assign(x, { isPromo: !!unsubCount[x.key] });
    }),
    topDomains: top(domainCount, 20),
    topPromo: top(unsubCount, 20),
  };
}
