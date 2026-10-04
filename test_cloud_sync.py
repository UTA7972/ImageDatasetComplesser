import os
import shutil
from pathlib import Path
from cloud_sync import (
    scan_and_build_index,
    save_index_csv,
    load_index_csv,
    build_cloud_index,
    compare_cloud_files,
    copy_cloud_files,
    process_cloud_sync,
    is_same_content,
    INDEX_FILENAME
)

def create_test_dir_structure(root_dir):
    root = Path(root_dir)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    # サブフォルダとファイルの作成
    sub1 = root / "folder_a"
    sub2 = root / "folder_b" / "nested_c"
    sub1.mkdir(parents=True, exist_ok=True)
    sub2.mkdir(parents=True, exist_ok=True)

    (root / "root_file.txt").write_text("Hello Root File", encoding="utf-8")
    (sub1 / "file_a1.txt").write_text("Content A1", encoding="utf-8")
    (sub1 / "file_a2.txt").write_text("Content A2", encoding="utf-8")
    (sub2 / "file_c1.txt").write_text("Content C1 in nested", encoding="utf-8")

def main():
    test_src = Path("testdata_cloud_src")
    test_dest = Path("testdata_cloud_dest")

    try:
        print("=== 1. テストデータの生成 ===")
        create_test_dir_structure(test_src)
        if test_dest.exists():
            shutil.rmtree(test_dest)

        print("\n=== 2. 段階1: インデックス生成テスト ===")
        res_idx = build_cloud_index(test_src)
        entries = res_idx["entries"]
        csv_path = Path(res_idx["index_file"])
        print(f"スキャン結果 ({len(entries)} 項目):")
        for e in entries:
            print(f"  [{e['整理番号']}] {e['タイプ']}: {e['相対パス']} (状態: {e['処理状態']}, 比較: {e['ファイル比較']})")

        assert len(entries) == 7, f"期待される項目数は 7 ですが {len(entries)} 件でした"
        loaded = load_index_csv(csv_path)
        assert len(loaded) == 7, "CSVロード結果の件数が不一致です"
        assert loaded[0]["処理状態"] == "0", "初期処理状態が0ではありません"
        assert loaded[0]["ファイル比較"] == "1", "初期ファイル比較が1ではありません"

        print("\n=== 3. 段階2: ファイル比較テスト (転送前) ===")
        res_cmp = compare_cloud_files(test_src, test_dest, index_csv_path=csv_path, use_hash=False)
        print("ファイル比較結果:", res_cmp)
        assert res_cmp["diff"] == 7, f"転送前の差分項目数は 7 であるべきですが {res_cmp['diff']} でした"
        
        loaded_after_cmp = load_index_csv(csv_path)
        for e in loaded_after_cmp:
            assert e["ファイル比較"] == "1", f"転送前は全件ファイル比較が1である必要があります: {e['相対パス']}"

        print("\n=== 4. 段階3: ファイルコピーテスト ===")
        res_copy = copy_cloud_files(test_src, test_dest, index_csv_path=csv_path, num_workers=4)
        print("ファイルコピー結果:", res_copy)
        assert res_copy["copied"] == 7, f"コピー実行数は 7 であるべきですが {res_copy['copied']} でした"
        assert (test_dest / "root_file.txt").exists(), "コピー先に root_file.txt がありません"
        assert (test_dest / "folder_b" / "nested_c" / "file_c1.txt").exists(), "ネストファイルが存在しません"

        updated_index = load_index_csv(csv_path)
        for e in updated_index:
            assert e["処理状態"] == "1", f"処理状態が1になっていません: {e['相対パス']}"

        print("\n=== 5. 再比較テスト (転送後・同一内容) ===")
        res_cmp2 = compare_cloud_files(test_src, test_dest, index_csv_path=csv_path, use_hash=False)
        print("転送後の比較結果:", res_cmp2)
        assert res_cmp2["same"] == 7, f"転送後は全7件一致するはずですが {res_cmp2['same']} でした"

        loaded_after_cmp2 = load_index_csv(csv_path)
        for e in loaded_after_cmp2:
            assert e["ファイル比較"] == "0", f"一致した項目はファイル比較が0になる必要があります: {e['相対パス']}"

        print("\n=== 6. 内容変更と再比較・再転送テスト ===")
        dest_file_to_mod = test_dest / "root_file.txt"
        dest_file_to_mod.write_text("MODIFIED CONTENT FOR TEST", encoding="utf-8")
        
        # 処理状態を 0 にリセットして比較実行
        for e in loaded_after_cmp2:
            e["処理状態"] = "0"
        save_index_csv(csv_path, loaded_after_cmp2)

        res_cmp3 = compare_cloud_files(test_src, test_dest, index_csv_path=csv_path, use_hash=False)
        print("一部変更後の比較結果:", res_cmp3)
        assert res_cmp3["diff"] == 1, f"変更されたファイル1件のみ差分検知されるべきですが {res_cmp3['diff']} でした"

        res_copy2 = copy_cloud_files(test_src, test_dest, index_csv_path=csv_path)
        print("差分ファイルのみ転送結果:", res_copy2)
        assert res_copy2["copied"] == 1, f"コピーされたのは1件であるべきですが {res_copy2['copied']} でした"
        assert dest_file_to_mod.read_text(encoding="utf-8") == "Hello Root File", "ファイルが正しく更新されていません"

        print("\n すべてのクラウド転送ユニットテスト（段階別・比較ステータス機能含む）に成功しました！")

    finally:
        if test_src.exists():
            shutil.rmtree(test_src)
        if test_dest.exists():
            shutil.rmtree(test_dest)

if __name__ == "__main__":
    main()

