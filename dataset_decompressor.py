import os
import csv
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

def scan_compressed_datasets(root_dir):
    """
    指定されたルートディレクトリ以下を再帰的にスキャンし、
    dataset.npz と images_index.csv が存在するフォルダのリストを返します。
    """
    compressed_folders = []
    root_path = Path(root_dir)
    
    if not root_path.exists():
        return compressed_folders

    for dirpath, _, filenames in os.walk(root_path):
        folder = Path(dirpath)
        if (folder / "dataset.npz").exists() and (folder / "images_index.csv").exists():
            compressed_folders.append(folder)
            
    return compressed_folders

def _decompress_image_worker(args):
    """
    並列処理用のワーカー関数:
    NumPy配列から元の画像サイズ(orig_w, orig_h)にクロップし、画像ファイルとして保存します。
    """
    img_array, orig_w, orig_h, output_path_str = args
    output_path = Path(output_path_str)
    
    try:
        # 左上 (0:orig_h, 0:orig_w) をクロップして黒補完領域を除去
        cropped_array = img_array[:orig_h, :orig_w]
        
        # 配列の形状とチャネル判定
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
    単一の圧縮データセットフォルダを解凍・復元します。
    1. images_index.csv と dataset.npz の読み込み
    2. 元サイズへのクロップと画像保存を並列実行
    3. images_index.csv と dataset.npz の削除
    """
    folder_path = Path(folder_path)
    npz_path = folder_path / "dataset.npz"
    csv_path = folder_path / "images_index.csv"

    if not npz_path.exists() or not csv_path.exists():
        return {'status': 'error', 'message': 'dataset.npz または images_index.csv が存在しません'}

    # CSV の読み込み
    index_records = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                index_records.append({
                    'index': int(row['index']),
                    'filename': row['filename'],
                    'orig_w': int(row['original_width']),
                    'orig_h': int(row['original_height'])
                })
    except Exception as e:
        return {'status': 'error', 'message': f'images_index.csv の読み込みに失敗しました: {e}'}

    if not index_records:
        return {'status': 'error', 'message': 'images_index.csv 内にレコードが存在しません'}

    # npz の読み込み
    try:
        with np.load(npz_path) as data:
            if 'images' not in data:
                return {'status': 'error', 'message': 'npz 内に images キーが存在しません'}
            images_array = data['images'] # shape: (N, max_h, max_w, C)
    except Exception as e:
        return {'status': 'error', 'message': f'dataset.npz の読み込みに失敗しました: {e}'}

    if len(index_records) > len(images_array):
        return {'status': 'error', 'message': 'csv のレコード数と npz 内の画像数が一致しません'}

    total_images = len(index_records)
    if progress_callback:
        progress_callback(f"解凍処理開始: {folder_path.name} (計{total_images}枚)")

    # タスクの作成
    tasks = []
    for rec in index_records:
        idx = rec['index']
        img_arr = images_array[idx]
        orig_w = rec['orig_w']
        orig_h = rec['orig_h']
        out_path = folder_path / rec['filename']
        tasks.append((img_arr, orig_w, orig_h, str(out_path)))

    num_workers = max(1, min(num_workers, os.cpu_count() or 4))
    results = []

    # ProcessPoolExecutor で並列復元
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_decompress_image_worker, task) for task in tasks]
        
        completed_count = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1
            if progress_callback and completed_count % 10 == 0:
                progress_callback(f"  - 解凍復元中... {completed_count}/{total_images}")

    successful_results = [r for r in results if r['success']]
    if len(successful_results) < total_images:
        failed_count = total_images - len(successful_results)
        return {'status': 'error', 'message': f'{failed_count}枚の解凍に失敗したため、アーカイブの削除をスキップします'}

    # 解凍成功後に dataset.npz と images_index.csv を削除
    try:
        os.remove(npz_path)
        os.remove(csv_path)
        if progress_callback:
            progress_callback(f"完了: dataset.npz および images_index.csv を削除しました ({folder_path.name})")
    except Exception as e:
        if progress_callback:
            progress_callback(f"警告: 圧縮ファイルの削除中にエラーが発生しました: {e}")

    return {
        'status': 'success',
        'decompressed_count': len(successful_results)
    }
