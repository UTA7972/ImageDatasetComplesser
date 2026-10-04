import os
import csv
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

def scan_compressed_datasets(root_dir):
    """
    指定されたルートディレクトリ以下を再帰的にスキャンし、
    images_index.csv および .npz ファイルが存在するフォルダのリストを返します。
    """
    compressed_folders = []
    root_path = Path(root_dir)
    
    if not root_path.exists():
        return compressed_folders

    for dirpath, _, filenames in os.walk(root_path):
        folder = Path(dirpath)
        has_csv = (folder / "images_index.csv").exists()
        npz_files = [f for f in filenames if f.endswith(".npz")]
        if has_csv and npz_files:
            compressed_folders.append(folder)
            
    return compressed_folders

def get_compressed_folder_info(folder_path):
    """
    圧縮データセットフォルダの詳細情報 (タスク数/npzファイル数, 総画像枚数) を取得します。
    """
    folder_path = Path(folder_path)
    csv_path = folder_path / "images_index.csv"
    npz_files = list(folder_path.glob("*.npz"))
    
    task_count = len(npz_files)
    total_images = 0
    
    if csv_path.exists():
        try:
            with open(csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                total_images = sum(1 for _ in reader)
        except Exception:
            pass
            
    return {
        'folder_path': str(folder_path),
        'folder_name': folder_path.name,
        'task_count': task_count,
        'total_images': total_images,
        'npz_files': [f.name for f in npz_files]
    }

def _decompress_image_worker(args):
    """
    並列処理用のワーカー関数:
    NumPy配列から元の画像サイズ(orig_w, orig_h)にクロップし、画像ファイルとして保存します。
    """
    img_array, orig_w, orig_h, output_path_str = args
    output_path = Path(output_path_str)
    
    try:
        cropped_array = img_array[:orig_h, :orig_w]
        
        if cropped_array.ndim == 3 and cropped_array.shape[2] == 4:
            mode = 'RGBA'
        elif cropped_array.ndim == 3 and cropped_array.shape[2] == 3:
            mode = 'RGB'
        elif cropped_array.ndim == 2 or (cropped_array.ndim == 3 and cropped_array.shape[2] == 1):
            mode = 'L'
            if cropped_array.ndim == 3:
                cropped_array = cropped_array.squeeze(axis=2)
        else:
            mode = 'RGB'

        img = Image.fromarray(cropped_array, mode=mode)
        img.save(output_path)
        
        return {
            'success': True,
            'filename': output_path.name,
            'filepath': output_path_str
        }
    except Exception as e:
        return {
            'success': False,
            'filename': output_path.name,
            'error': str(e),
            'filepath': output_path_str
        }

def process_decompress_folder(folder_path, num_workers=4, progress_callback=None):
    """
    単一の圧縮/パックデータセットフォルダを解凍・復元します。
    1. images_index.csv の読み込みおよび該当 .npz ファイルの探索
    2. 元サイズへのクロップと画像保存を並列実行
    3. images_index.csv および関連 .npz ファイルの削除
    """
    folder_path = Path(folder_path)
    csv_path = folder_path / "images_index.csv"

    if not csv_path.exists():
        return {'status': 'error', 'message': 'images_index.csv が存在しません'}

    # CSV の読み込み
    index_records = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                npz_file_name = row.get('npz_file') or "dataset.npz"
                index_records.append({
                    'index': int(row['index']),
                    'filename': row['filename'],
                    'orig_w': int(row['original_width']),
                    'orig_h': int(row['original_height']),
                    'npz_file': npz_file_name
                })
    except Exception as e:
        return {'status': 'error', 'message': f'images_index.csv の読み込みに失敗しました: {e}'}

    if not index_records:
        return {'status': 'error', 'message': 'images_index.csv 内にレコードが存在しません'}

    npz_cache = {}
    npz_files_needed = set(r['npz_file'] for r in index_records)

    for npz_name in npz_files_needed:
        npz_file_path = folder_path / npz_name
        if not npz_file_path.exists():
            return {'status': 'error', 'message': f'必要なアーカイブファイルが存在しません: {npz_name}'}
        try:
            with np.load(npz_file_path) as data:
                if 'images' not in data:
                    return {'status': 'error', 'message': f'{npz_name} 内に images キーが存在しません'}
                npz_cache[npz_name] = np.array(data['images'])
        except Exception as e:
            return {'status': 'error', 'message': f'{npz_name} の読み込みに失敗しました: {e}'}

    total_images = len(index_records)
    num_workers = max(1, min(num_workers, os.cpu_count() or 4))

    if progress_callback:
        progress_callback(f"解凍・展開処理開始: {folder_path.name} (計{total_images}枚, 検出アーカイブ数: {len(npz_files_needed)}個, 使用CPUコア数: {num_workers})")

    tasks = []
    for rec in index_records:
        npz_name = rec['npz_file']
        idx = rec['index']
        img_arr = npz_cache[npz_name][idx]
        orig_w = rec['orig_w']
        orig_h = rec['orig_h']
        out_path = folder_path / rec['filename']
        tasks.append((img_arr, orig_w, orig_h, str(out_path)))

    results = []

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_decompress_image_worker, task) for task in tasks]
        
        completed_count = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1
            if progress_callback and (completed_count % 1000 == 0 or completed_count == total_images):
                pct = (completed_count / total_images) * 100
                progress_callback(f"  - 解凍展開進捗: {completed_count}/{total_images}枚 ({pct:.1f}%)")

    successful_results = [r for r in results if r['success']]
    if len(successful_results) < total_images:
        failed_count = total_images - len(successful_results)
        return {'status': 'error', 'message': f'{failed_count}枚の解凍に失敗したため、アーカイブの削除をスキップします'}

    del npz_cache

    try:
        for npz_name in npz_files_needed:
            p = folder_path / npz_name
            if p.exists():
                os.remove(p)
        os.remove(csv_path)
        if progress_callback:
            progress_callback(f"完了: アーカイブファイル ({len(npz_files_needed)}個) および images_index.csv を削除しました ({folder_path.name})")
    except Exception as e:
        if progress_callback:
            progress_callback(f"警告: アーカイブファイルの削除中にエラーが発生しました: {e}")

    return {
        'status': 'success',
        'decompressed_count': len(successful_results)
    }


