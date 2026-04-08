"""
Slack通知モジュール
割安車両の要約を Slack Webhook で投稿する。
"""
import json
import logging
import os
import datetime
import requests

log = logging.getLogger(__name__)


def notify_slack(
    bargains: list[dict],
    summary: dict,
    report_url: str = "",
    webhook_url: str = "",
) -> bool:
    """
    Slack Webhook で割安車両の要約を通知する。

    Args:
        bargains: 割安車両リスト
        summary: サマリー辞書
        report_url: レポートのURL（GitHub Pages）
        webhook_url: Slack Webhook URL（省略時は環境変数 SLACK_WEBHOOK_URL を使用）

    Returns:
        成功した場合 True
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        log.warning("SLACK_WEBHOOK_URL が設定されていません。Slack通知をスキップします。")
        return False

    today = datetime.date.today().strftime("%Y/%m/%d")
    lines = [f"*🚗 割安認定中古車レポート（{today}）*", "━" * 24]

    brand_emoji = {"トヨタ": "🔵", "ホンダ": "🔴"}
    for car in bargains:
        emoji = "🆕 " if car.get("is_new") else ""
        be = brand_emoji.get(car["brand"], "")
        lines.append(
            f"{emoji}{be} *{car['name']} {car['grade']}*（{car['year']}年）　"
            f"*−{car['discount']}万円*　相場中央値 {car['market_median']}万円"
        )

    lines.append("")
    lines.append(
        f"📊 検知: *{summary['count']}件* ／ 平均割安額: *{summary['avg_discount']}万円*"
    )
    if report_url:
        lines.append(f"🔗 詳細レポート → {report_url}")

    payload = {"text": "\n".join(lines)}

    try:
        resp = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("Slack通知送信完了")
            return True
        else:
            log.warning("Slack通知失敗: HTTP %d %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as e:
        log.warning("Slack通知エラー: %s", e)
        return False
