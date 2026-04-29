/**
 * Web.gs — Web App エントリポイント
 *
 * デプロイ → 「ウェブアプリ」 → 「自分として実行」 / 「自分のみアクセス」 で公開すると
 * URL がブラウザから開けるダッシュボードになる。
 */

function doGet(e) {
  const tpl = HtmlService.createTemplateFromFile('ui/Index');
  return tpl.evaluate()
    .setTitle('Gmail Organizer')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}
