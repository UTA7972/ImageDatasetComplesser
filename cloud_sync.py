import os
import sys
import csv
import shutil
import hashlib
import time
from pathlib import Path

INDEX_FILENAME = "folder_index.csv"

# CSVヘッダー定義
# 整理番号, タイプ, 名前, 相対パス, 処理状態
FIELDNAMES = ["整理番号", "タイプ", "名前", "相対パス", "処理状態"]


def scan_and_build_index(source_dir):
    """
    処理対象フォルダ配下のすべてのフォルダおよびファイルを再帰的に探索し、
    folder_index 用のリストを生成します。

    :param source_dir: 処理対象 (コピー元) フォルダのパス
    :return: 整理番号、タイプ、名前、相対パス、処理状態 (初期値 0) を含む辞書のリスト
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
                "処理状態": "0"
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
                "処理状態": "0"
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
        writer.writerows(entries)


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
            # 必要なキーが存在するか検証
            for field in FIELDNAMES:
                if field not in row:
                    raise ValueError(f"CSVフォーマットが無効です ('{field}' カラムが見つかりません): {csv_path}")
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


def is_same_content(src_path, dest_path):
    """
    コピー元とコピー先のファイル内容が同一かどうかを検証します。
    1. ファイルサイズの比較
    2. サイズ一致時は MD5 ハッシュ値の比較
    """
    if not dest_path.exists():
        return False
    if not src_path.exists():
        return False

    # ディレクトリの場合
    if src_path.is_dir() and dest_path.is_dir():
        return True

    # ファイルサイズの比較
    try:
        if src_path.stat().st_size != dest_path.stat().st_size:
            return False
    except OSError:
        return False

    # ハッシュ値比較
    try:
        src_hash = compute_file_hash(src_path)
        dest_hash = compute_file_hash(dest_path)
        return src_hash == dest_hash
    except OSError:
        return False


def copy_file_robust(src_path, dest_path, chunk_size=2 * 1024 * 1024, max_retries=3, delay=1.0):
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
                    df.flush()

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
                # 最終フォールバック: 直接書き込み
                try:
                    with open(src_path, "rb") as sf, open(dest_path, "wb") as df:
                        while chunk := sf.read(chunk_size):
                            df.write(chunk)
                    return True
                except Exception as final_e:
                    raise IOError(f"コピー失敗 ({src_path} -> {dest_path}): {final_e}")
            time.sleep(delay * attempt)


def process_cloud_sync(source_dir, dest_dir, index_csv_path=None, progress_callback=None, cancel_event=None):
    """
    folder_index.csv に従って安定的にファイルをコピーし、処理状態を1に更新します。

    :param source_dir: コピー元フォルダのパス
    :param dest_dir: コピー先フォルダのパス
    :param index_csv_path: 途中再開用の index.csv パス (None の場合は新規自動生成)
    :param progress_callback: 進捗通知用のコールバック関数 callback(status_dict)
    :param cancel_event: キャンセル要求判定用の threading.Event
    :return: 処理結果サマリー dict
    """
    source_path = Path(source_dir).resolve()
    dest_path = Path(dest_dir).resolve()

    if not source_path.exists() or not source_path.is_dir():
        raise ValueError(f"コピー元フォルダが存在しません: {source_dir}")

    dest_path.mkdir(parents=True, exist_ok=True)

    # インデックスデータの準備
    if index_csv_path and Path(index_csv_path).exists():
        index_file = Path(index_csv_path).resolve()
        entries = load_index_csv(index_file)
        if progress_callback:
            progress_callback({"type": "info", "message": f"既存のインデックスファイルを読み込みました: {index_file}"})
    else:
        index_file = source_path / INDEX_FILENAME
        if progress_callback:
            progress_callback({"type": "info", "message": f"フォルダ構造をスキャンしてインデックスを作成中..."})
        entries = scan_and_build_index(source_path)
        save_index_csv(index_file, entries)
        if progress_callback:
            progress_callback({"type": "info", "message": f"インデックスを生成しました: {index_file} ({len(entries)} 項目)"})

    # コピー先にもインデックスのコピーを保存/更新
    dest_index_file = dest_path / INDEX_FILENAME

    total_items = len(entries)
    completed_count = sum(1 for e in entries if str(e.get("処理状態")) == "1")
    skipped_count = 0
    copied_count = 0
    error_count = 0

    if progress_callback:
        progress_callback({
            "type": "start",
            "total": total_items,
            "completed": completed_count,
            "message": f"転送開始 (全 {total_items} 項目中、残り {total_items - completed_count} 項目)"
        })

    for idx, entry in enumerate(entries, 1):
        if cancel_event and cancel_event.is_set():
            if progress_callback:
                progress_callback({"type": "cancelled", "message": "ユーザーによって処理が中断されました。"})
            break

        # すでに処理完了(1) の場合はスキップ
        if str(entry.get("処理状態")) == "1":
            continue

        item_type = entry.get("タイプ", "ファイル")
        rel_path = entry.get("相対パス", "")
        seq_num = entry.get("整理番号", "")
        item_name = entry.get("名前", "")

        src_item = source_path / rel_path
        dest_item = dest_path / rel_path

        item_status = "0"
        msg = ""

        try:
            if item_type == "フォルダー":
                dest_item.mkdir(parents=True, exist_ok=True)
                item_status = "1"
                copied_count += 1
                msg = f"[{seq_num}/{total_items}] フォルダ作成: {rel_path}"
            else:
                # ファイル処理
                if not src_item.exists():
                    msg = f"[{seq_num}/{total_items}] 警告: コピー元ファイルが存在しません: {rel_path}"
                    if progress_callback:
                        progress_callback({"type": "warning", "message": msg})
                    error_count += 1
                    continue

                if is_same_content(src_item, dest_item):
                    item_status = "1"
                    skipped_count += 1
                    msg = f"[{seq_num}/{total_items}] 内容一致のためスキップ: {rel_path}"
                else:
                    copy_file_robust(src_item, dest_item)
                    item_status = "1"
                    copied_count += 1
                    msg = f"[{seq_num}/{total_items}] コピー完了: {rel_path}"

            # 処理完了状態(1)に更新
            entry["処理状態"] = item_status
            completed_count += 1

            # インデックスファイルを都度更新保存 (中断対策)
            save_index_csv(index_file, entries)
            try:
                save_index_csv(dest_index_file, entries)
            except Exception:
                pass

            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "current": idx,
                    "total": total_items,
                    "completed": completed_count,
                    "seq": seq_num,
                    "item_name": item_name,
                    "rel_path": rel_path,
                    "message": msg
                })

        except Exception as e:
            error_count += 1
            err_msg = f"[{seq_num}/{total_items}] エラー ({rel_path}): {e}"
            if progress_callback:
                progress_callback({"type": "error", "message": err_msg})

    return {
        "status": "completed" if not (cancel_event and cancel_event.is_set()) else "cancelled",
        "total": total_items,
        "completed": completed_count,
        "copied": copied_count,
        "skipped": skipped_count,
        "errors": error_count,
        "index_file": str(index_file)
    }
