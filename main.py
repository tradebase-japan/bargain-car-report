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
from scripts.analyze         import find_bargains, summarize
from scripts.generate_report import generate_report
from scripts.notify_slack    import notify_slack

USE_DEMO       = os.environ.get("USE_DEMO", "false").lower() != "false"
OUTPUT_PATH    = os.environ.get("OUTPUT_PATH", "output/index.html")
REPORT_URL     = os.environ.get("REPORT_URL", "")
SLACK_WEBHOOK  = os.environ.get("SLACK_WEBHOOK_URL", "")


def main() -> None:
    logging.info("=== 割安認定中古車レポート 開始 ===")

    # 1. データ取得
    listings = fetch_all_listings(use_demo=USE_DEMO)

    # 2. 割安分析
    bargains = find_bargains(listings, discount_threshold=10, top_n=5)
    summary  = summarize(bargains)
    logging.info("割安車両検出: %d件（平均割安額 %s万円）", summary["count"], summary["avg_discount"])

    # 3. HTMLレポート生成
    out_path = generate_report(bargains, summary, output_path=OUTPUT_PATH)
    logging.info("レポート出力: %s", out_path)

    # 4. Slack通知
    if SLACK_WEBHOOK:
        notify_slack(bargains, summary, report_url=REPORT_URL, webhook_url=SLACK_WEBHOOK)
    else:
        logging.info("SLACK_WEBHOOK_URL 未設定のため通知をスキップ")

    logging.info("=== 完了 ===")


if __name__ == "__main__":
    main()
