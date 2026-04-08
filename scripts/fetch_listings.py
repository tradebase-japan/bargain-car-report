"""
認定中古車リスト取得モジュール
グーネット（goo-net.com）から関東の認定中古車をスクレイピングする。
失敗した場合はデモデータにフォールバックする。
"""
import logging
import random
import re
import time
import datetime
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="[fetch] %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://www.goo-net.com/usedcar/brand-{brand}/pref-{pref:02d}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

BRANDS = {
    "トヨタ": "TOYOTA",
    "ホンダ": "HONDA",
}

KANTO_PREFS = {
    13: "東京都",
    14: "神奈川県",
    11: "埼玉県",
    12: "千葉県",
    8:  "茨城県",
    9:  "栃木県",
    10: "群馬県",
}

# ===== 正規ディーラー判定 =====

# トヨタ正規ディーラーの店舗名キーワード
# トヨタ系販売会社は「○○トヨタ」「トヨペット」「ネッツ」「カローラ」等の名称を使用する
TOYOTA_DEALER_KEYWORDS = [
    "トヨタ", "ネッツ", "カローラ", "レクサス", "トヨペット",
    "ﾄﾖﾀ", "ネッツ", "TOYOTA",
]

# ホンダ正規ディーラーの店舗名キーワード
HONDA_DEALER_KEYWORDS = [
    "Honda Cars", "ホンダカーズ", "ﾎﾝﾀﾞｶｰｽﾞ", "Honda　Cars",
    "ホンダ Cars", "Ｈｏｎｄａ", "HONDA",
]

# 非ディーラーと判定する除外キーワード（ウィーカーズ等の量販店）
NON_DEALER_KEYWORDS = [
    "ウィーカーズ", "ガリバー", "ビッグモーター", "ネクステージ",
    "フレックス", "ＳＵＶＬＡＮＤ", "ＳＵＶ　ＬＡＮＤ", "SUV LAND", "ＳＵＶ　Ｌａｎｄ",
    "グッドスピード", "オートバックス", "ケーユー",
    "ユーポス", "ハナテン", "ラビット", "リミックス",
    "チューリップ", "アップル", "ジャック",
]


def _is_official_dealer(card: BeautifulSoup, brand_jp: str) -> bool:
    """
    メーカー正規ディーラーかどうかを判定する。
    ① makerHosyouLogo に <img> があればメーカー認定確定
    ② 店舗名のホワイトリストで判定（①が取れない場合のフォールバック）
    """
    # ① メーカー保証ロゴ画像があればメーカー認定確定
    maker_logo = card.select_one("div.makerHosyouLogo img")
    if maker_logo:
        return True

    # ② 店舗名ホワイトリスト判定
    dealer_el = card.select_one("p.dealer-name")
    if not dealer_el:
        return False
    shop = dealer_el.get_text(strip=True)

    # まず非ディーラーキーワードで除外
    for ng in NON_DEALER_KEYWORDS:
        if ng in shop:
            return False

    # 次にブランド別のホワイトリストで判定
    keywords = TOYOTA_DEALER_KEYWORDS if brand_jp == "トヨタ" else HONDA_DEALER_KEYWORDS
    return any(kw in shop for kw in keywords)


# ===== 実スクレイピング =====

def _parse_card(card: BeautifulSoup, brand_jp: str, pref_name: str) -> "dict | None":
    """
    div.box_item_detail から1件の車両情報を抽出する。
    メーカー正規ディーラー以外はスキップする。
    """
    try:
        # メーカー正規ディーラーのみ対象
        if not _is_official_dealer(card, brand_jp):
            return None

        h3 = card.select_one("h3")
        if not h3:
            return None

        full_name = h3.get_text(strip=True)
        model_name = (
            full_name
            .replace("トヨタ", "")
            .replace("ホンダ", "")
            .strip()
        )

        spec_text = card.get_text(separator=" ", strip=True)

        # 支払総額（最初に出てくる万円単位の数値）
        prices_found = re.findall(r"([\d,]+\.?\d*)\s*万円", spec_text)
        if not prices_found:
            return None
        price = int(float(prices_found[0].replace(",", "")))

        # 年式
        year_m = re.search(r"年式\D*(\d{4})年", spec_text)
        year = int(year_m.group(1)) if year_m else 0
        if not year:
            return None

        # 走行距離（万km → km変換）対象範囲: 0.5〜9.9万km
        km_m = re.search(r"走行距離\D*([\d.]+)万km", spec_text)
        if not km_m:
            return None
        mileage_km = int(float(km_m.group(1)) * 10000)
        if mileage_km < 5000 or mileage_km > 99000:
            return None   # 対象外（ほぼ新車 or 高走行）

        # 店舗名
        dealer_el = card.select_one("p.dealer-name")
        shop = dealer_el.get_text(strip=True) if dealer_el else ""

        # 掲載URL
        link = card.select_one("a[href*='/usedcar/spread/']")
        detail_url = "https://www.goo-net.com" + link["href"] if link else "#"

        # 新着判定
        is_new = bool(card.find(string=re.compile(r"新着|NEW")))

        return {
            "brand": brand_jp,
            "certified": True,
            "name": model_name,
            "grade": "",
            "year": year,
            "mileage_km": mileage_km,
            "color": "",
            "color_emoji": "",
            "pref": pref_name,
            "shop": shop,
            "price": price,
            "url": detail_url,
            "is_new": is_new,
        }

    except (AttributeError, ValueError, KeyError) as e:
        log.debug("カードパース失敗: %s", e)
        return None


def _scrape_brand(brand_jp: str, brand_en: str, max_pages: int = 3) -> list[dict]:
    """グーネットから指定メーカーの認定中古車を関東全域でスクレイピングする。"""
    listings: list[dict] = []

    for pref_code, pref_name in KANTO_PREFS.items():
        for page in range(1, max_pages + 1):
            url = BASE_URL.format(brand=brand_en, pref=pref_code)
            params = {"certification": 1, "p": page}

            try:
                resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
                if resp.status_code != 200:
                    log.debug("%s %s p%d: HTTP %d", brand_jp, pref_name, page, resp.status_code)
                    break

                resp.encoding = resp.apparent_encoding
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select("div.box_item_detail")

                if not cards:
                    break

                page_results = []
                for card in cards:
                    parsed = _parse_card(card, brand_jp, pref_name)
                    if parsed:
                        page_results.append(parsed)

                listings.extend(page_results)
                log.info("%s %s p%d: %d件取得", brand_jp, pref_name, page, len(page_results))

                if len(cards) < 20:
                    break

                time.sleep(random.uniform(2.0, 3.5))

            except requests.RequestException as e:
                log.warning("%s %s p%d: ネットワークエラー: %s", brand_jp, pref_name, page, e)
                time.sleep(5)   # レートリミット後は長めに待つ
                break
            except Exception as e:
                log.warning("%s %s p%d: 予期しないエラー: %s", brand_jp, pref_name, page, e)
                break

        time.sleep(random.uniform(2.0, 3.0))

    log.info("%s: 合計%d件", brand_jp, len(listings))
    return listings


# ===== デモデータ（フォールバック用） =====

DEMO_MODELS = [
    {"brand": "トヨタ", "name": "シエンタ HV G",          "base": 195},
    {"brand": "トヨタ", "name": "ヴォクシー S-Z",          "base": 310},
    {"brand": "トヨタ", "name": "プリウス Z",              "base": 355},
    {"brand": "トヨタ", "name": "ハリアー Z",              "base": 390},
    {"brand": "トヨタ", "name": "ヤリスクロス HV Z",       "base": 235},
    {"brand": "ホンダ", "name": "フリードＧ・センシング",   "base": 185},
    {"brand": "ホンダ", "name": "ヴェゼル e:HEV Z",        "base": 275},
    {"brand": "ホンダ", "name": "ステップワゴン SPADA",     "base": 340},
]
KANTO_PREF_NAMES = list(KANTO_PREFS.values())
COLORS = ["白", "黒", "シルバー", "パール", "グレー"]
COLOR_EMOJI = {"白": "⬜", "黒": "⬛", "シルバー": "◻️", "パール": "🤍", "グレー": "🩶"}


def _generate_demo_listings() -> list[dict]:
    """実スクレイピングのフォールバック用デモデータを生成する。"""
    random.seed(42)
    listings = []
    current_year = datetime.date.today().year

    for model in DEMO_MODELS:
        for _ in range(random.randint(12, 18)):
            year = random.randint(current_year - 4, current_year - 1)
            mileage_km = int(random.uniform(5000, 98000))
            variation = random.uniform(-0.18, 0.22)
            price = int(model["base"] * (1 + variation) * (1 - (current_year - year) * 0.05))
            color = random.choice(COLORS)
            pref = random.choice(KANTO_PREF_NAMES)
            listings.append({
                "brand": model["brand"],
                "certified": True,
                "name": model["name"],
                "grade": "",
                "year": year,
                "mileage_km": mileage_km,
                "color": color,
                "color_emoji": COLOR_EMOJI.get(color, ""),
                "pref": pref,
                "shop": "",
                "price": price,
                "url": "#",
                "is_new": random.random() < 0.4,
            })

    log.info("デモデータ生成: %d件", len(listings))
    return listings


# ===== 公開API =====

def fetch_all_listings(use_demo: bool = False) -> list[dict]:
    """
    全メーカーの認定中古車リストを取得して返す。

    Args:
        use_demo: True のときデモデータを使用
    """
    if use_demo:
        return _generate_demo_listings()

    listings: list[dict] = []
    for brand_jp, brand_en in BRANDS.items():
        results = _scrape_brand(brand_jp, brand_en, max_pages=2)
        listings.extend(results)

    if not listings:
        log.warning("スクレイピング結果が0件 → デモデータにフォールバック")
        return _generate_demo_listings()

    log.info("スクレイピング完了: 合計%d件", len(listings))
    return listings
