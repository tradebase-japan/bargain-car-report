"""
新着物件追跡モジュール
seen_ids.json を使って既通知の車両IDを管理し、新着物件を検出する。
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = "seen_ids.json"


def load_seen_ids(path: str = DEFAULT_PATH) -> set[str]:
    """
    seen_ids.json から既通知の車両IDセットを読み込む。
    ファイルが存在しない場合は空セットを返す。
    """
    p = Path(path)
    if not p.exists():
        log.info("seen_ids.json が存在しません。新規作成します。")
        return set()
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        seen = set(data) if isinstance(data, list) else set()
        log.info("既通知ID: %d件読み込み", len(seen))
        return seen
    except (json.JSONDecodeError, OSError) as e:
        log.warning("seen_ids.json 読み込みエラー: %s", e)
        return set()


def save_seen_ids(seen_ids: set[str], path: str = DEFAULT_PATH) -> None:
    """
    既通知の車両IDセットを seen_ids.json に保存する。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump(sorted(seen_ids), f, ensure_ascii=False, indent=2)
        log.info("seen_ids.json 保存: %d件", len(seen_ids))
    except OSError as e:
        log.warning("seen_ids.json 保存エラー: %s", e)


def mark_new_listings(listings: list[dict], seen_ids: set[str]) -> list[dict]:
    """
    リストの各車両について、seen_ids に含まれない場合に is_new=True を付与して返す。
    リスト自体はフィルタしない（全件返す）。
    """
    marked: list[dict] = []
    new_count = 0
    for car in listings:
        car_id = car.get("id", "")
        is_new_detected = car_id not in seen_ids
        if is_new_detected:
            new_count += 1
        marked.append({**car, "is_new": is_new_detected})
    log.info("新着検出: %d件 / 全 %d件", new_count, len(listings))
    return marked


def update_seen_ids(seen_ids: set[str], listings: list[dict]) -> set[str]:
    """
    今回取得した全車両 ID を seen_ids に追加して返す（上限 50,000 件）。
    """
    new_set = seen_ids | {car["id"] for car in listings if car.get("id")}
    # 古い ID が増えすぎないよう上限を設ける
    if len(new_set) > 50_000:
        # 古い順（ソート後の先頭）から削除
        sorted_ids = sorted(new_set)
        new_set = set(sorted_ids[-50_000:])
    return new_set
