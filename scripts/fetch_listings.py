"""
認定中古車リスト取得モジュール
GAZOO.com（トヨタ公式）と Honda 公式 API から関東の認定中古車を取得する。
"""
import logging
import random
import re
import time
import unicodedata
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="[fetch] %(message)s")
log = logging.getLogger(__name__)

GAZOO_BASE = "https://gazoo.com/DealerU-Car/search_result"
HONDA_API  = "https://ucar.honda.co.jp/api/Car/FindCarList"
HONDA_DETAIL_BASE = "https://ucar.honda.co.jp/Car/Detail"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}

# GAZOO.com 関東トヨタ系全ディーラー
# コード体系: 03xxx=トヨタ, 13xxx=トヨペット, 33xxx=カローラ, 43xxx=ネッツ
TOYOTA_KANTO_DEALERS: dict[str, tuple[str, str]] = {
    "03101": ("茨城トヨタ自動車",     "茨城県"),
    "03201": ("栃木トヨタ自動車",     "栃木県"),
    "03301": ("群馬トヨタ自動車",     "群馬県"),
    "03401": ("埼玉トヨタ自動車",     "埼玉県"),
    "03501": ("千葉トヨタ自動車",     "千葉県"),
    "03601": ("トヨタモビリティ東京", "東京都"),
    "03701": ("トヨタモビリティ神奈川", "神奈川県"),
    "13101": ("茨城トヨペット",       "茨城県"),
    "13201": ("栃木トヨペット",       "栃木県"),
    "13301": ("群馬トヨペット",       "群馬県"),
    "13401": ("埼玉トヨペット",       "埼玉県"),
    "13501": ("千葉トヨペット",       "千葉県"),
    "13701": ("ウエインズトヨタ神奈川", "神奈川県"),
    "33201": ("トヨタカローラ栃木",   "栃木県"),
    "33301": ("トヨタカローラ群馬",   "群馬県"),
    "33401": ("トヨタカローラ埼玉",   "埼玉県"),
    "33501": ("トヨタカローラ千葉",   "千葉県"),
    "43101": ("ネッツトヨタ茨城",     "茨城県"),
    "43201": ("ネッツトヨタ栃木",     "栃木県"),
    "43301": ("ネッツトヨタ群馬",     "群馬県"),
    "43401": ("ネッツトヨタ東埼玉",   "埼玉県"),
    "43501": ("ネッツトヨタ千葉",     "千葉県"),
}

# Honda 公式 API: 関東都道府県コード（JIS X 0401 2桁文字列）
HONDA_KANTO_PREFS = ["08", "09", "10", "11", "12", "13", "14"]


# ─────────────────────────────────────────────
# GAZOO.com スクレイピング
# ─────────────────────────────────────────────

def _parse_gazoo_card(dl: BeautifulSoup, dealer_code: str, pref: str) -> "dict | None":
    """GAZOO.com の dl カード要素を1件の車両辞書に変換する。"""
    try:
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not dt or not dd:
            return None

        # NEW バッジ
        is_new = bool(dt.find("img", alt="NEW"))

        # 車名・メーカー
        name_el = dt.find("span", class_="car_name")
        if not name_el:
            return None
        full_name = name_el.get_text(strip=True)

        # URL と車両 ID
        link = dd.find("a", class_="wrap_link")
        if not link:
            return None
        href = link.get("href", "")
        id_m = re.search(r"Id=(\d+)", href)
        if not id_m:
            return None
        car_id = id_m.group(1)
        url = "https://gazoo.com" + href

        # 支払総額（li.sum の .price .number）
        price_area = dd.find("ul", class_="price_area")
        if not price_area:
            return None
        sum_li = price_area.find("li", class_="sum")
        if not sum_li:
            return None
        num_p = sum_li.find("p", class_="number")
        if not num_p:
            return None
        # <p class="number">311<span class="price_decimal">.3</span><span>万円</span></p>
        price_text = num_p.get_text(strip=True).replace("万円", "").replace(",", "").strip()
        try:
            price = int(float(price_text))
        except ValueError:
            return None

        # 年式・走行距離（ul.detail_table の各 li）
        detail_table = dd.find("ul", class_="detail_table")
        if not detail_table:
            return None
        year = 0
        mileage_km = 0
        for li in detail_table.find_all("li"):
            ps = li.find_all("p", recursive=False)
            if len(ps) < 2:
                continue
            label = ps[0].get_text(strip=True)
            value = ps[1].get_text(strip=True)
            if label == "年式":
                m = re.search(r"(\d{4})年", value)
                if m:
                    year = int(m.group(1))
            elif label == "走行距離":
                if "万km" in value:
                    m = re.search(r"([\d.]+)万km", value)
                    if m:
                        mileage_km = int(float(m.group(1)) * 10_000)
                elif "km" in value:
                    m = re.search(r"([\d,]+)km", value)
                    if m:
                        mileage_km = int(m.group(1).replace(",", ""))

        if not year or not mileage_km:
            return None

        # 走行距離フィルタ（0.5〜9.9 万km）
        if mileage_km < 5_000 or mileage_km > 99_000:
            return None

        # 店舗名
        dealer_span = dd.find("span", class_="dealer-name")
        shop = dealer_span.get_text(strip=True) if dealer_span else ""

        return {
            "id":          f"gazoo_{car_id}",
            "source":      "gazoo",
            "brand":       "トヨタ",
            "certified":   True,
            "name":        full_name,
            "grade":       "",
            "year":        year,
            "mileage_km":  mileage_km,
            "color":       "",
            "color_emoji": "",
            "pref":        pref,
            "shop":        shop,
            "price":       price,
            "url":         url,
            "is_new":      is_new,
        }

    except (AttributeError, ValueError, KeyError) as e:
        log.debug("GAZOOカードパース失敗: %s", e)
        return None


def fetch_gazoo_listings(new_only: bool = True) -> list[dict]:
    """
    GAZOO.com から関東全ディーラーの認定中古車一覧を取得する。

    Args:
        new_only: True のとき New=1 パラメータを付けて新着のみ取得
    """
    listings: list[dict] = []

    for sdlr, (dealer_name, pref) in TOYOTA_KANTO_DEALERS.items():
        params: dict = {"Sdlr": sdlr}
        if new_only:
            params["New"] = 1

        try:
            resp = requests.get(GAZOO_BASE, params=params, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                log.warning("GAZOO %s: HTTP %d", dealer_name, resp.status_code)
                time.sleep(2)
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            wrap = soup.find("div", id="car-list-wrap")
            if not wrap:
                log.debug("GAZOO %s: car-list-wrap なし", dealer_name)
                time.sleep(1)
                continue

            cards = wrap.find_all("dl", recursive=False)
            dealer_results: list[dict] = []
            for dl in cards:
                parsed = _parse_gazoo_card(dl, sdlr, pref)
                if parsed:
                    dealer_results.append(parsed)

            listings.extend(dealer_results)
            log.info("GAZOO %s: %d件", dealer_name, len(dealer_results))

        except requests.RequestException as e:
            log.warning("GAZOO %s: ネットワークエラー: %s", dealer_name, e)

        time.sleep(random.uniform(1.5, 2.5))

    log.info("GAZOO 合計: %d件", len(listings))
    return listings


# ─────────────────────────────────────────────
# GAZOO.com 詳細ページ 色情報取得
# ─────────────────────────────────────────────

def fetch_gazoo_color(url: str) -> str:
    """
    GAZOO.com の車両詳細ページからボディカラーを取得する。
    半角カナを全角に正規化して返す。
    （割安候補に絞って呼び出すため、リクエスト数は最小限）

    Args:
        url: GAZOO.com 詳細ページURL（例: https://gazoo.com/DealerU-Car/detail?Id=...）

    Returns:
        色名文字列（例: "プラチナホワイトパールマイカ"）。取得失敗時は空文字。
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for th in soup.find_all("th"):
            label = th.get_text(strip=True)
            if label in ("カラー", "ボディカラー", "色"):
                td = th.find_next_sibling("td")
                if td:
                    # 半角カナ → 全角カナに正規化
                    raw = td.get_text(strip=True)
                    return unicodedata.normalize("NFKC", raw)
        return ""
    except Exception as e:
        log.debug("GAZOOカラー取得失敗 %s: %s", url, e)
        return ""


# ─────────────────────────────────────────────
# Honda 公式 API
# ─────────────────────────────────────────────

def fetch_honda_listings(max_pages: int = 5) -> list[dict]:
    """
    Honda 公式 API から関東の U-Select 認定中古車一覧を取得する。
    """
    listings: list[dict] = []
    headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Referer": "https://ucar.honda.co.jp/",
    }

    for page in range(1, max_pages + 1):
        payload = {
            "IsUSelect":        True,
            "IsUSelectPremium": True,
            "Page":             page,
            "OrderBy":          11,   # デフォルト（新着順）
            "PrefectureCdList": HONDA_KANTO_PREFS,
            "DeliverablePrefectureFlg": False,
        }

        try:
            resp = requests.post(HONDA_API, headers=headers, json=payload, timeout=20)
            if resp.status_code != 200:
                log.warning("Honda API p%d: HTTP %d", page, resp.status_code)
                break

            data = resp.json()
            cars = data.get("Data", [])
            if not cars:
                break

            for car in cars:
                try:
                    wns_cd = car.get("WnsPropertyCd", "")
                    if not wns_cd:
                        continue

                    price_info = car.get("TotalAmount", {})
                    price_str  = price_info.get("Price", "0") if isinstance(price_info, dict) else "0"
                    try:
                        price = int(float(price_str))
                    except (ValueError, TypeError):
                        continue

                    # 走行距離（単位: 万km）
                    dist = car.get("RunningDistance", 0) or 0
                    mileage_km = int(float(dist) * 10_000)
                    if mileage_km < 5_000 or mileage_km > 99_000:
                        continue

                    year = car.get("ModelYear", 0) or 0
                    if not year:
                        continue

                    listings.append({
                        "id":          f"honda_{wns_cd}",
                        "source":      "honda",
                        "brand":       "ホンダ",
                        "certified":   True,
                        "name":        car.get("CarName", "").strip(),
                        "grade":       car.get("GradeName", "").strip(),
                        "year":        year,
                        "mileage_km":  mileage_km,
                        "color":       car.get("BodyColor", ""),
                        "color_emoji": "",
                        "pref":        car.get("StorePrefecture", ""),
                        "shop":        car.get("StoreName", ""),
                        "price":       price,
                        "url":         f"{HONDA_DETAIL_BASE}/{wns_cd}",
                        "is_new":      False,  # track_seen で後から判定
                    })

                except (KeyError, TypeError) as e:
                    log.debug("Hondaカードパース失敗: %s", e)
                    continue

            log.info("Honda API p%d: %d件取得", page, len(cars))
            total_pages = data.get("TotalPage", 1)
            if page >= total_pages:
                break

        except requests.RequestException as e:
            log.warning("Honda API p%d: ネットワークエラー: %s", page, e)
            break

        time.sleep(random.uniform(1.0, 2.0))

    log.info("Honda 合計: %d件", len(listings))
    return listings


# ─────────────────────────────────────────────
# デモデータ（フォールバック用）
# ─────────────────────────────────────────────

import datetime
import random as _rnd

DEMO_MODELS = [
    {"brand": "トヨタ", "name": "シエンタ HV G",           "base": 195},
    {"brand": "トヨタ", "name": "ヴォクシー S-Z",           "base": 310},
    {"brand": "トヨタ", "name": "プリウス Z",               "base": 355},
    {"brand": "トヨタ", "name": "ハリアー Z",               "base": 390},
    {"brand": "トヨタ", "name": "ヤリスクロス HV Z",        "base": 235},
    {"brand": "ホンダ", "name": "フリード G・Honda SENSING", "base": 185},
    {"brand": "ホンダ", "name": "ヴェゼル e:HEV Z",         "base": 275},
    {"brand": "ホンダ", "name": "ステップワゴン SPADA",      "base": 340},
]
_DEMO_PREFS = [v[1] for v in TOYOTA_KANTO_DEALERS.values()]


def _generate_demo_listings() -> list[dict]:
    _rnd.seed(42)
    listings = []
    current_year = datetime.date.today().year

    for model in DEMO_MODELS:
        for i in range(_rnd.randint(12, 18)):
            year      = _rnd.randint(current_year - 4, current_year - 1)
            mileage   = int(_rnd.uniform(5_000, 99_000))
            variation = _rnd.uniform(-0.18, 0.22)
            price     = int(model["base"] * (1 + variation) * (1 - (current_year - year) * 0.05))
            pref      = _rnd.choice(_DEMO_PREFS)
            listings.append({
                "id":          f"demo_{model['brand']}_{i}",
                "source":      "demo",
                "brand":       model["brand"],
                "certified":   True,
                "name":        model["name"],
                "grade":       "",
                "year":        year,
                "mileage_km":  mileage,
                "color":       "",
                "color_emoji": "",
                "pref":        pref,
                "shop":        "デモ店舗",
                "price":       price,
                "url":         "#",
                "is_new":      _rnd.random() < 0.4,
            })

    log.info("デモデータ生成: %d件", len(listings))
    return listings


# ─────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────

def fetch_all_listings(use_demo: bool = False) -> list[dict]:
    """
    GAZOO.com + Honda 公式 API から関東の認定中古車リストを取得して返す。

    Args:
        use_demo: True のときデモデータを使用
    """
    if use_demo:
        return _generate_demo_listings()

    listings: list[dict] = []

    toyota = fetch_gazoo_listings(new_only=True)
    listings.extend(toyota)

    honda = fetch_honda_listings(max_pages=5)
    listings.extend(honda)

    if not listings:
        log.warning("実スクレイピング結果が0件 → デモデータにフォールバック")
        return _generate_demo_listings()

    log.info("スクレイピング完了: 合計 %d 件", len(listings))
    return listings
