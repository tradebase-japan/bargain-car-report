"""
割安認定中古車レポート 自動生成スクリプト
GitHub Actions から呼び出されるエントリーポイント。
"""
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from scripts.fetch_listings  import fetch_all_listings, fetch_gazoo_color
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


def _enrich_gazoo_colors(bargains: list[dict]) -> list[dict]:
    """
    割安候補のうちGAZOO.com 車両（色情報なし）だけ、
    詳細ページをスクレイピングして色を補完する。
    件数は通常 10〜20 件なので追加リクエストは最小限。
    """
    enriched = []
    for car in bargains:
        if car.get("source") == "gazoo" and not car.get("color"):
            color = fetch_gazoo_color(car["url"])
            if color:
                logging.info("色補完: %s %s → %s", car["name"], car.get("grade",""), color)
            car = {**car, "color": color}
            time.sleep(0.8)  # 詳細ページへの連続アクセスを緩和
        enriched.append(car)
    return enriched


def main() -> None:
    logging.info("=== 割安認定中古車レポート 開始 ===")

    # ── 1. 公式ディーラーから物件取得 ────────────────────────
    listings = fetch_all_listings(use_demo=USE_DEMO)

    # ── 2. 新着検出（seen_ids との差分） ──────────────────────
    seen_ids = load_seen_ids(SEEN_IDS_PATH)
    listings = mark_new_listings(listings, seen_ids)
    new_count = sum(1 for c in listings if c.get("is_new"))
    logging.info("新着物件: %d件 / 全 %d件", new_count, len(listings))

    # ── 3. 市場相場データ取得（グーネット + カーセンサー） ────
    market_listings: "list[dict] | None" = None
    if USE_MARKET and not USE_DEMO:
        market_listings = fetch_market_listings(max_pages=3)
        if not market_listings:
            logging.warning("市場データ取得0件。listings 内部比較にフォールバック")

    # ── 4. 割安分析（第1パス: 色補正なしで候補を絞る） ────────
    # 色補正前に多めの候補を取得（top_n=30）してから色を補完する
    candidates = find_bargains(
        listings,
        market_listings=market_listings,
        discount_threshold=10,
        top_n=30,           # 色補完後に再絞りするため多めに取る
        year_band_width=1,
        min_peers=2,
    )
    logging.info("割安候補（色補正前）: %d件", len(candidates))

    # ── 5. GAZOO.com 割安候補の色を詳細ページから補完 ─────────
    if not USE_DEMO:
        candidates = _enrich_gazoo_colors(candidates)

    # ── 6. 色補正を反映した本ランキング（再 analyze 不要: sort のみ） ──
    # analyze の BargainCar は色補正後の discount を持つが、
    # 色補完後に discount を再計算するため、候補をリスト化して再 find_bargains
    # ただし候補 30 件だけを pool にすると比較数が不足するので、
    # 元の listings に色補完済み情報をマージして再実行する
    if not USE_DEMO:
        # listings に色補完済み情報をマージ
        color_map = {c["url"]: c.get("color", "") for c in candidates if c.get("source") == "gazoo"}
        for i, car in enumerate(listings):
            if car.get("source") == "gazoo" and car.get("url") in color_map:
                listings[i] = {**car, "color": color_map[car["url"]]}

        # 第2パス（最終 top_n）
        bargains = find_bargains(
            listings,
            market_listings=market_listings,
            discount_threshold=10,
            top_n=10,
            year_band_width=1,
            min_peers=2,
        )
    else:
        bargains = candidates[:10]

    summary = summarize(bargains)
    logging.info(
        "割安車両: %d件（うち新着 %d件 / 平均割安額 %s万円）",
        summary["count"], summary.get("new_count", 0), summary["avg_discount"],
    )

    # ── 7. HTMLレポート生成 ─────────────────────────────────
    out_path = generate_report(bargains, summary, output_path=OUTPUT_PATH)
    logging.info("レポート出力: %s", out_path)

    # ── 8. Slack 通知（新着割安が1件以上のとき） ──────────────
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

    # ── 9. seen_ids を更新・保存 ──────────────────────────────
    updated_seen = update_seen_ids(seen_ids, listings)
    save_seen_ids(updated_seen, SEEN_IDS_PATH)

    logging.info("=== 完了 ===")


if __name__ == "__main__":
    main()
