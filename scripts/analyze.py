"""
割安車両分析モジュール
同条件の車両リストから市場中央値を算出し、割安度を判定する。
"""
import statistics
from typing import TypedDict


class BargainCar(TypedDict):
    brand: str
    name: str
    grade: str
    year: int
    mileage_km: int       # km単位（例: 21000）
    mileage_display: str  # 表示用（例: "2.1万km"）
    color: str
    color_emoji: str
    pref: str
    shop: str
    price: int
    url: str
    is_new: bool
    market_median: int    # 相場中央値（万円）
    discount: int         # 割安額（万円）
    discount_pct: float
    compare_count: int
    year_range: str
    mileage_range: str


def _year_band(year: int, width: int = 1) -> tuple[int, int]:
    return (year - width, year + width)


def _mileage_band(mileage_km: int, band_size: int = 50000) -> tuple[int, int]:
    """走行距離を band_size km 幅の帯にまとめる。"""
    lower = (mileage_km // band_size) * band_size
    return (lower, lower + band_size)


def find_bargains(
    listings: list[dict],
    discount_threshold: int = 10,
    top_n: int = 5,
    year_band_width: int = 1,
) -> list["BargainCar"]:
    """
    割安な車両を検出して返す（割安額の降順）。

    Args:
        listings: 車両リスト（fetch_listings.fetch_all_listings の返り値）
        discount_threshold: 割安と判定する最低差額（万円）
        top_n: 返す最大件数
        year_band_width: 年式帯の幅（±N年）
    """
    bargains: list[BargainCar] = []

    for car in listings:
        year_lo, year_hi = _year_band(car["year"], year_band_width)
        mileage_lo, mileage_hi = _mileage_band(car["mileage_km"])

        peers = [
            c["price"] for c in listings
            if (
                c["name"] == car["name"]
                and c["grade"] == car["grade"]
                and year_lo <= c["year"] <= year_hi
                and mileage_lo <= c["mileage_km"] <= mileage_hi
                and c is not car
            )
        ]

        if len(peers) < 3:
            continue

        median = statistics.median(peers)
        discount = int(median) - car["price"]
        discount_pct = discount / median * 100 if median > 0 else 0

        if discount < discount_threshold:
            continue

        mileage_man_km = car["mileage_km"] / 10000
        mileage_display = f"{mileage_man_km:.1f}万km"

        mileage_lo_man = mileage_lo // 10000
        mileage_hi_man = mileage_hi // 10000

        bargains.append(BargainCar(
            brand=car["brand"],
            name=car["name"],
            grade=car["grade"],
            year=car["year"],
            mileage_km=car["mileage_km"],
            mileage_display=mileage_display,
            color=car["color"],
            color_emoji=car["color_emoji"],
            pref=car["pref"],
            shop=car["shop"],
            price=car["price"],
            url=car["url"],
            is_new=car["is_new"],
            market_median=int(median),
            discount=discount,
            discount_pct=round(discount_pct, 1),
            compare_count=len(peers),
            year_range=f"{year_lo}〜{year_hi}年",
            mileage_range=f"{mileage_lo_man}〜{mileage_hi_man}万km",
        ))

    # 割安額の大きい順（UIデザイナー指摘：最もお得な物件を先頭に）
    bargains.sort(key=lambda c: c["discount"], reverse=True)
    return bargains[:top_n]


def summarize(bargains: list["BargainCar"]) -> dict:
    """サマリーカード用の集計値を返す。"""
    if not bargains:
        return {
            "count": 0,
            "avg_discount": 0.0,
            "brands": [],
            "area": "関東",
        }

    brands = sorted({c["brand"] for c in bargains})
    avg_discount = round(sum(c["discount"] for c in bargains) / len(bargains), 1)

    return {
        "count": len(bargains),
        "avg_discount": avg_discount,
        "brands": brands,
        "area": "関東",
    }
