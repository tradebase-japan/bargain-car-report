"""
市場相場データ取得モジュール
グーネット（goo-net.com）から関東の認定中古車相場データをスクレイピングする。
割安判定の比較基準として使用する（掲載物件自体の対象ではない）。
"""
import logging
import random
import re
import time
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MARKET_URL = "https://www.goo-net.com/usedcar/brand-{brand}/pref-{pref:02d}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

KANTO_PREFS: dict[int, str] = {
    8:  "茨城県",
    9:  "栃木県",
    10: "群馬県",
    11: "埼玉県",
    12: "千葉県",
    13: "東京都",
    14: "神奈川県",
}

MARKET_BRANDS = {
    "トヨタ": "TOYOTA",
    "ホンダ": "HONDA",
}


def _parse_market_card(card: BeautifulSoup, brand_jp: str, pref_name: str) -> "dict | None":
    """グーネット の div.box_item_detail から市場価格データを抽出する。"""
    try:
        h3 = card.select_one("h3")
        if not h3:
            return None

        full_name = h3.get_text(strip=True)
        name = (
            full_name
            .replace("トヨタ", "")
            .replace("ホンダ", "")
            .strip()
        )

        spec = card.get_text(separator=" ", strip=True)

        # 価格（最初の万円単位）
        prices = re.findall(r"([\d,]+\.?\d*)\s*万円", spec)
        if not prices:
            return None
        price = int(float(prices[0].replace(",", "")))

        # 年式
        year_m = re.search(r"年式\D*(\d{4})年", spec)
        year = int(year_m.group(1)) if year_m else 0
        if not year:
            return None

        # 走行距離（万km → km）
        km_m = re.search(r"走行距離\D*([\d.]+)万km", spec)
        if not km_m:
            return None
        mileage_km = int(float(km_m.group(1)) * 10_000)
        if mileage_km < 5_000 or mileage_km > 99_000:
            return None

        return {
            "brand":      brand_jp,
            "name":       name,
            "year":       year,
            "mileage_km": mileage_km,
            "price":      price,
            "pref":       pref_name,
        }

    except (AttributeError, ValueError, KeyError) as e:
        log.debug("市場カードパース失敗: %s", e)
        return None


def fetch_market_listings(max_pages: int = 3) -> list[dict]:
    """
    グーネットから関東の認定中古車相場データを取得する。

    Args:
        max_pages: 都道府県・ブランドごとの最大ページ数

    Returns:
        市場価格比較用の車両リスト（id フィールドなし）
    """
    listings: list[dict] = []

    for brand_jp, brand_en in MARKET_BRANDS.items():
        for pref_code, pref_name in KANTO_PREFS.items():
            for page in range(1, max_pages + 1):
                url = MARKET_URL.format(brand=brand_en, pref=pref_code)
                params = {"certification": 1, "p": page}

                try:
                    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
                    if resp.status_code != 200:
                        break

                    resp.encoding = resp.apparent_encoding
                    soup = BeautifulSoup(resp.text, "lxml")
                    cards = soup.select("div.box_item_detail")

                    if not cards:
                        break

                    page_results: list[dict] = []
                    for card in cards:
                        parsed = _parse_market_card(card, brand_jp, pref_name)
                        if parsed:
                            page_results.append(parsed)

                    listings.extend(page_results)
                    log.info("市場 %s %s p%d: %d件", brand_jp, pref_name, page, len(page_results))

                    if len(cards) < 20:
                        break

                    time.sleep(random.uniform(1.5, 2.5))

                except requests.RequestException as e:
                    log.warning("市場 %s %s p%d: エラー: %s", brand_jp, pref_name, page, e)
                    time.sleep(3)
                    break
                except Exception as e:
                    log.warning("市場 %s %s p%d: 予期しないエラー: %s", brand_jp, pref_name, page, e)
                    break

            time.sleep(random.uniform(1.0, 2.0))

    log.info("市場データ合計: %d件", len(listings))
    return listings
