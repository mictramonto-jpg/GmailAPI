/**
 * Rules.gs — ルールの読み書きとデフォルト値
 *
 * ルールは PropertiesService の DOCUMENT または USER スコープに JSON で保存する。
 * UI から編集できるが、ここに含まれるデフォルトを初回に書き込む。
 */

const RULES_KEY = 'GMAIL_ORG_RULES_V1';
const SETTINGS_KEY = 'GMAIL_ORG_SETTINGS_V1';

const DEFAULT_RULES = {
  defaultLabel: 'Org/Review',
  rules: [
    {
      name: '請求・支払い',
      match: { subject: '(invoice|請求|支払|領収|receipt|billing)' },
      action: { label: 'Org/Bills', archive: true },
    },
    {
      name: 'カレンダー・会議招待',
      match: { subject: '(invitation|招待|meeting|会議|calendar)' },
      action: { label: 'Org/Calendar', archive: false },
    },
    {
      name: 'GitHub 通知',
      match: { from: '@github\\.com$' },
      action: { label: 'Org/GitHub', archive: true },
    },
    {
      name: 'ニュースレター・販促',
      match: { hasListUnsubscribe: true },
      action: { label: 'Org/Unwanted', archive: true, markRead: true },
    },
  ],
};

const DEFAULT_SETTINGS = {
  query: 'in:inbox newer_than:7d',
  maxMessages: 200,
  llmProvider: 'none',           // 'none' | 'gemini' | 'claude'
  geminiApiKey: '',
  geminiModel: 'gemini-2.5-flash',
  claudeApiKey: '',
  claudeModel: 'claude-opus-4-7',  // Anthropic 推奨デフォルト。コスト重視なら claude-haiku-4-5
  unwantedLabel: 'Org/Unwanted',
  reviewLabel: 'Org/Review',
  whitelist: '',  // 改行区切り。foo@bar.com / @bar.com / /regex/i のいずれか
};

function loadRules() {
  const raw = PropertiesService.getUserProperties().getProperty(RULES_KEY);
  if (!raw) {
    saveRules(DEFAULT_RULES);
    return DEFAULT_RULES;
  }
  try {
    return JSON.parse(raw);
  } catch (e) {
    return DEFAULT_RULES;
  }
}

function saveRules(rules) {
  PropertiesService.getUserProperties().setProperty(RULES_KEY, JSON.stringify(rules));
}

function loadSettings() {
  const raw = PropertiesService.getUserProperties().getProperty(SETTINGS_KEY);
  if (!raw) {
    saveSettings(DEFAULT_SETTINGS);
    return DEFAULT_SETTINGS;
  }
  try {
    return Object.assign({}, DEFAULT_SETTINGS, JSON.parse(raw));
  } catch (e) {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings) {
  PropertiesService.getUserProperties().setProperty(SETTINGS_KEY, JSON.stringify(settings));
}

function resetRulesToDefault() {
  saveRules(DEFAULT_RULES);
  return DEFAULT_RULES;
}
