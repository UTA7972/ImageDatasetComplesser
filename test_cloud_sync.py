import os
import shutil
from pathlib import Path
from cloud_sync import (
    scan_and_build_index,
    save_index_csv,
    load_index_csv,
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

        print("\n=== 2. インデックス生成テスト ===")
        entries = scan_and_build_index(test_src)
        print(f"スキャン結果 ({len(entries)} 項目):")
        for e in entries:
            print(f"  [{e['整理番号']}] {e['タイプ']}: {e['相対パス']} (状態: {e['処理状態']})")

        # 構造チェック: フォルダ3個 + ファイル4個 = 7項目
        assert len(entries) == 7, f"期待される項目数は 7 ですが {len(entries)} 件でした"
        
        # CSVの書き出し＆読み込み検証
        csv_path = test_src / INDEX_FILENAME
        save_index_csv(csv_path, entries)
        loaded = load_index_csv(csv_path)
        assert len(loaded) == 7, "CSVロード結果の件数が不一致です"
        assert loaded[0]["処理状態"] == "0", "初期状態が0ではありません"

        print("\n=== 3. 初回転送 (全コピー) テスト ===")
        res1 = process_cloud_sync(test_src, test_dest)
        print("初回転送結果:", res1)
        assert res1["completed"] == 7, f"完了件数が不一致です: {res1['completed']}"
        assert (test_dest / "root_file.txt").exists(), "コピー先に root_file.txt がありません"
        assert (test_dest / "folder_b" / "nested_c" / "file_c1.txt").exists(), "ネストファイルが存在しません"

        # CSV内の処理状態が1になっているか確認
        updated_index = load_index_csv(csv_path)
        for e in updated_index:
            assert e["処理状態"] == "1", f"処理状態が1になっていません: {e['相対パス']}"

        print("\n=== 4. スキップ (同一内容) テスト ===")
        res2 = process_cloud_sync(test_src, test_dest, index_csv_path=csv_path)
        print("2回目転送結果:", res2)
        # すべて処理済み(1)のため、残りは0
        assert res2["copied"] == 0, f"再転送でコピーが発生しました: {res2['copied']}"

        print("\n=== 5. 途中再開テスト ===")
        # 一部の項目の処理状態を 0 に戻し、転送先ファイルを1つ削除して擬似的に中断状態を作成
        updated_index[3]["処理状態"] = "0"  # file_a2.txt
        updated_index[6]["処理状態"] = "0"  # file_c1.txt
        save_index_csv(csv_path, updated_index)

        dest_file_to_del = test_dest / updated_index[6]["相対パス"]
        if dest_file_to_del.exists():
            dest_file_to_del.unlink()

        res3 = process_cloud_sync(test_src, test_dest, index_csv_path=csv_path)
        print("途中再開転送結果:", res3)
        assert dest_file_to_del.exists(), "削除されたファイルが復元されませんでした"
        final_index = load_index_csv(csv_path)
        for e in final_index:
            assert e["処理状態"] == "1", "再開後の処理状態が1になりませんでした"

        print("\n=== 6. 内容変更の上書きテスト ===")
        # コピー先のファイルを書き換えてサイズ/内容を異なるものにする
        dest_file_to_mod = test_dest / "root_file.txt"
        dest_file_to_mod.write_text("MODIFIED CONTENT", encoding="utf-8")
        assert not is_same_content(test_src / "root_file.txt", dest_file_to_mod), "内容差異が検知されませんでした"

        # インデックスの状態を0にして再転送
        final_index[0]["処理状態"] = "0"
        save_index_csv(csv_path, final_index)
        res4 = process_cloud_sync(test_src, test_dest, index_csv_path=csv_path)
        print("上書き転送結果:", res4)
        assert dest_file_to_mod.read_text(encoding="utf-8") == "Hello Root File", "ファイルが正しく上書きされていません"

        print("\n すべてのクラウド転送ユニットテストに成功しました！")

    finally:
        # 後片付け
        if test_src.exists():
            shutil.rmtree(test_src)
        if test_dest.exists():
            shutil.rmtree(test_dest)

if __name__ == "__main__":
    main()
