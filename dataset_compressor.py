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
        # 直下の画像ファイルをカウント
        image_files = [f for f in filenames if Path(f).suffix.lower() in IMAGE_EXTENSIONS]
        if len(image_files) >= min_images:
            dataset_folders.append(Path(dirpath))
            
    return dataset_folders

def _process_image_worker(args):
    """
    並列処理用のワーカー関数: 画像を読み込み、指定サイズのキャンバスに配置してnp.ndarrayを返します。
    """
    img_path_str, max_w, max_h, has_alpha = args
    img_path = Path(img_path_str)
    
    try:
        with Image.open(img_path) as img:
            orig_w, orig_h = img.size
            
            # モードの統一
            if has_alpha:
                img_conv = img.convert('RGBA')
                bg_color = (0, 0, 0, 0)
            else:
                img_conv = img.convert('RGB')
                bg_color = (0, 0, 0)
                
            # 黒（または透明）キャンバスの作成
            mode = 'RGBA' if has_alpha else 'RGB'
            canvas = Image.new(mode, (max_w, max_h), bg_color)
            canvas.paste(img_conv, (0, 0)) # 左上に配置 (右・下を黒補完)
            
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

def process_dataset_folder(folder_path, min_images=20, num_workers=4, progress_callback=None):
    """
    単一のデータセットフォルダを処理します。
    1. 画像一覧の取得および非圧縮画像の有無判定
    2. 画像サイズの取得と最大幅・最大の高さの確定
    3. 並列処理で画像読み込み・黒補完
    4. 非圧縮画像がある場合はコア数でタスク分割してマルチコアZip圧縮
       圧縮済み画像のみの場合は無圧縮パック保存
    5. images_index.csv の保存
    6. 元画像ファイルの削除
    """
    folder_path = Path(folder_path)
    image_paths = [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    
    if len(image_paths) < min_images:
        return {'status': 'skipped', 'message': f'画像枚数が{min_images}枚未満のためスキップ ({len(image_paths)}枚)'}
    
    # 昇順で並び替え
    image_paths.sort(key=lambda p: p.name)
    
    # 非圧縮画像の有無判定
    has_uncompressed = any(p.suffix.lower() in UNCOMPRESSED_EXTENSIONS for p in image_paths)
    
    # 全画像の元サイズとアルファチャネルの有無を確認
    meta_info = []
    max_w = 0
    max_h = 0
    has_alpha = False
    
    for p in image_paths:
        try:
            with Image.open(p) as img:
                w, h = img.size
                max_w = max(max_w, w)
                max_h = max(max_h, h)
                if img.mode in ('RGBA', 'LA', 'PA') or 'transparency' in img.info:
                    has_alpha = True
                meta_info.append((str(p), w, h))
        except Exception as e:
            if progress_callback:
                progress_callback(f"警告: 画像読み込みエラー {p.name}: {e}")

    if not meta_info:
        return {'status': 'error', 'message': '有効な画像が見つかりませんでした'}

    total_images = len(meta_info)
    num_workers = max(1, min(num_workers, os.cpu_count() or 4))
    
    if progress_callback:
        mode_str = f"非圧縮画像あり ({num_workers}コア並列Zip圧縮)" if has_uncompressed else "圧縮済み画像のみ (爆速パック保存)"
        progress_callback(f"データセット処理開始: {folder_path.name} (計{total_images}枚, 最大サイズ: {max_w}x{max_h}, モード: {mode_str})")

    # 並列処理のタスク引数を準備
    tasks = [(p_str, max_w, max_h, has_alpha) for (p_str, _, _) in meta_info]
    
    results = []
    
    # ProcessPoolExecutor で並列処理（画像読み込み・パディング）
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_process_image_worker, task) for task in tasks]
        
        completed_count = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1
            if progress_callback and completed_count % 10 == 0:
                progress_callback(f"  - 画像読み込み・パディング中... {completed_count}/{total_images}")

    # 結果をファイル名で元順序にソート
    results.sort(key=lambda x: x['filename'])

    successful_results = [r for r in results if r['success']]
    if not successful_results:
        return {'status': 'error', 'message': 'すべての画像の処理に失敗しました'}

    # バッチ分割数（非圧縮画像ありの場合はコア数、無圧縮パックの場合もコア数または1バッチ）
    num_batches = num_workers if (has_uncompressed and len(successful_results) >= num_workers) else 1
    chunk_size = (len(successful_results) + num_batches - 1) // num_batches
    
    save_tasks = []
    index_records = []
    created_npz_files = []

    for batch_idx in range(num_batches):
        batch_items = successful_results[batch_idx * chunk_size : (batch_idx + 1) * chunk_size]
        if not batch_items:
            continue
        
        npz_name = "dataset.npz" if num_batches == 1 else f"dataset_part{batch_idx + 1:02d}.npz"
        npz_path = folder_path / npz_name
        created_npz_files.append(str(npz_path))
        
        batch_arrays = [r['array'] for r in batch_items]
        save_tasks.append((batch_arrays, str(npz_path), has_uncompressed))
        
        for idx_in_batch, r in enumerate(batch_items):
            index_records.append({
                'index': idx_in_batch,
                'filename': r['filename'],
                'orig_w': r['orig_w'],
                'orig_h': r['orig_h'],
                'npz_file': npz_name
            })

    if progress_callback:
        action_name = "並列Zip圧縮保存中" if has_uncompressed else "パック保存中"
        progress_callback(f"  - {action_name}... ({num_batches}ファイルに出力)")

    # 保存処理の実行（マルチコア並列圧縮 or 単一/並列パック）
    with ProcessPoolExecutor(max_workers=min(len(save_tasks), num_workers)) as executor:
        save_futures = [executor.submit(_save_batch_worker, task) for task in save_tasks]
        for future in as_completed(save_futures):
            future.result()

    # images_index.csv の作成
    csv_path = folder_path / "images_index.csv"
    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['index', 'filename', 'original_width', 'original_height', 'npz_file'])
        for rec in index_records:
            writer.writerow([rec['index'], rec['filename'], rec['orig_w'], rec['orig_h'], rec['npz_file']])

    # 元画像の削除
    deleted_count = 0
    for r in successful_results:
        try:
            os.remove(r['filepath'])
            deleted_count += 1
        except Exception as e:
            if progress_callback:
                progress_callback(f"警告: ファイル削除失敗 {r['filename']}: {e}")

    mode_label = "マルチコアZip圧縮" if has_uncompressed else "パック保存"
    if progress_callback:
        progress_callback(f"完了: {folder_path.name} -> {mode_label}完了 ({deleted_count}枚の元画像を削除)")

    return {
        'status': 'success',
        'processed_count': len(successful_results),
        'npz_files': created_npz_files,
        'csv_path': str(csv_path),
        'mode': 'compressed' if has_uncompressed else 'packed'
    }

