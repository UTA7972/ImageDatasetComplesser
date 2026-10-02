import os
import shutil
from pathlib import Path
import numpy as np
from PIL import Image

from dataset_compressor import process_dataset_folder
from dataset_decompressor import scan_compressed_datasets, process_decompress_folder

def create_test_images(target_dir):
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    image_specs = [
        ("img_01.png", (120, 90)),
        ("img_02.png", (200, 150)),
        ("img_03.png", (80, 240)),
        ("img_04.png", (160, 160)),
    ]
    
    # 24枚作成（20枚以上）
    original_sizes = {}
    for i in range(24):
        fname, (w, h) = image_specs[i % len(image_specs)]
        file_name = f"test_{i:02d}_{fname}"
        img_arr = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        img = Image.fromarray(img_arr)
        file_path = target_dir / file_name
        img.save(file_path)
        original_sizes[file_name] = (w, h)
        
    return original_sizes

def main():
    test_root = Path("testdata_decompress")
    if test_root.exists():
        shutil.rmtree(test_root)
        
    print("--- 1. テスト画像生成 ---")
    orig_sizes = create_test_images(test_root)
    print(f"元画像 {len(orig_sizes)} 枚生成完了")

    print("\n--- 2. 圧縮テスト ---")
    comp_res = process_dataset_folder(test_root, min_images=20, num_workers=2, progress_callback=print)
    assert comp_res['status'] == 'success', f"圧縮失敗: {comp_res}"
    assert (test_root / "dataset.npz").exists()
    assert (test_root / "images_index.csv").exists()
    assert len(list(test_root.glob("*.png"))) == 0, "元画像が削除されていません"

    print("\n--- 3. 圧縮データセットスキャンテスト ---")
    compressed_folders = scan_compressed_datasets(test_root)
    print("検出フォルダ:", compressed_folders)
    assert len(compressed_folders) == 1

    print("\n--- 4. 解凍テスト ---")
    decomp_res = process_decompress_folder(test_root, num_workers=2, progress_callback=print)
    assert decomp_res['status'] == 'success', f"解凍失敗: {decomp_res}"

    print("\n--- 5. 復元検証 ---")
    # npz と csv が削除されているか
    assert not (test_root / "dataset.npz").exists(), "dataset.npz が削除されていません"
    assert not (test_root / "images_index.csv").exists(), "images_index.csv が削除されていません"

    # 復元された画像の検証
    restored_images = list(test_root.glob("*.png"))
    assert len(restored_images) == len(orig_sizes), f"復元画像数が一致しません ({len(restored_images)} vs {len(orig_sizes)})"

    for img_path in restored_images:
        with Image.open(img_path) as img:
            w, h = img.size
            expected_w, expected_h = orig_sizes[img_path.name]
            assert (w, h) == (expected_w, expected_h), f"{img_path.name} の解像度が一致しません: 復元 ({w}x{h}) vs 元 ({expected_w}x{expected_h})"
            print(f"  [OK] {img_path.name}: 正確に解像度 ({w}x{h}) へ復元されました")

    print("\n--- すべての解凍・復元テストに成功しました！ ---")

    # クリーニング
    if test_root.exists():
        shutil.rmtree(test_root)

if __name__ == "__main__":
    main()
