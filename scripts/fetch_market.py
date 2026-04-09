"""
市場相場データ取得モジュール
グーネット + カーセンサーから全国の認定中古車相場データを取得する。
割安判定の比較基準として使用する（掲載物件自体の対象ではない）。
"""
import logging
import random
import re
import time
import unicodedata
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

# ─────────────────────────────────────────────
# グーネット（関東エリア）
# ─────────────────────────────────────────────

GOONET_URL = "https://www.goo-net.com/usedcar/brand-{brand}/pref-{pref:02d}/"

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


def _parse_goonet_card(card: BeautifulSoup, brand_jp: str) -> "dict | None":
    """グーネット div.box_item_detail から相場データを抽出する。"""
    try:
        h3 = card.select_one("h3")
        if not h3:
            return None

        full_name = h3.get_text(strip=True)
        # 「トヨタ プリウス Z」→ 車名だけ取り出す
        name = full_name.replace("トヨタ", "").replace("ホンダ", "").strip()
        # グレードはスペース区切り後半
        parts = name.split(None, 1)
        model = parts[0] if parts else name
        grade = parts[1] if len(parts) > 1 else ""

        spec = card.get_text(separator=" ", strip=True)

        prices = re.findall(r"([\d,]+\.?\d*)\s*万円", spec)
        if not prices:
            return None
        price = int(float(prices[0].replace(",", "")))

        year_m = re.search(r"年式\D*(\d{4})年", spec)
        year = int(year_m.group(1)) if year_m else 0
        if not year:
            return None

        km_m = re.search(r"走行距離\D*([\d.]+)万km", spec)
        if not km_m:
            return None
        mileage_km = int(float(km_m.group(1)) * 10_000)
        if mileage_km < 5_000 or mileage_km > 99_000:
            return None

        color_m = re.search(r"カラー\s*(.+?)(?:\s{2}|$)", spec)
        color = color_m.group(1).strip() if color_m else ""

        return {
            "brand":      brand_jp,
            "name":       model,
            "grade":      grade,
            "year":       year,
            "mileage_km": mileage_km,
            "price":      price,
            "color":      color,
            "source":     "goonet",
        }
    except (AttributeError, ValueError, KeyError) as e:
        log.debug("グーネットカードパース失敗: %s", e)
        return None


def fetch_goonet_listings(max_pages: int = 3) -> list[dict]:
    """グーネットから関東の認定中古車相場データを取得する。"""
    listings: list[dict] = []

    for brand_jp, brand_en in MARKET_BRANDS.items():
        for pref_code in KANTO_PREFS:
            for page in range(1, max_pages + 1):
                url = GOONET_URL.format(brand=brand_en, pref=pref_code)
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
                    for card in cards:
                        parsed = _parse_goonet_card(card, brand_jp)
                        if parsed:
                            listings.append(parsed)
                    if len(cards) < 20:
                        break
                    time.sleep(random.uniform(1.5, 2.5))
                except requests.RequestException as e:
                    log.warning("グーネット %s pref%d p%d: %s", brand_jp, pref_code, page, e)
                    time.sleep(3)
                    break
                except Exception as e:
                    log.warning("グーネット 予期しないエラー: %s", e)
                    break
            time.sleep(random.uniform(1.0, 2.0))

    log.info("グーネット相場: %d件", len(listings))
    return listings


# ─────────────────────────────────────────────
# カーセンサー（全国認定中古車）
# ─────────────────────────────────────────────

CARSENSOR_URLS = {
    "トヨタ": "https://www.carsensor.net/usedcar/freeword/%E3%83%88%E3%83%A8%E3%82%BF%E8%AA%8D%E5%AE%9A%E4%B8%AD%E5%8F%A4%E8%BB%8A/index.html",
    "ホンダ": "https://www.carsensor.net/usedcar/freeword/Honda%E8%AA%8D%E5%AE%9A%E4%B8%AD%E5%8F%A4%E8%BB%8A/index.html",
}

CARSENSOR_HEADERS = {
    **HEADERS,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Referer": "https://www.carsensor.net/",
}


def _parse_carsensor_card(card: BeautifulSoup, brand_jp: str) -> "dict | None":
    """カーセンサー div.cassetteMain から相場データを抽出する。"""
    try:
        # 車名・グレード（h3: "クラウン ハイブリッド 2.5 RS 認定中古車 ..."）
        h3 = card.find("h3")
        if not h3:
            return None
        raw_name = h3.get_text(strip=True)
        # "認定中古車" 以降のオプション文字列を除去
        raw_name = re.sub(r"認定中古車.*", "", raw_name).strip()
        parts = raw_name.split(None, 1)
        model = parts[0] if parts else raw_name
        grade = parts[1].strip() if len(parts) > 1 else ""

        # 価格（支払総額: span[class*=total] + span[class*=decimal]）
        total_int = card.find("span", class_=re.compile(r"total"))
        total_dec = card.find("span", class_=re.compile(r"decimal"))
        if not total_int:
            return None
        price_str = total_int.get_text(strip=True)
        if total_dec:
            price_str += "." + total_dec.get_text(strip=True).lstrip(".")
        try:
            price = int(float(price_str))
        except ValueError:
            return None

        # 年式・走行距離・色（dl[class*=spec]）
        spec_dl = card.find("dl", class_=re.compile(r"spec"))
        if not spec_dl:
            return None
        spec_text = spec_dl.get_text(separator=" ", strip=True)

        year_m = re.search(r"年式\s*(\d{4})", spec_text)
        year = int(year_m.group(1)) if year_m else 0
        if not year:
            return None

        km_m = re.search(r"走行距離\s*([\d.]+)\s*万km", spec_text)
        if not km_m:
            return None
        mileage_km = int(float(km_m.group(1)) * 10_000)
        if mileage_km < 5_000 or mileage_km > 99_000:
            return None

        # 色（img alt や テキストから）
        color_m = re.search(r"カラー\s*([^\s]+)", spec_text)
        raw_color = color_m.group(1) if color_m else ""
        color = unicodedata.normalize("NFKC", raw_color)

        return {
            "brand":      brand_jp,
            "name":       model,
            "grade":      grade,
            "year":       year,
            "mileage_km": mileage_km,
            "price":      price,
            "color":      color,
            "source":     "carsensor",
        }
    except (AttributeError, ValueError, KeyError) as e:
        log.debug("カーセンサーカードパース失敗: %s", e)
        return None


def _carsensor_next_url(soup: BeautifulSoup, current_url: str) -> "str | None":
    """カーセンサーの次ページURLを取得する。"""
    # ページャから「次へ」または数字リンクを探す
    pager = soup.find("a", class_=re.compile(r"next|pager.*next", re.I))
    if pager and pager.get("href"):
        href = pager["href"]
        return href if href.startswith("http") else "https://www.carsensor.net" + href

    # index2.html, index3.html 形式のパターン
    m = re.search(r"index(\d+)\.html", current_url)
    if m:
        next_n = int(m.group(1)) + 1
        return re.sub(r"index\d+\.html", f"index{next_n}.html", current_url)
    # 初回ページ(index.html)→ index2.html
    if current_url.endswith("index.html"):
        return current_url.replace("index.html", "index2.html")
    return None


def fetch_carsensor_listings(max_pages: int = 5) -> list[dict]:
    """カーセンサーから全国の認定中古車相場データを取得する。"""
    listings: list[dict] = []

    for brand_jp, base_url in CARSENSOR_URLS.items():
        url: "str | None" = base_url
        for page in range(1, max_pages + 1):
            if not url:
                break
            try:
                resp = requests.get(url, headers=CARSENSOR_HEADERS, timeout=20)
                if resp.status_code != 200:
                    log.warning("カーセンサー %s p%d: HTTP %d", brand_jp, page, resp.status_code)
                    break
                resp.encoding = "utf-8"
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select("div.cassetteMain")
                if not cards:
                    break

                page_results: list[dict] = []
                for card in cards:
                    parsed = _parse_carsensor_card(card, brand_jp)
                    if parsed:
                        page_results.append(parsed)

                listings.extend(page_results)
                log.info("カーセンサー %s p%d: %d件", brand_jp, page, len(page_results))

                url = _carsensor_next_url(soup, url)
                time.sleep(random.uniform(1.5, 2.5))

            except requests.RequestException as e:
                log.warning("カーセンサー %s p%d: %s", brand_jp, page, e)
                time.sleep(3)
                break
            except Exception as e:
                log.warning("カーセンサー 予期しないエラー: %s", e)
                break

        time.sleep(random.uniform(1.0, 2.0))

    log.info("カーセンサー相場: %d件", len(listings))
    return listings


# ─────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────

def fetch_market_listings(max_pages: int = 3) -> list[dict]:
    """
    グーネット + カーセンサーから相場データを取得して合算する。

    Args:
        max_pages: 各ソースのページ数上限

    Returns:
        市場価格比較用の車両リスト
    """
    listings: list[dict] = []

    goonet = fetch_goonet_listings(max_pages=max_pages)
    listings.extend(goonet)

    carsensor = fetch_carsensor_listings(max_pages=max_pages)
    listings.extend(carsensor)

    log.info("市場データ合計（グーネット+カーセンサー）: %d件", len(listings))
    return listings
