"""
割安車両分析モジュール
同条件の車両リストから市場中央値を算出し、割安度を判定する。
比較条件: 車名・グレード一致 / 年式±1年 / 走行距離帯 / 色補正
"""
import statistics
from typing import TypedDict


class BargainCar(TypedDict):
    brand:           str
    name:            str
    grade:           str
    year:            int
    mileage_km:      int       # km単位（例: 21000）
    mileage_display: str       # 表示用（例: "2.1万km"）
    color:           str
    color_emoji:     str
    pref:            str
    shop:            str
    price:           int       # 支払総額（補正前・万円）
    price_adj:       int       # 色補正後の実質価格（万円）
    url:             str
    is_new:          bool
    market_median:   int       # 相場中央値（色補正済み・万円）
    discount:        int       # 実質割安額（color_adj適用後・万円）
    discount_pct:    float
    compare_count:   int
    year_range:      str
    mileage_range:   str
    color_premium:   int       # プレミアムカラー補正額（万円）


# ─────────────────────────────────────────────
# 走行距離帯
# ─────────────────────────────────────────────

MILEAGE_BANDS = [
    (5_000,  25_000),   # 0.5〜2.5万km
    (26_000, 49_000),   # 2.6〜4.9万km
    (50_000, 74_000),   # 5.0〜7.4万km
    (75_000, 99_000),   # 7.5〜9.9万km
]


def _year_band(year: int, width: int = 1) -> tuple[int, int]:
    return (year - width, year + width)


def _mileage_band(mileage_km: int) -> "tuple[int, int] | None":
    for lo, hi in MILEAGE_BANDS:
        if lo <= mileage_km <= hi:
            return (lo, hi)
    return None


# ─────────────────────────────────────────────
# 色補正
# ─────────────────────────────────────────────

# 白・黒・パール系はオプション価格が高く、相場も約+10万円高い
PREMIUM_COLOR_KEYWORDS = (
    "白", "黒", "パール", "ホワイト", "ブラック",
    "プラチナ", "プレミアム", "クリスタル",
)
COLOR_PREMIUM_YEN = 10  # 万円


def _color_premium(color: str) -> int:
    """プレミアムカラーなら +10（万円）、それ以外は 0 を返す。"""
    if not color:
        return 0
    return COLOR_PREMIUM_YEN if any(kw in color for kw in PREMIUM_COLOR_KEYWORDS) else 0


def _normalized_price(price: int, color: str) -> int:
    """価格を「標準色換算」に正規化する（プレミアムカラーは -10万円）。"""
    return price - _color_premium(color)


# ─────────────────────────────────────────────
# 割安判定
# ─────────────────────────────────────────────

def find_bargains(
    listings: list[dict],
    market_listings: "list[dict] | None" = None,
    discount_threshold: int = 10,
    top_n: int = 10,
    year_band_width: int = 1,
    min_peers: int = 2,
) -> "list[BargainCar]":
    """
    割安な車両を検出して返す。

    比較条件:
      - 車名が完全一致
      - グレードが完全一致（空文字同士もOK）
      - 年式が ±year_band_width 年以内
      - 走行距離が同じ帯に属する
      - 価格は「色補正後（標準色換算）」で比較

    Args:
        listings:           公式ディーラーの車両リスト
        market_listings:    グーネット+カーセンサー等の市場比較用リスト。
                            None の場合は listings 内で比較する。
        discount_threshold: 割安と判定する最低差額（万円）
        top_n:              返す最大件数
        year_band_width:    年式帯の幅（±N年）。デフォルト1（=±1年）
        min_peers:          比較に必要な最少ピア数
    """
    comparison_pool = market_listings if market_listings else listings

    bargains: list[BargainCar] = []

    for car in listings:
        try:
            car_year    = int(car["year"])
            car_mileage = int(car["mileage_km"])
            car_price   = int(car["price"])
        except (ValueError, TypeError):
            continue

        year_lo, year_hi = _year_band(car_year, year_band_width)
        band = _mileage_band(car_mileage)
        if band is None:
            continue
        mileage_lo, mileage_hi = band

        car_grade     = car.get("grade", "") or ""
        car_color     = car.get("color", "") or ""
        car_price_adj = _normalized_price(car_price, car_color)

        # 同車種・同グレード・同年式帯・同走行距離帯のピア価格を収集（色補正後）
        peers_adj: list[int] = []
        for c in comparison_pool:
            if c is car:
                continue
            try:
                peer_grade = c.get("grade", "") or ""
                if (
                    c["name"] == car["name"]
                    and peer_grade == car_grade          # グレード一致
                    and year_lo <= int(c["year"]) <= year_hi
                    and mileage_lo <= int(c["mileage_km"]) <= mileage_hi
                ):
                    peer_color     = c.get("color", "") or ""
                    peer_price_adj = _normalized_price(int(c["price"]), peer_color)
                    peers_adj.append(peer_price_adj)
            except (ValueError, TypeError):
                continue

        if len(peers_adj) < min_peers:
            continue

        median_adj   = statistics.median(peers_adj)
        discount     = int(median_adj) - car_price_adj
        discount_pct = discount / median_adj * 100 if median_adj > 0 else 0.0

        if discount < discount_threshold:
            continue

        color_premium  = _color_premium(car_color)
        mileage_man    = car_mileage / 10_000
        mileage_lo_man = mileage_lo / 10_000
        mileage_hi_man = mileage_hi / 10_000

        bargains.append(BargainCar(
            brand=car["brand"],
            name=car["name"],
            grade=car_grade,
            year=car_year,
            mileage_km=car_mileage,
            mileage_display=f"{mileage_man:.1f}万km",
            color=car_color,
            color_emoji=car.get("color_emoji", "") or "",
            pref=car.get("pref", "") or "",
            shop=car.get("shop", "") or "",
            price=car_price,
            price_adj=car_price_adj,
            url=car.get("url", "#"),
            is_new=car.get("is_new", False),
            market_median=int(median_adj),
            discount=discount,
            discount_pct=round(discount_pct, 1),
            compare_count=len(peers_adj),
            year_range=f"{year_lo}〜{year_hi}年",
            mileage_range=f"{mileage_lo_man:.1f}〜{mileage_hi_man:.1f}万km",
            color_premium=color_premium,
        ))

    # 新着優先、次に割安額の大きい順
    bargains.sort(key=lambda c: (-int(c["is_new"]), -c["discount"]))
    return bargains[:top_n]


def summarize(bargains: "list[BargainCar]") -> dict:
    """サマリーカード用の集計値を返す。"""
    if not bargains:
        return {
            "count":        0,
            "avg_discount": 0.0,
            "new_count":    0,
            "brands":       [],
            "area":         "関東",
        }

    brands       = sorted({c["brand"] for c in bargains})
    avg_discount = round(sum(c["discount"] for c in bargains) / len(bargains), 1)
    new_count    = sum(1 for c in bargains if c["is_new"])

    return {
        "count":        len(bargains),
        "avg_discount": avg_discount,
        "new_count":    new_count,
        "brands":       brands,
        "area":         "関東",
    }
