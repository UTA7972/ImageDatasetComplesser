import os
import shutil
import numpy as np
from PIL import Image
from pathlib import Path
from dataset_compressor import scan_datasets, process_dataset_folder

def create_dummy_dataset(target_dir, count=25):
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 異なるサイズの画像を作成
    sizes = [(100, 100), (120, 80), (90, 150), (200, 200)]
    for i in range(count):
        w, h = sizes[i % len(sizes)]
        # ランダムな色付き画像
        img_arr = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        img = Image.fromarray(img_arr)
        img.save(target_dir / f"img_{i:03d}.png")

def main():
    test_root = Path("testdata")
    if test_root.exists():
        shutil.rmtree(test_root)
        
    ds1 = test_root / "dataset_A"
    ds2 = test_root / "dataset_B" / "sub_dataset_C"
    ignored = test_root / "ignored_small"
    
    print("--- テストデータ作成中 ---")
    create_dummy_dataset(ds1, 22)
    create_dummy_dataset(ds2, 25)
    create_dummy_dataset(ignored, 10) # 10枚はスキップ対象
    
    print("\n--- スキャンテスト ---")
    folders = scan_datasets(test_root, min_images=20)
    print(f"検出されたデータセットフォルダ ({len(folders)}件):")
    for f in folders:
        print(f" - {f}")

    assert len(folders) == 2, f"期待されるデータセット数は2ですが、{len(folders)}件検出されました"

    print("\n--- 圧縮・変換テスト ---")
    for f in folders:
        res = process_dataset_folder(f, min_images=20, num_workers=2, progress_callback=print)
        print("結果:", res)
        
        # 検証
        npz_file = f / "dataset.npz"
        csv_file = f / "images_index.csv"
        assert npz_file.exists(), "dataset.npz が作成されていません"
        assert csv_file.exists(), "images_index.csv が作成されていません"
        
        # 元画像が削除されているか検証
        png_files = list(f.glob("*.png"))
        assert len(png_files) == 0, f"元画像が削除されていません: {len(png_files)}件残存"
        
        # npzデータの検証
        with np.load(npz_file) as data:
            imgs = data['images']
            print(f"  -> npz内の画像配列形状: {imgs.shape}")
        
    print("\nすべてのテストが成功しました！")

    # 後片付け
    if test_root.exists():
        shutil.rmtree(test_root)

if __name__ == "__main__":
    main()
