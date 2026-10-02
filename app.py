import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from dataset_compressor import scan_datasets, process_dataset_folder
from dataset_decompressor import scan_compressed_datasets, process_decompress_folder

class DatasetCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Dataset Compressor & Decompressor")
        self.root.geometry("820x680")
        self.root.minsize(720, 580)

        # システム情報
        self.max_cpus = os.cpu_count() or 4
        self.is_running = False
        self.log_queue = queue.Queue()

        # テーマとスタイルの初期化
        self.setup_styles()
        
        # UI構築
        self.build_ui()
        
        # キューの定期確認
        self.root.after(100, self.process_queue)

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')

        BG_COLOR = "#f5f6fa"
        HEADER_BG = "#2c3e50"
        HEADER_FG = "#ffffff"
        PRIMARY_COLOR = "#2980b9"
        ACCENT_COLOR = "#27ae60"
        WARN_COLOR = "#e67e22"
        
        self.root.configure(bg=BG_COLOR)

        self.style.configure("TFrame", background=BG_COLOR)
        self.style.configure("TLabelframe", background=BG_COLOR, font=("Segoe UI", 10, "bold"))
        self.style.configure("TLabelframe.Label", background=BG_COLOR, foreground="#333333")
        
        self.style.configure("Header.TFrame", background=HEADER_BG)
        self.style.configure("HeaderTitle.TLabel", background=HEADER_BG, foreground=HEADER_FG, font=("Segoe UI", 16, "bold"))
        self.style.configure("HeaderSub.TLabel", background=HEADER_BG, foreground="#bdc3c7", font=("Segoe UI", 9))

        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background=PRIMARY_COLOR, foreground="white")
        self.style.map("Primary.TButton", background=[("active", "#1c5980"), ("disabled", "#bdc3c7")])

        self.style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), background=ACCENT_COLOR, foreground="white")
        self.style.map("Accent.TButton", background=[("active", "#1e8449"), ("disabled", "#bdc3c7")])

        self.style.configure("Warn.TButton", font=("Segoe UI", 10, "bold"), background=WARN_COLOR, foreground="white")
        self.style.map("Warn.TButton", background=[("active", "#d35400"), ("disabled", "#bdc3c7")])

        self.style.configure("TLabel", background=BG_COLOR, font=("Segoe UI", 9))
        self.style.configure("Status.TLabel", font=("Segoe UI", 9, "italic"), foreground="#555555")

        # タブのスタイル
        self.style.configure("TNotebook", background=BG_COLOR)
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[12, 6])
        self.style.map("TNotebook.Tab", background=[("selected", "#2c3e50")], foreground=[("selected", "white")])

    def build_ui(self):
        # 1. ヘッダーエリア
        header_frame = ttk.Frame(self.root, style="Header.TFrame", padding=(15, 12))
        header_frame.pack(fill=tk.X)
        
        title_label = ttk.Label(header_frame, text="📦 Image Dataset Compressor & Decompressor", style="HeaderTitle.TLabel")
        title_label.pack(anchor=tk.W)
        
        sub_label = ttk.Label(
            header_frame, 
            text="データセットの高速並列圧縮 (npz化) および 完全元解像度復元 (解凍) ツール", 
            style="HeaderSub.TLabel"
        )
        sub_label.pack(anchor=tk.W, pady=(2, 0))

        # メインコンテンツエリア
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 2. タブコントロール (圧縮 / 解凍)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=False, pady=(0, 10))

        # タブ1: 圧縮設定
        self.tab_compress = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_compress, text=" 📦 画像データセット圧縮 (Pack) ")

        # タブ2: 解凍設定
        self.tab_decompress = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_decompress, text=" 🔓 圧縮データセット解凍 (Unpack) ")

        # --- 圧縮タブのレイアウト ---
        # フォルダ選択
        comp_folder_frame = ttk.LabelFrame(self.tab_compress, text=" 対象フォルダの指定 ", padding=8)
        comp_folder_frame.pack(fill=tk.X, pady=(0, 8))
        
        self.comp_path_var = tk.StringVar()
        ttk.Entry(comp_folder_frame, textvariable=self.comp_path_var, font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(comp_folder_frame, text="参照...", command=lambda: self.browse_folder(self.comp_path_var)).pack(side=tk.RIGHT)

        # パラメータ
        comp_param_frame = ttk.Frame(self.tab_compress)
        comp_param_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(comp_param_frame, text=f"CPUコア数 (最大{self.max_cpus}):").pack(side=tk.LEFT, padx=(0, 5))
        self.comp_cpu_var = tk.IntVar(value=self.max_cpus)
        ttk.Spinbox(comp_param_frame, from_=1, to=self.max_cpus, textvariable=self.comp_cpu_var, width=6).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(comp_param_frame, text="データセット判定閾値(枚数):").pack(side=tk.LEFT, padx=(0, 5))
        self.min_img_var = tk.IntVar(value=20)
        ttk.Spinbox(comp_param_frame, from_=1, to=1000, textvariable=self.min_img_var, width=6).pack(side=tk.LEFT)

        # ボタン
        comp_btn_frame = ttk.Frame(self.tab_compress)
        comp_btn_frame.pack(fill=tk.X)
        self.scan_comp_btn = ttk.Button(comp_btn_frame, text="🔍 対象スキャン", command=self.start_scan_compress)
        self.scan_comp_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.start_comp_btn = ttk.Button(comp_btn_frame, text="🚀 圧縮処理を開始", style="Accent.TButton", command=self.start_processing_compress)
        self.start_comp_btn.pack(side=tk.LEFT)

        # --- 解凍タブのレイアウト ---
        decomp_folder_frame = ttk.LabelFrame(self.tab_decompress, text=" 解凍対象フォルダの指定 ", padding=8)
        decomp_folder_frame.pack(fill=tk.X, pady=(0, 8))
        
        self.decomp_path_var = tk.StringVar()
        ttk.Entry(decomp_folder_frame, textvariable=self.decomp_path_var, font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(decomp_folder_frame, text="参照...", command=lambda: self.browse_folder(self.decomp_path_var)).pack(side=tk.RIGHT)

        decomp_param_frame = ttk.Frame(self.tab_decompress)
        decomp_param_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(decomp_param_frame, text=f"CPUコア数 (最大{self.max_cpus}):").pack(side=tk.LEFT, padx=(0, 5))
        self.decomp_cpu_var = tk.IntVar(value=self.max_cpus)
        ttk.Spinbox(decomp_param_frame, from_=1, to=self.max_cpus, textvariable=self.decomp_cpu_var, width=6).pack(side=tk.LEFT)

        decomp_btn_frame = ttk.Frame(self.tab_decompress)
        decomp_btn_frame.pack(fill=tk.X)
        self.scan_decomp_btn = ttk.Button(decomp_btn_frame, text="🔍 圧縮データセットスキャン", command=self.start_scan_decompress)
        self.scan_decomp_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.start_decomp_btn = ttk.Button(decomp_btn_frame, text="🔓 解凍・復元処理を開始", style="Warn.TButton", command=self.start_processing_decompress)
        self.start_decomp_btn.pack(side=tk.LEFT)

        # 3. 共有プログレスバー & ステータス
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(5, 5))

        self.status_label = ttk.Label(main_frame, text="待機中", style="Status.TLabel")
        self.status_label.pack(anchor=tk.W, pady=(0, 5))

        # 4. 共有ログ表示エリア
        log_frame = ttk.LabelFrame(main_frame, text=" 実行ログ ", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, font=("Consolas", 9), background="#1e1e1e", foreground="#dcdcdc")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_text.tag_config("INFO", foreground="#4ec9b0")
        self.log_text.tag_config("SUCCESS", foreground="#6a9955")
        self.log_text.tag_config("WARNING", foreground="#ce9178")
        self.log_text.tag_config("ERROR", foreground="#f44747")

    def log(self, message, tag="INFO"):
        self.log_queue.put((message, tag))

    def process_queue(self):
        while not self.log_queue.empty():
            msg, tag = self.log_queue.get()
            self.log_text.insert(tk.END, f"{msg}\n", tag)
            self.log_text.see(tk.END)
        self.root.after(100, self.process_queue)

    def browse_folder(self, target_var):
        selected = filedialog.askdirectory()
        if selected:
            target_var.set(selected)
            self.log(f"フォルダが指定されました: {selected}", "INFO")

    # --- 圧縮処理 ---
    def start_scan_compress(self):
        target_path = self.comp_path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        self.scan_comp_btn.config(state=tk.DISABLED)
        self.status_label.config(text="未圧縮データセット探索中...")
        threading.Thread(target=self._scan_compress_thread, args=(target_path,), daemon=True).start()

    def _scan_compress_thread(self, target_path):
        min_imgs = self.min_img_var.get()
        self.log(f"圧縮対象スキャン開始: {target_path} (閾値: {min_imgs}枚)", "INFO")
        folders = scan_datasets(target_path, min_images=min_imgs)
        self.log(f"スキャン完了. 圧縮対象フォルダ数: {len(folders)} 件", "SUCCESS")
        for idx, f in enumerate(folders, 1):
            self.log(f"  [{idx}] {f}", "INFO")
        self.root.after(0, lambda: self._on_scan_complete(self.scan_comp_btn, f"スキャン完了: {len(folders)} 件検出"))

    def start_processing_compress(self):
        if self.is_running:
            return
        target_path = self.comp_path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        num_cpus = self.comp_cpu_var.get()
        min_imgs = self.min_img_var.get()

        confirm = messagebox.askyesno(
            "圧縮処理開始の確認",
            f"指定されたフォルダ配下のデータセットを npz 圧縮します。\n"
            f"※ 圧縮後、元の画像ファイルは【削除】されます。\n\n"
            f"・対象フォルダ: {target_path}\n"
            f"・使用CPUコア数: {num_cpus}\n\n"
            f"処理を開始してよろしいですか？"
        )
        if not confirm:
            return

        self.is_running = True
        self.set_buttons_state(tk.DISABLED)
        threading.Thread(target=self._process_compress_thread, args=(target_path, num_cpus, min_imgs), daemon=True).start()

    def _process_compress_thread(self, target_path, num_cpus, min_imgs):
        self.log("===" * 15, "INFO")
        self.log("データセット圧縮処理を開始します...", "INFO")
        folders = scan_datasets(target_path, min_images=min_imgs)
        total_folders = len(folders)

        if total_folders == 0:
            self.log("対象となるデータセットフォルダが見つかりませんでした。", "WARNING")
            self.root.after(0, self._on_process_complete)
            return

        success_count = 0
        total_deleted_images = 0

        for idx, folder in enumerate(folders, 1):
            self.root.after(0, lambda p=(idx - 1) / total_folders * 100: self.progress_var.set(p))
            self.root.after(0, lambda text=f"圧縮中 ({idx}/{total_folders}): {folder.name}": self.status_label.config(text=text))

            res = process_dataset_folder(folder, min_images=min_imgs, num_workers=num_cpus, progress_callback=lambda msg: self.log(msg, "INFO"))
            if res['status'] == 'success':
                success_count += 1
                total_deleted_images += res['processed_count']
                self.log(f"[{idx}/{total_folders}] {folder.name} 圧縮完了", "SUCCESS")
            else:
                self.log(f"[{idx}/{total_folders}] {folder.name} スキップ/エラー: {res.get('message')}", "WARNING")

        self.root.after(0, lambda: self.progress_var.set(100))
        self.log("===" * 15, "SUCCESS")
        self.log(f"全圧縮処理が完了しました！ (成功: {success_count}/{total_folders} フォルダ, 削除画像: {total_deleted_images} 枚)", "SUCCESS")
        self.root.after(0, self._on_process_complete)

    # --- 解凍処理 ---
    def start_scan_decompress(self):
        target_path = self.decomp_path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        self.scan_decomp_btn.config(state=tk.DISABLED)
        self.status_label.config(text="圧縮済みデータセット探索中...")
        threading.Thread(target=self._scan_decompress_thread, args=(target_path,), daemon=True).start()

    def _scan_decompress_thread(self, target_path):
        self.log(f"解凍対象スキャン開始: {target_path}", "INFO")
        folders = scan_compressed_datasets(target_path)
        self.log(f"スキャン完了. 圧縮データセットフォルダ数: {len(folders)} 件", "SUCCESS")
        for idx, f in enumerate(folders, 1):
            self.log(f"  [{idx}] {f}", "INFO")
        self.root.after(0, lambda: self._on_scan_complete(self.scan_decomp_btn, f"スキャン完了: {len(folders)} 件の圧縮データセット検出"))

    def start_processing_decompress(self):
        if self.is_running:
            return
        target_path = self.decomp_path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        num_cpus = self.decomp_cpu_var.get()

        confirm = messagebox.askyesno(
            "解凍・復元処理開始の確認",
            f"指定されたフォルダ配下の dataset.npz を解凍・画像復元します。\n"
            f"※ 復元完了後、dataset.npz と images_index.csv は【削除】されます。\n\n"
            f"・対象フォルダ: {target_path}\n"
            f"・使用CPUコア数: {num_cpus}\n\n"
            f"処理を開始してよろしいですか？"
        )
        if not confirm:
            return

        self.is_running = True
        self.set_buttons_state(tk.DISABLED)
        threading.Thread(target=self._process_decompress_thread, args=(target_path, num_cpus), daemon=True).start()

    def _process_decompress_thread(self, target_path, num_cpus):
        self.log("===" * 15, "INFO")
        self.log("データセット解凍・復元処理を開始します...", "INFO")
        folders = scan_compressed_datasets(target_path)
        total_folders = len(folders)

        if total_folders == 0:
            self.log("対象となる圧縮データセットフォルダが見つかりませんでした。", "WARNING")
            self.root.after(0, self._on_process_complete)
            return

        success_count = 0
        total_restored_images = 0

        for idx, folder in enumerate(folders, 1):
            self.root.after(0, lambda p=(idx - 1) / total_folders * 100: self.progress_var.set(p))
            self.root.after(0, lambda text=f"解凍中 ({idx}/{total_folders}): {folder.name}": self.status_label.config(text=text))

            res = process_decompress_folder(folder, num_workers=num_cpus, progress_callback=lambda msg: self.log(msg, "INFO"))
            if res['status'] == 'success':
                success_count += 1
                total_restored_images += res['decompressed_count']
                self.log(f"[{idx}/{total_folders}] {folder.name} 解凍・復元完了", "SUCCESS")
            else:
                self.log(f"[{idx}/{total_folders}] {folder.name} 解凍エラー: {res.get('message')}", "ERROR")

        self.root.after(0, lambda: self.progress_var.set(100))
        self.log("===" * 15, "SUCCESS")
        self.log(f"全解凍・復元処理が完了しました！ (成功: {success_count}/{total_folders} フォルダ, 復元画像: {total_restored_images} 枚)", "SUCCESS")
        self.root.after(0, self._on_process_complete)

    # --- 共通ユーティリティ ---
    def _on_scan_complete(self, btn, status_msg):
        btn.config(state=tk.NORMAL)
        self.status_label.config(text=status_msg)

    def set_buttons_state(self, state):
        self.scan_comp_btn.config(state=state)
        self.start_comp_btn.config(state=state)
        self.scan_decomp_btn.config(state=state)
        self.start_decomp_btn.config(state=state)

    def _on_process_complete(self):
        self.is_running = False
        self.set_buttons_state(tk.NORMAL)
        self.status_label.config(text="すべての処理が完了しました")
        messagebox.showinfo("完了", "処理が完了いたしました！")

def main():
    root = tk.Tk()
    app = DatasetCompressorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
