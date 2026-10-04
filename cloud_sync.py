import os
import sys
import csv
import shutil
import hashlib
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

INDEX_FILENAME = "folder_index.csv"

# CSVヘッダー定義
# 整理番号, タイプ, 名前, 相対パス, 処理状態, ファイル比較
FIELDNAMES = ["整理番号", "タイプ", "名前", "相対パス", "処理状態", "ファイル比較"]


def scan_and_build_index(source_dir):
    """
    処理対象フォルダ配下のすべてのフォルダおよびファイルを再帰的に探索し、
    folder_index 用のリストを生成します。

    :param source_dir: 処理対象 (コピー元) フォルダのパス
    :return: 整理番号、タイプ、名前、相対パス、処理状態 (初期値 0)、ファイル比較 (初期値 1) を含む辞書のリスト
    """
    source_path = Path(source_dir).resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f"指定された処理対象フォルダが存在しません: {source_dir}")

    entries = []
    seq_num = 1

    # topdown=True で走査し、親フォルダが必ず先に登録されるようにする
    for root, dirs, files in os.walk(source_path, topdown=True):
        current_root = Path(root)
        dirs.sort()
        files.sort()

        # ルートフォルダ直下以外のサブフォルダを記録
        if current_root != source_path:
            rel_path = current_root.relative_to(source_path).as_posix()
            folder_name = current_root.name
            entries.append({
                "整理番号": str(seq_num),
                "タイプ": "フォルダー",
                "名前": folder_name,
                "相対パス": rel_path,
                "処理状態": "0",
                "ファイル比較": "1"
            })
            seq_num += 1

        # ファイルを記録 (インデックスファイル自体は対象外)
        for f in files:
            if f == INDEX_FILENAME:
                continue
            file_path = current_root / f
            rel_path = file_path.relative_to(source_path).as_posix()
            entries.append({
                "整理番号": str(seq_num),
                "タイプ": "ファイル",
                "名前": f,
                "相対パス": rel_path,
                "処理状態": "0",
                "ファイル比較": "1"
            })
            seq_num += 1

    return entries


def save_index_csv(csv_path, entries):
    """
    folder_index を CSV ファイルに保存します (UTF-8 with BOM)。

    :param csv_path: 保存先の CSV パス
    :param entries: インデックスデータのリスト
    """
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for e in entries:
            row = {
                "整理番号": str(e.get("整理番号", "")),
                "タイプ": str(e.get("タイプ", "ファイル")),
                "名前": str(e.get("名前", "")),
                "相対パス": str(e.get("相対パス", "")),
                "処理状態": str(e.get("処理状態", "0")),
                "ファイル比較": str(e.get("ファイル比較", "1"))
            }
            writer.writerow(row)


def load_index_csv(csv_path):
    """
    既存の folder_index.csv からインデックスデータを読み込みます。

    :param csv_path: インデックス CSV パス
    :return: 辞書のリスト
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"指定されたインデックスファイルが存在しません: {csv_path}")

    entries = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for field in ["整理番号", "タイプ", "名前", "相対パス"]:
                if field not in row:
                    raise ValueError(f"CSVフォーマットが無効です ('{field}' カラムが見つかりません): {csv_path}")
            if "処理状態" not in row:
                row["処理状態"] = "0"
            if "ファイル比較" not in row:
                row["ファイル比較"] = "1"
            entries.append(dict(row))
    return entries


def compute_file_hash(file_path, chunk_size=1024 * 1024):
    """
    ファイルの MD5 ハッシュ値を計算します。
    """
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_same_content(src_path, dest_path, use_hash=False, mtime_tolerance=1.5):
    """
    コピー元とコピー先のファイル内容が同一かどうかを検証します。
    - use_hash=False (デフォルト): ファイルサイズ + 更新日時 (mtime) 比較
    - use_hash=True: ファイルサイズ一致時、MD5 ハッシュ値比較
    """
    if not dest_path.exists() or not src_path.exists():
        return False

    if src_path.is_dir() and dest_path.is_dir():
        return True

    try:
        src_stat = src_path.stat()
        dest_stat = dest_path.stat()

        if src_stat.st_size != dest_stat.st_size:
            return False

        if not use_hash:
            return abs(src_stat.st_mtime - dest_stat.st_mtime) <= mtime_tolerance
        else:
            src_hash = compute_file_hash(src_path)
            dest_hash = compute_file_hash(dest_path)
            return src_hash == dest_hash
    except OSError:
        return False


def copy_file_robust(src_path, dest_path, chunk_size=2 * 1024 * 1024, max_retries=3, delay=0.5):
    """
    クラウドストレージやネットワーク環境での安定したファイルコピー。
    チャンク単位での読み書きとリトライ処理を行います。
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dest = dest_path.parent / f"{dest_path.name}.tmp_sync"

    for attempt in range(1, max_retries + 1):
        try:
            with open(src_path, "rb") as sf, open(temp_dest, "wb") as df:
                while chunk := sf.read(chunk_size):
                    df.write(chunk)

            try:
                shutil.copystat(src_path, temp_dest)
            except Exception:
                pass

            if dest_path.exists():
                try:
                    os.remove(dest_path)
                except Exception:
                    pass

            shutil.move(str(temp_dest), str(dest_path))
            return True
        except Exception as e:
            if temp_dest.exists():
                try:
                    os.remove(temp_dest)
                except Exception:
                    pass

            if attempt == max_retries:
                try:
                    shutil.copy2(src_path, dest_path)
                    return True
                except Exception as final_e:
                    raise IOError(f"コピー失敗 ({src_path} -> {dest_path}): {final_e}")
            time.sleep(delay * attempt)


# =========================================================================
# 三段階処理関数
# =========================================================================

def build_cloud_index(source_dir, index_csv_path=None, progress_callback=None):
    """
    [段階1] フォルダ構造をスキャンして folder_index.csv を作成します。
    """
    source_path = Path(source_dir).resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f"コピー元フォルダが存在しません: {source_dir}")

    index_file = Path(index_csv_path).resolve() if index_csv_path else source_path / INDEX_FILENAME

    if progress_callback:
        progress_callback({"type": "info", "message": "フォルダ構造をスキャンしてインデックスを作成中..."})

    entries = scan_and_build_index(source_path)
    save_index_csv(index_file, entries)

    if progress_callback:
        progress_callback({"type": "info", "message": f"インデックスを生成しました: {index_file} ({len(entries)} 項目)"})

    return {
        "status": "completed",
        "total": len(entries),
        "index_file": str(index_file),
        "entries": entries
    }


def compare_cloud_files(source_dir, dest_dir, index_csv_path=None, use_hash=False, num_workers=8, progress_callback=None, cancel_event=None):
    """
    [段階2] 対象フォルダのファイルを比較し、folder_index.csv の「ファイル比較」列を更新します。
    - 同一(コピー不要)なら "0"
    - 異なる/存在しない(コピー必要)なら "1"
    """
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()
    index_file = Path(index_csv_path).resolve() if index_csv_path else source_path / INDEX_FILENAME
    dest_index_file = dest_path / INDEX_FILENAME

    if not index_file.exists():
        entries = scan_and_build_index(source_path)
        save_index_csv(index_file, entries)
    else:
        entries = load_index_csv(index_file)

    dest_path.mkdir(parents=True, exist_ok=True)
    total_items = len(entries)
    mode_str = "MD5ハッシュ検証" if use_hash else "サイズ & 更新日時検証"

    if progress_callback:
        progress_callback({
            "type": "start",
            "total": total_items,
            "completed": 0,
            "message": f"ファイル比較開始 ({mode_str}, 並列スレッド: {num_workers})"
        })

    def _worker(entry_idx, entry):
        if cancel_event and cancel_event.is_set():
            return entry_idx, None
        item_type = entry.get("タイプ", "ファイル")
        rel_path = entry.get("相対パス", "")
        src_item = source_path / rel_path
        dest_item = dest_path / rel_path

        if item_type == "フォルダー":
            is_same = dest_item.exists() and dest_item.is_dir()
        else:
            is_same = is_same_content(src_item, dest_item, use_hash=use_hash)

        cmp_status = "0" if is_same else "1"
        return entry_idx, cmp_status

    completed = 0
    same_count = 0
    diff_count = 0
    processed_since_last_save = 0

    num_workers = max(1, num_workers)
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_worker, idx, entry) for idx, entry in enumerate(entries)]
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                break
            idx, cmp_status = future.result()
            if cmp_status is None:
                continue

            entries[idx]["ファイル比較"] = cmp_status
            completed += 1
            processed_since_last_save += 1

            if cmp_status == "0":
                same_count += 1
            else:
                diff_count += 1

            # 100件ごとに書き込み保存
            if processed_since_last_save >= 100:
                save_index_csv(index_file, entries)
                try:
                    save_index_csv(dest_index_file, entries)
                except Exception:
                    pass
                processed_since_last_save = 0

            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "current": completed,
                    "total": total_items,
                    "completed": completed,
                    "seq": entries[idx].get("整理番号", ""),
                    "item_name": entries[idx].get("名前", ""),
                    "rel_path": entries[idx].get("相対パス", ""),
                    "message": f"比較進捗 [{completed}/{total_items}]: 差分あり={diff_count}, 一致={same_count}"
                })

    # 最終保存
    save_index_csv(index_file, entries)
    try:
        save_index_csv(dest_index_file, entries)
    except Exception:
        pass

    return {
        "status": "completed" if not (cancel_event and cancel_event.is_set()) else "cancelled",
        "total": total_items,
        "completed": completed,
        "same": same_count,
        "diff": diff_count,
        "index_file": str(index_file)
    }


def copy_cloud_files(source_dir, dest_dir, index_csv_path=None, num_workers=8, progress_callback=None, cancel_event=None):
    """
    [段階3] 「ファイル比較」が "1" (コピー必要) の項目のみをマルチスレッドでコピーし、「処理状態」を "1" に更新します。
    """
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()
    index_file = Path(index_csv_path).resolve() if index_csv_path else source_path / INDEX_FILENAME
    dest_index_file = dest_path / INDEX_FILENAME

    if not index_file.exists():
        entries = scan_and_build_index(source_path)
        save_index_csv(index_file, entries)
    else:
        entries = load_index_csv(index_file)

    dest_path.mkdir(parents=True, exist_ok=True)
    total_items = len(entries)

    # コピー対象: ファイル比較 == "1" かつ 処理状態 != "1"
    target_entries = [
        (idx, entry) for idx, entry in enumerate(entries)
        if str(entry.get("ファイル比較", "1")) == "1" and str(entry.get("処理状態", "0")) != "1"
    ]

    already_done = total_items - len(target_entries)
    copied_count = 0
    error_count = 0
    processed_since_last_save = 0

    if progress_callback:
        progress_callback({
            "type": "start",
            "total": total_items,
            "completed": already_done,
            "message": f"転送開始 (コピー対象: {len(target_entries)}件 / 全{total_items}件, 並列スレッド: {num_workers})"
        })

    def _copy_worker(entry_idx, entry):
        if cancel_event and cancel_event.is_set():
            return entry_idx, False, "cancelled"

        item_type = entry.get("タイプ", "ファイル")
        rel_path = entry.get("相対パス", "")
        src_item = source_path / rel_path
        dest_item = dest_path / rel_path

        try:
            if item_type == "フォルダー":
                dest_item.mkdir(parents=True, exist_ok=True)
                return entry_idx, True, f"フォルダ作成: {rel_path}"
            else:
                if not src_item.exists():
                    return entry_idx, False, f"警告: コピー元が存在しません: {rel_path}"
                copy_file_robust(src_item, dest_item)
                return entry_idx, True, f"コピー完了: {rel_path}"
        except Exception as e:
            return entry_idx, False, f"エラー ({rel_path}): {e}"

    num_workers = max(1, num_workers)
    completed_total = already_done

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_copy_worker, idx, entry) for idx, entry in target_entries]
        for future in as_completed(futures):
            if cancel_event and cancel_event.is_set():
                break
            idx, success, msg = future.result()
            if msg == "cancelled":
                continue

            completed_total += 1
            processed_since_last_save += 1

            if success:
                entries[idx]["処理状態"] = "1"
                copied_count += 1
            else:
                error_count += 1

            # 100件ごとに書き込み保存
            if processed_since_last_save >= 100:
                save_index_csv(index_file, entries)
                try:
                    save_index_csv(dest_index_file, entries)
                except Exception:
                    pass
                processed_since_last_save = 0

            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "current": completed_total,
                    "total": total_items,
                    "completed": completed_total,
                    "seq": entries[idx].get("整理番号", ""),
                    "item_name": entries[idx].get("名前", ""),
                    "rel_path": entries[idx].get("相対パス", ""),
                    "message": f"転送進捗 [{completed_total}/{total_items}]: {msg}"
                })

    # 最終保存
    save_index_csv(index_file, entries)
    try:
        save_index_csv(dest_index_file, entries)
    except Exception:
        pass

    return {
        "status": "completed" if not (cancel_event and cancel_event.is_set()) else "cancelled",
        "total": total_items,
        "completed": completed_total,
        "copied": copied_count,
        "skipped": total_items - copied_count - error_count,
        "errors": error_count,
        "index_file": str(index_file)
    }


def process_cloud_sync(source_dir, dest_dir, index_csv_path=None, use_hash=False, num_workers=8, progress_callback=None, cancel_event=None):
    """
    一括実行用関数 (段階1 → 段階2 → 段階3 を連続して実行します)
    """
    index_file = Path(index_csv_path).resolve() if index_csv_path else Path(source_dir).resolve() / INDEX_FILENAME
    if not index_file.exists():
        build_cloud_index(source_dir, index_csv_path=index_csv_path, progress_callback=progress_callback)

    res_cmp = compare_cloud_files(
        source_dir, dest_dir, index_csv_path=index_csv_path,
        use_hash=use_hash, num_workers=num_workers,
        progress_callback=progress_callback, cancel_event=cancel_event
    )

    if cancel_event and cancel_event.is_set():
        return res_cmp

    res_copy = copy_cloud_files(
        source_dir, dest_dir, index_csv_path=index_csv_path,
        num_workers=num_workers,
        progress_callback=progress_callback, cancel_event=cancel_event
    )
    return res_copy

