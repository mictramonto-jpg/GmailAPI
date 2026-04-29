/**
 * Code.gs — エントリポイント (UI からの呼び出し / トリガ用)
 */

// ----- UI からの呼び出し用ラッパー -----

function uiGetSettings() {
  return loadSettings();
}

function uiSaveSettings(settings) {
  saveSettings(settings);
  return loadSettings();
}

function uiGetRules() {
  return loadRules();
}

function uiSaveRules(rules) {
  saveRules(rules);
  return loadRules();
}

function uiResetRules() {
  return resetRulesToDefault();
}

function uiAnalyze(opts) {
  return collectInboxStats(opts || {});
}

function uiRun(opts) {
  return runClassification(opts || {});
}

function uiTestGemini(from, subject) {
  return testGemini(from, subject);
}

// ----- 自動実行 (時間トリガ) -----

const HOURLY_TRIGGER_FN = 'hourlyOrganize';

/**
 * Triggers > Add から手動でも設定できるが、UI ボタンで設定するのを推奨。
 */
function installHourlyTrigger() {
  uninstallHourlyTrigger();
  ScriptApp.newTrigger(HOURLY_TRIGGER_FN).timeBased().everyHours(1).create();
  return 'OK';
}

function uninstallHourlyTrigger() {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === HOURLY_TRIGGER_FN) {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
  return 'OK';
}

function isTriggerInstalled() {
  const triggers = ScriptApp.getProjectTriggers();
  for (let i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === HOURLY_TRIGGER_FN) return true;
  }
  return false;
}

function uiGetTriggerStatus() {
  return { installed: isTriggerInstalled() };
}

function uiInstallTrigger() {
  installHourlyTrigger();
  return uiGetTriggerStatus();
}

function uiUninstallTrigger() {
  uninstallHourlyTrigger();
  return uiGetTriggerStatus();
}

/**
 * 1 時間に 1 回の自動仕分け。新着メールだけ対象にして通常の query をオーバーライド。
 */
function hourlyOrganize() {
  const settings = loadSettings();
  const result = runClassification({
    query: 'in:inbox newer_than:2h',
    max: settings.maxMessages || 200,
    dryRun: false,
  });
  console.log('hourlyOrganize result', JSON.stringify({
    total: result.total,
    counts: result.counts,
  }));
}
