/**
 * Claude.gs — Anthropic Claude API でメールを分類する
 *
 * UrlFetchApp で raw HTTP 呼び出し (GAS には Anthropic 公式 SDK がないため)。
 * https://console.anthropic.com/ で API キーを発行 (要クレカ登録)。
 *
 * デフォルトモデル: claude-opus-4-7 (最高性能)。
 * コスト重視なら settings.claudeModel を以下に変更:
 *   - claude-haiku-4-5  (約 1/5 のコスト・分類タスクに十分)
 *   - claude-sonnet-4-6 (中間)
 */

function classifyWithClaude(ctx, settings) {
  const key = settings.claudeApiKey;
  if (!key) return null;
  const model = settings.claudeModel || 'claude-opus-4-7';

  const systemPrompt =
    'あなたは個人 Gmail の自動仕分けアシスタントです。' +
    '判定基準:\n' +
    '- 必要 (Important): 仕事の連絡、請求/支払、予約確認、配送通知、認証コード、個人的なやりとり\n' +
    '- 通知 (Notification): SaaS の通知、GitHub/Jira などの自動配信\n' +
    '- 不要 (Unwanted): セール/広告/メルマガ/プロモーション/リクルート営業';

  const userPrompt =
    'From: ' + (ctx.from || '') + '\n' +
    'Subject: ' + (ctx.subject || '') + '\n' +
    'List-Unsubscribe: ' + (ctx.listUnsubscribe ? 'あり' : 'なし');

  const payload = {
    model: model,
    max_tokens: 256,
    system: systemPrompt,
    messages: [{ role: 'user', content: userPrompt }],
    output_config: {
      format: {
        type: 'json_schema',
        schema: {
          type: 'object',
          properties: {
            category: { type: 'string', enum: ['Important', 'Notification', 'Unwanted'] },
            reason: { type: 'string' },
          },
          required: ['category', 'reason'],
          additionalProperties: false,
        },
      },
    },
  };

  const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
    method: 'post',
    headers: {
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) {
    console.warn('Claude API error', res.getResponseCode(), res.getContentText());
    return null;
  }
  const body = JSON.parse(res.getContentText());
  const block = body && body.content && body.content[0];
  if (!block || block.type !== 'text' || !block.text) return null;

  let parsed;
  try {
    parsed = JSON.parse(block.text);
  } catch (e) {
    return null;
  }
  return decisionFromCategory(parsed.category, parsed.reason, settings);
}

function testClaude(from, subject) {
  const settings = loadSettings();
  return classifyWithClaude({
    from: from || 'newsletter@shop.example',
    subject: subject || '【春のセール】最大50%OFF',
    listUnsubscribe: '',
  }, settings);
}
