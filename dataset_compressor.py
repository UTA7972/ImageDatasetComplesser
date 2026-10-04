import os
import csv
import glob
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.tif', '.raw', '.ppm', '.pgm', '.pbm', '.pnm'}
UNCOMPRESSED_EXTENSIONS = {'.bmp', '.tif', '.tiff', '.raw', '.ppm', '.pgm', '.pbm', '.pnm'}

def is_image_file(filepath):
    return Path(filepath).suffix.lower() in IMAGE_EXTENSIONS

def scan_datasets(root_dir, min_images=20):
    """
    指定されたルートディレクトリ以下を再帰的にスキャンし、
    20枚以上の画像ファイルが存在するディレクトリのリストを返します。
    """
    dataset_folders = []
    root_path = Path(root_dir)
    
    if not root_path.exists():
        return dataset_folders

    for dirpath, dirnames, filenames in os.walk(root_path):
        image_files = [f for f in filenames if Path(f).suffix.lower() in IMAGE_EXTENSIONS]
        if len(image_files) >= min_images:
            dataset_folders.append(Path(dirpath))
            
    return dataset_folders

def _inspect_image_worker(p_str):
    """
    並列処理用の画像ヘッダー探査ワーカー:
    画像の解像度 (w, h)、アルファチャネル有無、非圧縮形式かどうかを判定します。
    """
    p = Path(p_str)
    ext = p.suffix.lower()
    is_uncomp = ext in UNCOMPRESSED_EXTENSIONS
    try:
        with Image.open(p) as img:
            w, h = img.size
            has_alpha = img.mode in ('RGBA', 'LA', 'PA') or 'transparency' in img.info
            return {
                'success': True,
                'filepath': p_str,
                'filename': p.name,
                'width': w,
                'height': h,
                'has_alpha': has_alpha,
                'is_uncompressed': is_uncomp
            }
    except Exception as e:
        return {
            'success': False,
            'filepath': p_str,
            'filename': p.name,
            'error': str(e)
        }

def _process_image_worker(args):
    """
    並列処理用の画像読み込み＆パディングワーカー:
    画像を読み込み、指定サイズのキャンバスに配置してnp.ndarrayを返します。
    """
    img_path_str, max_w, max_h, has_alpha = args
    img_path = Path(img_path_str)
    
    try:
        with Image.open(img_path) as img:
            orig_w, orig_h = img.size
            
            if has_alpha:
                img_conv = img.convert('RGBA')
                bg_color = (0, 0, 0, 0)
            else:
                img_conv = img.convert('RGB')
                bg_color = (0, 0, 0)
                
            mode = 'RGBA' if has_alpha else 'RGB'
            canvas = Image.new(mode, (max_w, max_h), bg_color)
            canvas.paste(img_conv, (0, 0))
            
            arr = np.array(canvas, dtype=np.uint8)
            return {
                'success': True,
                'filename': img_path.name,
                'orig_w': orig_w,
                'orig_h': orig_h,
                'array': arr,
                'filepath': img_path_str
            }
    except Exception as e:
        return {
            'success': False,
            'filename': img_path.name,
            'error': str(e),
            'filepath': img_path_str
        }

def _save_batch_worker(args):
    """
    並列保存用のワーカー関数:
    指定された画像配列リストを np.savez または np.savez_compressed でファイルへ保存します。
    """
    batch_arrays, npz_path_str, is_compressed = args
    dataset_np_array = np.stack(batch_arrays, axis=0)
    npz_path = Path(npz_path_str)
    
    if is_compressed:
        np.savez_compressed(npz_path, images=dataset_np_array)
    else:
        np.savez(npz_path, images=dataset_np_array)
        
    return str(npz_path)

def process_dataset_folder(folder_path, min_images=20, num_workers=4, num_tasks=4, progress_callback=None):
    """
    単一のデータセットフォルダを処理します。
    1. 並列画像探索（サイズ、アルファ、非圧縮性の取得）
    2. 画像を num_tasks (指定タスク数) の分割バッチに割り当て
    3. 並列処理でバッチごとに画像パディング＆npz保存 (マルチコアZip圧縮 or パック保存)
    4. images_index.csv の保存
    5. 元画像ファイルの削除
    """
    folder_path = Path(folder_path)
    image_paths = [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    
    if len(image_paths) < min_images:
        return {'status': 'skipped', 'message': f'画像枚数が{min_images}枚未満のためスキップ ({len(image_paths)}枚)'}
    
    image_paths.sort(key=lambda p: p.name)
    total_images = len(image_paths)
    num_workers = max(1, min(num_workers, os.cpu_count() or 4))
    num_tasks = max(1, num_tasks)

    if progress_callback:
        progress_callback(f"データセット処理開始: {folder_path.name} (計{total_images}枚, タスク分割数: {num_tasks}, CPUコア数: {num_workers})")

    # --- Phase 1: 並列画像探索 ---
    if progress_callback:
        progress_callback(f"[1/4 探索] 画像サイズおよびフォーマット並列検証中...")

    insp_tasks = [str(p) for p in image_paths]
    insp_results = []
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_inspect_image_worker, p_str) for p_str in insp_tasks]
        completed = 0
        for future in as_completed(futures):
            res = future.result()
            insp_results.append(res)
            completed += 1
            if progress_callback and (completed % 1000 == 0 or completed == total_images):
                pct = (completed / total_images) * 100
                progress_callback(f"  - 探査進捗: {completed}/{total_images}枚 ({pct:.1f}%)")

    successful_insp = [r for r in insp_results if r['success']]
    if not successful_insp:
        return {'status': 'error', 'message': '有効な画像サイズが取得できませんでした'}

    successful_insp.sort(key=lambda x: x['filename'])

    max_w = max(r['width'] for r in successful_insp)
    max_h = max(r['height'] for r in successful_insp)
    has_alpha = any(r['has_alpha'] for r in successful_insp)
    has_uncompressed = any(r['is_uncompressed'] for r in successful_insp)

    mode_label = f"非圧縮画像検出 ({num_workers}コア並列Zip圧縮)" if has_uncompressed else "圧縮済み画像のみ (爆速パック保存)"
    if progress_callback:
        progress_callback(f"  -> 最大解ゾード: {max_w}x{max_h}, 方式: {mode_label}")

    # --- Phase 2: タスク分割 & バッチ並列パディング ＆ 保存 ---
    num_batches = min(num_tasks, len(successful_insp))
    chunk_size = (len(successful_insp) + num_batches - 1) // num_batches

    created_npz_files = []
    index_records = []
    total_processed = 0

    if progress_callback:
        progress_callback(f"[2/4 パディング&保存] 全{num_batches}タスクの並列実行開始...")

    for batch_idx in range(num_batches):
        batch_items = successful_insp[batch_idx * chunk_size : (batch_idx + 1) * chunk_size]
        if not batch_items:
            continue

        npz_name = "dataset.npz" if num_batches == 1 else f"dataset_part{batch_idx + 1:02d}.npz"
        npz_path = folder_path / npz_name
        created_npz_files.append(str(npz_path))

        # バッチ内の画像読み込み＆パディング
        pad_tasks = [(item['filepath'], max_w, max_h, has_alpha) for item in batch_items]
        batch_pad_results = []

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_process_image_worker, task) for task in pad_tasks]
            for future in as_completed(futures):
                res = future.result()
                batch_pad_results.append(res)

        batch_pad_results.sort(key=lambda x: x['filename'])
        valid_pad_results = [r for r in batch_pad_results if r['success']]

        if valid_pad_results:
            batch_arrays = [r['array'] for r in valid_pad_results]
            dataset_np_array = np.stack(batch_arrays, axis=0)

            if has_uncompressed:
                np.savez_compressed(npz_path, images=dataset_np_array)
            else:
                np.savez(npz_path, images=dataset_np_array)

            for idx_in_batch, r in enumerate(valid_pad_results):
                index_records.append({
                    'index': idx_in_batch,
                    'filename': r['filename'],
                    'orig_w': r['orig_w'],
                    'orig_h': r['orig_h'],
                    'npz_file': npz_name
                })

        total_processed += len(valid_pad_results)
        if progress_callback:
            pct = (total_processed / len(successful_insp)) * 100
            progress_callback(f"  - タスク {batch_idx + 1}/{num_batches} 完了 -> {npz_name} (累計 {total_processed}/{len(successful_insp)}枚, {pct:.1f}%)")

    # --- Phase 3: インデックスCSVの作成 ---
    if progress_callback:
        progress_callback(f"[3/4 インデックス生成] images_index.csv 書き出し中...")

    csv_path = folder_path / "images_index.csv"
    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['index', 'filename', 'original_width', 'original_height', 'npz_file'])
        for rec in index_records:
            writer.writerow([rec['index'], rec['filename'], rec['orig_w'], rec['orig_h'], rec['npz_file']])

    # --- Phase 4: 元画像の削除 ---
    if progress_callback:
        progress_callback(f"[4/4 クリーンアップ] 元画像ファイルの削除開始...")

    deleted_count = 0
    for idx, r in enumerate(successful_insp, 1):
        try:
            os.remove(r['filepath'])
            deleted_count += 1
        except Exception as e:
            if progress_callback:
                progress_callback(f"警告: ファイル削除失敗 {r['filename']}: {e}")
        if progress_callback and (idx % 2000 == 0 or idx == len(successful_insp)):
            pct = (idx / len(successful_insp)) * 100
            progress_callback(f"  - 削除進捗: {idx}/{len(successful_insp)}枚 ({pct:.1f}%)")

    if progress_callback:
        progress_callback(f"完了: {folder_path.name} -> 成功 ({deleted_count}枚の元画像を削除)")

    return {
        'status': 'success',
        'processed_count': deleted_count,
        'npz_files': created_npz_files,
        'csv_path': str(csv_path),
        'mode': 'compressed' if has_uncompressed else 'packed'
    }


