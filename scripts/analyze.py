"""
割安車両分析モジュール
同条件の車両リストから市場中央値を算出し、割安度を判定する。
公式ディーラー listings を グーネット market_listings と比較する。
"""
import statistics
from typing import TypedDict


class BargainCar(TypedDict):
    brand:         str
    name:          str
    grade:         str
    year:          int
    mileage_km:    int       # km単位（例: 21000）
    mileage_display: str     # 表示用（例: "2.1万km"）
    color:         str
    color_emoji:   str
    pref:          str
    shop:          str
    price:         int
    url:           str
    is_new:        bool
    market_median: int       # 相場中央値（万円）
    discount:      int       # 割安額（万円）
    discount_pct:  float
    compare_count: int
    year_range:    str
    mileage_range: str


# 走行距離帯（ユーザー指定）
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


def find_bargains(
    listings: list[dict],
    market_listings: "list[dict] | None" = None,
    discount_threshold: int = 10,
    top_n: int = 10,
    year_band_width: int = 1,
    min_peers: int = 2,
) -> "list[BargainCar]":
    """
    割安な車両を検出して返す（割安額の降順）。

    Args:
        listings:           公式ディーラーの車両リスト
        market_listings:    グーネット等の市場比較用リスト。
                            指定時はこちらを相場中央値の計算に使う。
                            None の場合は listings 内で比較する。
        discount_threshold: 割安と判定する最低差額（万円）
        top_n:              返す最大件数
        year_band_width:    年式帯の幅（±N年）
        min_peers:          比較に必要な最少ピア数
    """
    # 比較用データソースを決定
    comparison_pool = market_listings if market_listings else listings

    bargains: list[BargainCar] = []

    for car in listings:
        try:
            car_year     = int(car["year"])
            car_mileage  = int(car["mileage_km"])
            car_price    = int(car["price"])
        except (ValueError, TypeError):
            continue

        year_lo, year_hi = _year_band(car_year, year_band_width)
        band = _mileage_band(car_mileage)
        if band is None:
            continue
        mileage_lo, mileage_hi = band

        # 同車種・同年式帯・同走行距離帯のピアを抽出
        peers = []
        for c in comparison_pool:
            if c is car:
                continue
            try:
                if (
                    c["name"] == car["name"]
                    and year_lo <= int(c["year"]) <= year_hi
                    and mileage_lo <= int(c["mileage_km"]) <= mileage_hi
                ):
                    peers.append(int(c["price"]))
            except (ValueError, TypeError):
                continue

        # ピア不足はスキップ
        if len(peers) < min_peers:
            continue

        median       = statistics.median(peers)
        discount     = int(median) - car_price
        discount_pct = discount / median * 100 if median > 0 else 0.0

        if discount < discount_threshold:
            continue

        mileage_man    = car_mileage / 10_000
        mileage_lo_man = mileage_lo / 10_000
        mileage_hi_man = mileage_hi / 10_000

        bargains.append(BargainCar(
            brand=car["brand"],
            name=car["name"],
            grade=car.get("grade", ""),
            year=car_year,
            mileage_km=car_mileage,
            mileage_display=f"{mileage_man:.1f}万km",
            color=car.get("color", ""),
            color_emoji=car.get("color_emoji", ""),
            pref=car.get("pref", ""),
            shop=car.get("shop", ""),
            price=car_price,
            url=car.get("url", "#"),
            is_new=car.get("is_new", False),
            market_median=int(median),
            discount=discount,
            discount_pct=round(discount_pct, 1),
            compare_count=len(peers),
            year_range=f"{year_lo}〜{year_hi}年",
            mileage_range=f"{mileage_lo_man:.1f}〜{mileage_hi_man:.1f}万km",
        ))

    # 新着を優先、次に割安額の大きい順
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
