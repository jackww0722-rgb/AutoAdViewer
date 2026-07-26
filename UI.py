import ctypes
import tkinter as tk
from tkinter import ttk
import threading
import logging

from core import signals  # 引入紅綠燈中心
from core.bot import AdWatcherBot

logger = logging.getLogger(__name__)

class DashboardUI:  # 把名字從 BotUI 改掉，明確表示這只是一個「儀表板」
    def __init__(self, root):
        self.root = root
        self.root.title("自動化掛機儀表板")
        self._apply_modern_style()
        
        # 🌟 加上 core_ 前綴，明確表示這些是「底層核心工具」，不是 UI 元件
        
        # 裝載大腦實體的容器
        self.active_bot_instance = None  

        self._build_layout()

    def _apply_modern_style(self):
        """套用現代化主題與全域字體"""
        style = ttk.Style()
        
        # 套用 Windows 內建的漂亮主題 (通常有 'vista', 'clam', 'winnative' 可以選)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        else:
            style.theme_use('clam')
            
        # 把所有 ttk 元件的預設字體改成微軟正黑體，大小調到 11
        style.configure(".", font=("微軟正黑體", 11))
        
        # 特別針對 LabelFrame (外框) 的標題做加粗
        style.configure("TLabelframe.Label", font=("微軟正黑體", 11, "bold"), foreground="#005599")
        
        # 讓按鈕大一點，看起來更好按
        style.configure("TButton", padding=5)

    def _build_layout(self):
        """建構畫面元件 (排版專用)"""
        # --- 模式選擇 ---
        self.task_mode_var = tk.StringVar(value="game")
        self.auto_lottery_var = tk.BooleanVar(value=False)
        frame_mode = ttk.LabelFrame(self.root, text="任務模式", padding=10)
        frame_mode.pack(fill="x", padx=10, pady=10)
        ttk.Radiobutton(frame_mode, text="遊戲廣告", variable=self.task_mode_var, value="game").pack(anchor="w")
        ttk.Radiobutton(frame_mode, text="步數廣告", variable=self.task_mode_var, value="steps").pack(anchor="w")
        # 縮排連動勾選框 (用 ttk.Checkbutton，加 padx=20 做出質感縮排)
        self.chk_auto_lottery = ttk.Checkbutton(
            frame_mode, 
            text="看完廣告自動抽獎", 
            variable=self.auto_lottery_var
        )
        self.chk_auto_lottery.pack(anchor="w", padx=20, pady=2)

        # 純粹自動抽獎單選鈕 (value 設為 "lottery")
        ttk.Radiobutton(frame_mode, text="自動抽獎", variable=self.task_mode_var, value="lottery").pack(anchor="w")

        self.task_mode_var.trace_add("write", self._on_mode_changed)
        self._on_mode_changed()

        # --- 狀態顯示 ---
        self.label_status = ttk.Label(self.root, text="狀態：待命中", foreground="green", font=("微軟正黑體", 12))
        self.label_status.pack(pady=10)

        # --- 按鈕區 ---
        frame_btn = ttk.Frame(self.root)
        frame_btn.pack(pady=10)

        # 🌟 UI 觸發的事件，統一用 on_ 開頭！
        self.btn_start = ttk.Button(frame_btn, text="▶ 啟動", command=self.on_start_clicked)
        self.btn_start.grid(row=0, column=0, padx=5)

        self.btn_stop = ttk.Button(frame_btn, text="⏹ 停止", command=self.on_stop_clicked, state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=5)

    # ---------------------------------------------------------
    # 🌟 以下為 UI 事件處理區 (Event Handlers)
    # ---------------------------------------------------------

    def on_start_clicked(self):
        """當使用者點擊「啟動」按鈕時觸發"""
        logger.info("UI: 收到啟動指令")
        
        # 1. 確保紅綠燈是綠燈
        signals.clear_stop()
        
        # 2. 更新按鈕狀態
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.label_status.config(text="狀態：運行中", foreground="red")
        
        # 3. 實例化新的大腦
        selected_job = self.task_mode_var.get()
        self.active_bot_instance = AdWatcherBot(selected_job)
        self.active_bot_instance.auto_lottery_enabled = self.auto_lottery_var.get()
        
        # 4. 把大腦丟進背景執行緒
        self.bot_thread = threading.Thread(target=self.active_bot_instance.start_task, daemon=True)
        self.bot_thread.start()
        self.monitor_bot_thread()

    def on_stop_clicked(self):
        """當使用者點擊「停止」按鈕時觸發"""    
        logger.info("UI: 收到停止指令")
        
        self.label_status.config(text="狀態：正在發送停止訊號... ⏳")
        self.root.update() 
        
        # 🌟 呼叫訊號中心亮紅燈
        signals.set_stop()
        self.reset_ui_state()

    def monitor_bot_thread(self):
        """
        巡邏員：負責檢查背景的大腦是否還活著
        """
        # 如果執行緒還在跑
        if self.bot_thread and self.bot_thread.is_alive():
            # 吩咐 Tkinter 的 MainLoop：「1000 毫秒 (1秒) 後，再來執行一次我自己」
            self.root.after(1000, self.monitor_bot_thread)
        else:
            # 如果發現執行緒已經死了 (自然結束或被例外中斷)，就執行重置
            self.reset_ui_state()

    def _on_mode_changed(self, *args):
        """ 當任務模式單選鈕切換時觸發 """
        current_mode = self.task_mode_var.get()
        
        # 只有在「步數廣告 (steps)」模式下，連動勾選框才有用
        if current_mode == "steps":
            self.chk_auto_lottery.config(state="normal")
        else:
            self.chk_auto_lottery.config(state="disabled")

    def reset_ui_state(self):
        """
        重置員：負責把按鈕和狀態列恢復原狀
        """
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.label_status.config(text="狀態：已停止", foreground="green")

if __name__ == "__main__":
    # 🌟 UI 醫美第二步：解除 Windows 模糊封印 (必須在 tk.Tk() 之前執行)
    try:
        # 告訴系統：這個程式支援高解析度 (DPI Aware)
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception as e:
        logger.debug(f"無法設定高解析度模式: {e}")

    root = tk.Tk()
    
    # 稍微把視窗拉大一點點，配合銳利化後的字體
    root.geometry("320x305") 
    
    app = DashboardUI(root)
    root.mainloop()