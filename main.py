"""
割安認定中古車レポート 自動生成スクリプト
GitHub Actions から呼び出されるエントリーポイント。
"""
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from scripts.fetch_listings  import fetch_all_listings
from scripts.fetch_market    import fetch_market_listings
from scripts.track_seen      import load_seen_ids, save_seen_ids, mark_new_listings, update_seen_ids
from scripts.analyze         import find_bargains, summarize
from scripts.generate_report import generate_report
from scripts.notify_slack    import notify_slack

USE_DEMO       = os.environ.get("USE_DEMO",       "false").lower() != "false"
USE_MARKET     = os.environ.get("USE_MARKET",     "true").lower()  != "false"
OUTPUT_PATH    = os.environ.get("OUTPUT_PATH",    "output/index.html")
REPORT_URL     = os.environ.get("REPORT_URL",     "")
SLACK_WEBHOOK  = os.environ.get("SLACK_WEBHOOK_URL", "")
SEEN_IDS_PATH  = os.environ.get("SEEN_IDS_PATH",  "seen_ids.json")


def main() -> None:
    logging.info("=== 割安認定中古車レポート 開始 ===")

    # ── 1. 公式ディーラーから物件取得 ────────────────────────
    listings = fetch_all_listings(use_demo=USE_DEMO)

    # ── 2. 新着検出（seen_ids との差分） ──────────────────────
    seen_ids = load_seen_ids(SEEN_IDS_PATH)
    listings = mark_new_listings(listings, seen_ids)

    new_count = sum(1 for c in listings if c.get("is_new"))
    logging.info("新着物件: %d件 / 全 %d件", new_count, len(listings))

    # ── 3. 市場相場データ取得（グーネット） ───────────────────
    market_listings: "list[dict] | None" = None
    if USE_MARKET and not USE_DEMO:
        market_listings = fetch_market_listings(max_pages=3)
        if not market_listings:
            logging.warning("市場データ取得0件。listings 内部比較にフォールバック")

    # ── 4. 割安分析 ──────────────────────────────────────────
    bargains = find_bargains(
        listings,
        market_listings=market_listings,
        discount_threshold=10,
        top_n=10,
        min_peers=2,
    )
    summary = summarize(bargains)
    logging.info(
        "割安車両: %d件（うち新着 %d件 / 平均割安額 %s万円）",
        summary["count"], summary.get("new_count", 0), summary["avg_discount"],
    )

    # ── 5. HTMLレポート生成（全割安件を掲載） ─────────────────
    out_path = generate_report(bargains, summary, output_path=OUTPUT_PATH)
    logging.info("レポート出力: %s", out_path)

    # ── 6. Slack 通知（新着割安が1件以上のとき） ──────────────
    if SLACK_WEBHOOK:
        has_new_bargain = any(c.get("is_new") for c in bargains)
        if has_new_bargain:
            notify_slack(
                bargains, summary,
                report_url=REPORT_URL,
                webhook_url=SLACK_WEBHOOK,
                new_only=True,
            )
        else:
            logging.info("新着割安物件なし → Slack 通知をスキップ")
    else:
        logging.info("SLACK_WEBHOOK_URL 未設定のため通知をスキップ")

    # ── 7. seen_ids を更新・保存 ──────────────────────────────
    updated_seen = update_seen_ids(seen_ids, listings)
    save_seen_ids(updated_seen, SEEN_IDS_PATH)

    logging.info("=== 完了 ===")


if __name__ == "__main__":
    main()
