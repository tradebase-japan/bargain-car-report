"""
Slack通知モジュール
割安・新着車両の要約を Slack Webhook で投稿する。
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
    new_only: bool = False,
) -> bool:
    """
    Slack Webhook で割安車両の要約を通知する。

    Args:
        bargains:    割安車両リスト
        summary:     サマリー辞書
        report_url:  レポートのURL（GitHub Pages）
        webhook_url: Slack Webhook URL（省略時は環境変数 SLACK_WEBHOOK_URL を使用）
        new_only:    True のとき新着のみ通知（bargains が全件でも新着だけ掲出）
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        log.warning("SLACK_WEBHOOK_URL が設定されていません。Slack通知をスキップします。")
        return False

    targets = [c for c in bargains if c.get("is_new")] if new_only else bargains
    if not targets:
        log.info("通知対象が0件のため Slack 通知をスキップします。")
        return True

    now_str = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")

    if new_only:
        header = f"*🆕 新着・割安認定中古車 {len(targets)}件 検出（{now_str}）*"
    else:
        header = f"*🚗 割安認定中古車レポート（{now_str}）*"

    lines = [header, "━" * 28]

    brand_emoji = {"トヨタ": "🔵", "ホンダ": "🔴"}
    for car in targets:
        be        = brand_emoji.get(car["brand"], "")
        new_badge = "🆕 " if car.get("is_new") else ""
        grade_str = f" {car['grade']}" if car.get("grade") else ""
        lines.append(
            f"{new_badge}{be} *{car['name']}{grade_str}*（{car['year']}年 / "
            f"{car.get('mileage_display', '?')}）"
        )
        lines.append(
            f"　　車両価格: *{car['price']}万円*　"
            f"相場中央値: {car['market_median']}万円　"
            f"*▼{car['discount']}万円安（{car['discount_pct']}%オフ）*"
        )
        shop = car.get("shop", "")
        pref = car.get("pref", "")
        if shop or pref:
            lines.append(f"　　📍 {pref} {shop}")
        lines.append(f"　　🔗 {car.get('url', '#')}")
        lines.append("")

    lines.append("─" * 28)
    new_count = summary.get("new_count", 0)
    lines.append(
        f"📊 割安検知: *{summary['count']}件*"
        + (f"（うち新着: {new_count}件）" if new_count else "")
        + f"　平均割安額: *{summary['avg_discount']}万円*"
    )
    if report_url:
        lines.append(f"📋 詳細レポート → {report_url}")

    payload = {"text": "\n".join(lines)}

    try:
        resp = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("Slack通知送信完了 (%d件)", len(targets))
            return True
        else:
            log.warning("Slack通知失敗: HTTP %d %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as e:
        log.warning("Slack通知エラー: %s", e)
        return False
