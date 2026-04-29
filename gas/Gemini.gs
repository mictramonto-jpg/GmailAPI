/**
 * Gemini.gs — ルールにマッチしなかったメールを LLM で分類する
 *
 * Gemini API を使う。settings.geminiApiKey が空なら呼ばない。
 * https://ai.google.dev/ で API キーを発行 (無料枠あり)。
 */

function classifyWithGemini(ctx, settings) {
  const key = settings.geminiApiKey;
  if (!key) return null;
  const model = settings.geminiModel || 'gemini-2.5-flash';
  const url = 'https://generativelanguage.googleapis.com/v1beta/models/'
    + encodeURIComponent(model) + ':generateContent?key=' + encodeURIComponent(key);

  const prompt = [
    'あなたは個人 Gmail の自動仕分けアシスタントです。',
    '以下の 1 通のメールを読み、必要 / 不要を判定し JSON で返答してください。',
    '',
    '判定基準:',
    '- 必要 (Important): 仕事の連絡、請求/支払、予約確認、配送通知、認証コード、個人的なやりとり',
    '- 通知 (Notification): SaaS の通知、GitHub/Jira などの自動配信',
    '- 不要 (Unwanted): セール/広告/メルマガ/プロモーション/リクルート営業',
    '',
    'メール:',
    'From: ' + (ctx.from || ''),
    'Subject: ' + (ctx.subject || ''),
    'List-Unsubscribe: ' + (ctx.listUnsubscribe ? 'あり' : 'なし'),
    '',
    '次の JSON スキーマで返答 (他の文字列を出さない):',
    '{"category": "Important|Notification|Unwanted", "reason": "短い理由"}',
  ].join('\n');

  const payload = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: 0.0,
      responseMimeType: 'application/json',
    },
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    console.warn('Gemini API error', res.getResponseCode(), res.getContentText());
    return null;
  }
  const body = JSON.parse(res.getContentText());
  const text = body && body.candidates && body.candidates[0]
    && body.candidates[0].content && body.candidates[0].content.parts
    && body.candidates[0].content.parts[0] && body.candidates[0].content.parts[0].text;
  if (!text) return null;
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return null;
  }
  return decisionFromCategory(parsed.category, parsed.reason, settings);
}

function decisionFromCategory(category, reason, settings) {
  const map = {
    'Important':    { label: 'Org/Important',    archive: false, markRead: false },
    'Notification': { label: 'Org/Notification', archive: true,  markRead: false },
    'Unwanted':     { label: settings.unwantedLabel || 'Org/Unwanted',
                      archive: true, markRead: true },
  };
  const decision = map[category];
  if (!decision) return null;
  return Object.assign({ category: category, reason: reason || '' }, decision);
}

/**
 * UI 検証用: 任意のテキストで Gemini を試す
 */
function testGemini(from, subject) {
  const settings = loadSettings();
  return classifyWithGemini({
    from: from || 'noreply@example.com',
    subject: subject || 'Test message',
    listUnsubscribe: '',
  }, settings);
}
