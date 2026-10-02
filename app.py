import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from dataset_compressor import scan_datasets, process_dataset_folder

class DatasetCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Dataset Compressor & Packager")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)

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

        # カラーパレット
        BG_COLOR = "#f5f6fa"
        HEADER_BG = "#2c3e50"
        HEADER_FG = "#ffffff"
        PRIMARY_COLOR = "#2980b9"
        ACCENT_COLOR = "#27ae60"
        
        self.root.configure(bg=BG_COLOR)

        # カスタムスタイル
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

        self.style.configure("TLabel", background=BG_COLOR, font=("Segoe UI", 9))
        self.style.configure("Status.TLabel", font=("Segoe UI", 9, "italic"), foreground="#555555")

    def build_ui(self):
        # 1. ヘッダーエリア
        header_frame = ttk.Frame(self.root, style="Header.TFrame", padding=(15, 12))
        header_frame.pack(fill=tk.X)
        
        title_label = ttk.Label(header_frame, text="📦 画像データセット圧縮ツール (npz Packager)", style="HeaderTitle.TLabel")
        title_label.pack(anchor=tk.W)
        
        sub_label = ttk.Label(
            header_frame, 
            text="指定フォルダ配下のデータセット(20枚以上)を自動検出し、黒補完した上で npz に高速並列圧縮します", 
            style="HeaderSub.TLabel"
        )
        sub_label.pack(anchor=tk.W, pady=(2, 0))

        # メインコンテンツエリア
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 2. フォルダ選択フレーム
        folder_frame = ttk.LabelFrame(main_frame, text=" 1. 処理対象フォルダの指定 ", padding=10)
        folder_frame.pack(fill=tk.X, pady=(0, 10))

        self.path_var = tk.StringVar()
        path_entry = ttk.Entry(folder_frame, textvariable=self.path_var, font=("Segoe UI", 9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_btn = ttk.Button(folder_frame, text="フォルダ参照...", command=self.browse_folder)
        browse_btn.pack(side=tk.RIGHT)

        # 3. 設定パラメーターフレーム
        config_frame = ttk.LabelFrame(main_frame, text=" 2. パラメータ設定 ", padding=10)
        config_frame.pack(fill=tk.X, pady=(0, 10))

        # CPUコア選択
        cpu_label = ttk.Label(config_frame, text=f"並列処理CPUコア数 (検出最大: {self.max_cpus}):")
        cpu_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)

        self.cpu_var = tk.IntVar(value=self.max_cpus)
        cpu_spinbox = ttk.Spinbox(config_frame, from_=1, to=self.max_cpus, textvariable=self.cpu_var, width=8)
        cpu_spinbox.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)

        # 最小画像数
        min_img_label = ttk.Label(config_frame, text="データセット判定閾値 (最小枚数):")
        min_img_label.grid(row=0, column=2, sticky=tk.W, padx=(20, 5), pady=5)

        self.min_img_var = tk.IntVar(value=20)
        min_img_spinbox = ttk.Spinbox(config_frame, from_=1, to=1000, textvariable=self.min_img_var, width=8)
        min_img_spinbox.grid(row=0, column=3, sticky=tk.W, padx=5, pady=5)

        # 4. 実行コントロール
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=tk.X, pady=(0, 10))

        self.scan_btn = ttk.Button(action_frame, text="🔍 データセットをスキャン", command=self.start_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.start_btn = ttk.Button(action_frame, text="🚀 圧縮処理を開始", style="Accent.TButton", command=self.start_processing)
        self.start_btn.pack(side=tk.LEFT)

        # プログレスバー
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.status_label = ttk.Label(main_frame, text="待機中", style="Status.TLabel")
        self.status_label.pack(anchor=tk.W, pady=(0, 5))

        # 5. ログ表示エリア
        log_frame = ttk.LabelFrame(main_frame, text=" 3. 実行ログ ", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, font=("Consolas", 9), background="#1e1e1e", foreground="#dcdcdc")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ログ用タグ設定
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

    def browse_folder(self):
        selected = filedialog.askdirectory()
        if selected:
            self.path_var.set(selected)
            self.log(f"フォルダが指定されました: {selected}", "INFO")

    def start_scan(self):
        target_path = self.path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        self.scan_btn.config(state=tk.DISABLED)
        self.status_label.config(text="データセット探索中...")
        
        threading.Thread(target=self._scan_thread, args=(target_path,), daemon=True).start()

    def _scan_thread(self, target_path):
        min_imgs = self.min_img_var.get()
        self.log(f"スキャン開始: {target_path} (閾値: {min_imgs}枚)", "INFO")
        folders = scan_datasets(target_path, min_images=min_imgs)
        
        self.log(f"スキャン完了. 対象データセットフォルダ数: {len(folders)} 件", "SUCCESS")
        for idx, f in enumerate(folders, 1):
            self.log(f"  [{idx}] {f}", "INFO")
            
        self.root.after(0, lambda: self._on_scan_complete(folders))

    def _on_scan_complete(self, folders):
        self.scan_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"スキャン完了: {len(folders)} 件のデータセットを検出")

    def start_processing(self):
        if self.is_running:
            return

        target_path = self.path_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("エラー", "有効なフォルダパスを指定してください。")
            return

        num_cpus = self.cpu_var.get()
        min_imgs = self.min_img_var.get()

        confirm = messagebox.askyesno(
            "処理開始の確認",
            f"指定されたフォルダ配下のデータセットを npz 圧縮します。\n"
            f"※ 圧縮後、元の画像ファイルは【削除】されます。\n\n"
            f"・対象フォルダ: {target_path}\n"
            f"・使用CPUコア数: {num_cpus}\n\n"
            f"処理を開始してよろしいですか？"
        )
        if not confirm:
            return

        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.scan_btn.config(state=tk.DISABLED)

        threading.Thread(target=self._process_thread, args=(target_path, num_cpus, min_imgs), daemon=True).start()

    def _process_thread(self, target_path, num_cpus, min_imgs):
        self.log("===" * 15, "INFO")
        self.log("データセット圧縮・パッケージング処理を開始します...", "INFO")
        
        folders = scan_datasets(target_path, min_images=min_imgs)
        total_folders = len(folders)
        
        if total_folders == 0:
            self.log("対象となるデータセットフォルダが見つかりませんでした。", "WARNING")
            self.root.after(0, self._on_process_complete)
            return

        self.log(f"合計 {total_folders} 件のデータセットフォルダを処理します (使用CPU: {num_cpus} コア)", "INFO")

        success_count = 0
        total_deleted_images = 0

        for idx, folder in enumerate(folders, 1):
            self.root.after(0, lambda p=(idx - 1) / total_folders * 100: self.progress_var.set(p))
            self.root.after(0, lambda text=f"処理中 ({idx}/{total_folders}): {folder.name}": self.status_label.config(text=text))

            res = process_dataset_folder(
                folder,
                min_images=min_imgs,
                num_workers=num_cpus,
                progress_callback=lambda msg: self.log(msg, "INFO")
            )

            if res['status'] == 'success':
                success_count += 1
                total_deleted_images += res['processed_count']
                self.log(f"[{idx}/{total_folders}] {folder.name} の処理が成功しました。", "SUCCESS")
            else:
                self.log(f"[{idx}/{total_folders}] {folder.name} スキップ/エラー: {res.get('message')}", "WARNING")

        self.root.after(0, lambda: self.progress_var.set(100))
        self.log("===" * 15, "SUCCESS")
        self.log(f"全処理が完了しました！ (成功: {success_count}/{total_folders} フォルダ, 削除画像: {total_deleted_images} 枚)", "SUCCESS")
        
        self.root.after(0, self._on_process_complete)

    def _on_process_complete(self):
        self.is_running = False
        self.start_btn.config(state=tk.NORMAL)
        self.scan_btn.config(state=tk.NORMAL)
        self.status_label.config(text="すべての処理が完了しました")
        messagebox.showinfo("完了", "画像データセットの圧縮処理が完了いたしました！")

def main():
    root = tk.Tk()
    app = DatasetCompressorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
