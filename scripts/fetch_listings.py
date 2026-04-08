"""
認定中古車リスト取得モジュール
実スクレイピングが失敗した場合はデモデータにフォールバックする。
"""
import logging
import random
import time
import datetime
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="[fetch] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

KANTO_PREFS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県"]

TOYOTA_MODELS = [
    {"name": "シエンタ",     "grades": ["G", "Z", "X"],       "base_price": 195, "brand_id": "TO"},
    {"name": "ヴォクシー",   "grades": ["S-Z", "S-G"],         "base_price": 310, "brand_id": "TO"},
    {"name": "プリウス",     "grades": ["Z", "G", "U"],        "base_price": 355, "brand_id": "TO"},
    {"name": "ハリアー",     "grades": ["Z", "G", "S"],        "base_price": 390, "brand_id": "TO"},
    {"name": "ヤリスクロス", "grades": ["Z", "G", "X"],        "base_price": 235, "brand_id": "TO"},
    {"name": "ライズ",       "grades": ["Z", "G", "X"],        "base_price": 215, "brand_id": "TO"},
    {"name": "アルファード", "grades": ["Z", "G", "X"],        "base_price": 650, "brand_id": "TO"},
]

HONDA_MODELS = [
    {"name": "フリード",       "grades": ["G Honda SENSING", "CROSSTAR Honda SENSING"], "base_price": 185, "brand_id": "HO"},
    {"name": "ヴェゼル",       "grades": ["e:HEV Z", "e:HEV X", "G"],                  "base_price": 275, "brand_id": "HO"},
    {"name": "ステップワゴン", "grades": ["SPADA", "AIR", "SPADA e:HEV"],               "base_price": 340, "brand_id": "HO"},
    {"name": "フィット",       "grades": ["e:HEV HOME", "e:HEV NESS", "HOME"],          "base_price": 195, "brand_id": "HO"},
    {"name": "ZR-V",           "grades": ["Z", "X"],                                    "base_price": 330, "brand_id": "HO"},
]

COLORS = ["白", "黒", "シルバー", "パール", "グレー", "ブルー", "レッド"]
COLOR_EMOJI = {
    "白": "⬜", "黒": "⬛", "シルバー": "◻️",
    "パール": "🤍", "グレー": "🩶", "ブルー": "🟦", "レッド": "🟥",
}

TOYOTA_SHOPS = [
    "神奈川トヨタ 横浜港北店", "東京トヨタ 練馬店", "埼玉トヨタ 大宮店",
    "千葉トヨタ 柏店", "茨城トヨタ 水戸店", "栃木トヨタ 宇都宮店",
]
HONDA_SHOPS = [
    "Honda Cars 埼玉 浦和店", "Honda Cars 東京 新宿店", "Honda Cars 神奈川 横浜店",
    "Honda Cars 千葉 船橋店", "Honda Cars 茨城 土浦店",
]


def _make_listing(
    brand: str, model_name: str, grade: str, year: int,
    mileage_km: int, color: str, pref: str, shop: str,
    price: int, url: str = "#", is_new: bool = False,
) -> dict:
    return {
        "brand": brand,
        "certified": True,
        "name": model_name,
        "grade": grade,
        "year": year,
        "mileage_km": mileage_km,   # 常にkm単位（例: 21000）
        "color": color,
        "color_emoji": COLOR_EMOJI.get(color, ""),
        "pref": pref,
        "shop": shop,
        "price": price,
        "url": url,
        "is_new": is_new,
    }


def _generate_demo_listings() -> list[dict]:
    """実スクレイピングのフォールバック用デモデータを生成する。"""
    random.seed(42)
    listings = []
    current_year = datetime.date.today().year
    all_models = [
        ("トヨタ", TOYOTA_MODELS, TOYOTA_SHOPS),
        ("ホンダ", HONDA_MODELS, HONDA_SHOPS),
    ]

    for brand, models, shops in all_models:
        for model in models:
            for _ in range(random.randint(8, 14)):
                year = random.randint(current_year - 4, current_year - 1)
                grade = random.choice(model["grades"])
                mileage_km = int(random.uniform(5000, 98000))
                variation = random.uniform(-0.15, 0.20)
                price = int(
                    model["base_price"]
                    * (1 + variation)
                    * (1 - (current_year - year) * 0.05)
                )
                color = random.choice(COLORS)
                pref = random.choice(KANTO_PREFS)
                shop = random.choice(shops)
                listings.append(_make_listing(
                    brand=brand,
                    model_name=model["name"],
                    grade=grade,
                    year=year,
                    mileage_km=mileage_km,
                    color=color,
                    pref=pref,
                    shop=shop,
                    price=price,
                    url="#",
                    is_new=random.random() < 0.4,
                ))

    log.info("デモデータ生成: %d件", len(listings))
    return listings


def _scrape_model(brand: str, model_name: str, brand_id: str) -> list[dict]:
    """
    カーセンサーから指定モデルの認定中古車をスクレイピングする。
    失敗した場合は空リストを返す。
    """
    try:
        url = (
            f"https://www.carsensor.net/usedcar/{brand_id}/"
            f"?STID=CS_NEWCAR&MKID={brand_id}&CARNAME={model_name}"
            f"&AREACD=010&BSTYPE=used"
        )
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            log.warning("%s %s: HTTPエラー %d", brand, model_name, resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("section.cassetteMain")
        results = []

        for card in cards[:20]:
            try:
                name_el  = card.select_one(".modelName")
                price_el = card.select_one(".totalPrice")
                year_el  = card.select_one(".year")
                km_el    = card.select_one(".mileage")
                pref_el  = card.select_one(".area")
                url_el   = card.select_one("a[href]")

                if not (name_el and price_el):
                    continue

                price = int(price_el.get_text(strip=True).replace("万円", "").replace(",", ""))
                year  = int((year_el.get_text(strip=True) if year_el else "2022年").replace("年", ""))
                km_text = km_el.get_text(strip=True) if km_el else "3万km"
                mileage_km = int(float(km_text.replace("万km", "")) * 10000)
                pref  = pref_el.get_text(strip=True) if pref_el else "東京都"
                detail_url = url_el["href"] if url_el else "#"

                results.append(_make_listing(
                    brand=brand,
                    model_name=name_el.get_text(strip=True),
                    grade="",
                    year=year,
                    mileage_km=mileage_km,
                    color="白",
                    pref=pref,
                    shop="",
                    price=price,
                    url=detail_url,
                ))
            except (ValueError, AttributeError, KeyError) as e:
                log.debug("カードパース失敗: %s", e)
                continue

        log.info("%s %s: %d件取得", brand, model_name, len(results))
        return results

    except requests.RequestException as e:
        log.warning("%s %s: ネットワークエラー: %s", brand, model_name, e)
        return []
    except Exception as e:
        log.warning("%s %s: 予期しないエラー: %s", brand, model_name, e)
        return []


def _scrape_all() -> list[dict]:
    """全モデルをスクレイピングして結果を結合する。"""
    listings = []
    all_models = [
        ("トヨタ", TOYOTA_MODELS),
        ("ホンダ", HONDA_MODELS),
    ]
    for brand, models in all_models:
        for model in models:
            results = _scrape_model(brand, model["name"], model["brand_id"])
            listings.extend(results)
            time.sleep(random.uniform(1.5, 3.0))   # レートリミット対策

    return listings


def fetch_all_listings(use_demo: bool = True) -> list[dict]:
    """
    全メーカーの認定中古車リストを取得して返す。

    Args:
        use_demo: True のときデモデータを使用（GitHub Actions での安定動作用）
    """
    if not use_demo:
        listings = _scrape_all()
        if listings:
            log.info("スクレイピング成功: 計%d件", len(listings))
            return listings
        log.warning("スクレイピング結果が0件 → デモデータにフォールバック")

    return _generate_demo_listings()
