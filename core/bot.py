import time
from .config import SysConfig, AdbConfig, VisionConfig, logger, TaskProfiles
from .adb_controller import AdbController
from .vision import ImageFinder
from .signals import AppStopException, check_stop, smart_sleep

class AdWatcherBot:
    def __init__(self, job_type_str: str):
        self.sysconfig = SysConfig
        self.adbconfig = AdbConfig
        self.visionconfig = VisionConfig

        self.adb = AdbController(self.sysconfig, self.adbconfig)
        self.vision = ImageFinder(self.sysconfig, self.visionconfig)

        # 🌟 1. 設定初始狀態
        self.current_state = "IDLE"
        
        # 🌟 2. 建立「狀態分發表 (Dispatch Table)」
        # 什麼狀態，就對應執行哪個函數
        if job_type_str == "game":
            self.task = TaskProfiles.GAME_AD
        elif job_type_str == "steps":
            self.task = TaskProfiles.STEP_AD
        else:
            raise ValueError(f"未知的任務類型: {job_type_str}")

        self.state_handlers = {
            "IDLE": self.handle_idle,
            "WAIT_CONFIRM": self.handle_wait_confirm,
            "WATCHING_AD": self.handle_watching_ad,
        }

        logger.info(f"🤖 機器人啟動，當前任務：{self.task['name']}")
      
    def wait_for_image(self, image_name: str | list[str], timeout: int = 10, interval: float = 1.0):
        """
        在指定時間內 (timeout)，每隔一段時間 (interval) 不斷截圖尋找目標。
        找到就回傳座標，超時就回傳 None。
        """
        logger.info(f"⏳ 準備尋找 [{image_name}] (最多等待 {timeout} 秒)...")

        if isinstance(image_name, str):
            image_name = [image_name]

        start_time = time.time()
        
        while time.time() - start_time < timeout:
            check_stop()

            screen = self.adb.get_screenshot()
            if screen is None:
                smart_sleep(2)
                continue

            img, coords = self.vision.find_and_get_pos(screen, image_name)

            if coords is not None:
                return img, coords
                
            # 沒找到就睡一下，避免截圖太快讓電腦卡死
            time.sleep(interval)
            
        logger.warning(f"⌛ 警告：等待 [{image_name}] 超時！可能網路卡住或畫面異常。")
        return None, None

    #==========================================
    #------------------主程式------------------
    #==========================================
    def run(self, close_app : bool = False):
        """ 永遠只有薄薄一層的主迴圈，再也沒有巢狀 if！ """
        self.adb.connect()   #還沒寫UI 暫時先在這邊呼叫adb連線
        logger.info("🚀 啟動狀態機模式！")
        try:
            while self.current_state != "DONE":
                check_stop()
                # 從字典裡拿出當前狀態該執行的函數
                handler = self.state_handlers.get(self.current_state)
                
                if handler:
                    # 執行該函數，函數會回傳「下一個狀態」給我們！
                    self.current_state = handler()
                else:
                    logger.error(f"❌ 未知狀態：{self.current_state}")
                    break
                    
                time.sleep(1) # 讓迴圈稍微喘口氣
                
            logger.info("🏁 任務圓滿結束！")
            if close_app:
                self.adb.stop_app()
        except AppStopException as e:
            # 🌟 攔截網：不管是 ADB、Vision 還是 sleep 拋出的自爆，都會在這裡被接住
            logger.info(f"🛑 收到總部停止命令，已安全撤退: {e}")
        finally:
            logger.info(">>> 機器人資源清理完畢。")
        

    #==========================================
    #--------------I NEED HEALING--------------
    #==========================================
    def navigate_to_ad_entry(self, force_restart=False):
        """
        從任何地方啟動並導航至廣告入口
        回傳值: "WATCHING_AD" (成功點擊入口) 或 "ERROR" (超時或失敗)
        """
        logger.info("🚀 啟動全域導航程序...")
        
        # 1. 確保遊戲在前景 (喚醒機制)
        current_app = self.adb.get_foreground_app()

        if not force_restart and (current_app == self.adbconfig.TARGET_APP_PACKAGE):
            logger.info("遊戲已在前景，跳過重啟程序，直接交付狀態機巡邏。")
            return "IDLE"
        

        logger.info("遊戲未在前景，執行強制喚醒...")
        self.adb.restart_app(self.adbconfig.TARGET_APP_PACKAGE)
        smart_sleep(5) # 給遊戲一點冷卻與初步載入的時間
    
        # 2. 尋找入口的輪詢迴圈 (最長嘗試 60 秒)

        start_time = time.time()
        timeout = 60 
        
        
        while time.time() - start_time < timeout:
            check_stop() # 🌟 保持對 UI 停止鍵的敏銳度
            
            screen = self.adb.get_screenshot()
            if screen is None:
                smart_sleep(1)
                continue
                
            # 🎯 優先目標：尋找廣告入口按鈕
            target_name, coords = self.vision.find_and_get_pos(
                screen, 
                "AD_ENTRY_BUTTON.png", 
                threshold=0.8
            )
            
            if target_name and coords is not None:
                logger.info(f"✅ 成功鎖定廣告入口！座標: {coords}，點擊進入！")
                self.adb.tap(*coords)
                smart_sleep(2) # 等待廣告載入
                return "IDLE" # 成功！切換狀態到看廣告迴圈
            else: self.check_and_clear_error(screen)
            

            # 3. 盲等區與除障機制 (Wiper)

            # 如果還沒看到入口，可能原因：1. 還在載入 2. 被每日登入/公告彈窗擋住 3. 卡在子選單
            logger.info("🔍 尚未看見入口，尋找中...(可能被彈窗遮擋或載入中)")
            
                
            smart_sleep(2)

    # 迴圈結束代表超時
        logger.error("❌ 全域導航超時！無法在 60 秒內找到廣告入口。")
        return "DONE"
    

       
    def check_and_clear_error(self,screen):
        _, pos =self.vision.find_and_get_pos(screen, "error_closed.png")

        if pos is not None:
            logger.warning("🚨 偵測到系統錯誤或斷線彈窗！啟動自動排除...")
            self.adb.tap(*pos)
            smart_sleep(1)
            return True
        return False
    # ==========================================
    # 以下是每個狀態的獨立邏輯 (彼此互不干擾)
    # ==========================================
    def handle_idle(self):
        """ 狀態：待命中 (尋找入口) """
        # ==========================================
        # 🌟 首次啟動防呆：只在第一次進入 IDLE 時執行
        # ==========================================
        if not getattr(self, 'has_navigated', False):
            logger.info("🚀 首次開機：執行全域防呆導航...")
            
            # 呼叫導航機制 (確保 App 在前景，或點擊掉剛開遊戲的彈窗)
            self.navigate_to_ad_entry()
            
            # 貼上標籤，告訴大腦「已經導航過了」，以後這個 if 永遠不會再觸發
            self.has_navigated = True
            
            # 導航完給畫面一點緩衝時間，然後直接返回 IDLE，準備進入正式掃描
            smart_sleep(2)
            return "IDLE"
        
        if not hasattr(self, 'idle_start_time'):
            self.idle_start_time = time.time()
            logger.info("⏱️ 開始記錄 IDLE 待命時間...")

        if time.time() - self.idle_start_time > 300:
            logger.error("🚨 待命超時！超過 5 分鐘沒看到任何廣告入口，強制收工。")
            delattr(self, 'idle_start_time') # 離開前撕掉計時器標籤
            return "DONE"
        
        check_stop()
        screen = self.adb.get_screenshot()
        if screen is None:
            logger.error("❌ 系統失明！停止狀態機運作。")
            return "DONE"
        
        if self.check_and_clear_error(screen):
            return "IDLE"

        target, coords = self.vision.find_and_get_pos(screen, self.task["entry"] + self.task["empty"],threshold= 0.9)
        if coords is None:
            # 沒找到按鈕，繼續待命等它出現
            return "IDLE"

        if hasattr(self, 'idle_start_time'):
                delattr(self, 'idle_start_time')

        if target in self.task["empty"]:
            return "DONE" # 沒廣告了，切換到結束狀態
            
        elif target in self.task["entry"]:
            logger.info("👆 點擊廣告入口")
            self.adb.tap(*coords)
            return "WAIT_CONFIRM" # 切換到等待確認狀態
            
        return "IDLE" # 什麼都沒找到，維持原狀態繼續找

    def handle_wait_confirm(self):
        """ 狀態：等待確認視窗彈出 """
        check_stop()
        _, coords = self.wait_for_image(self.task["confirm"], timeout=5)
        if coords is not None:
            logger.info("👆 點擊確認，開始看廣告")
            self.adb.tap(*coords)
            self.ad_start_time = time.time()
            time.sleep(5) #不急 蹲好 讓廣告 再飛一會兒
            return "WATCHING_AD" # 成功！切換到看廣告狀態
        else:
            logger.warning("⚠️ 等不到確認視窗，退回主畫面重試")
            return "IDLE" # 失敗！退回初始狀態重新來過
        
    def handle_watching_ad(self):
        check_stop()
        
        # ==========================================
        # 0. 全域超時防呆 (180秒核彈)
        # ==========================================
        if time.time() - getattr(self, 'ad_start_time', time.time()) > 180:
            logger.error("🚨 廣告卡死超過 180 秒！！")
            next_state = self.navigate_to_ad_entry(force_restart=True)
            if hasattr(self, 'ad_start_time'):
                delattr(self, 'ad_start_time')
            return next_state
        
        # ==========================================
        # 1. 取得畫面與絕對出口檢查
        # ==========================================
        screen = self.adb.get_screenshot()
        if screen is None: 
            logger.error("❌ 系統失明！")
            smart_sleep(1)
            return "WATCHING_AD"
            
        target_name, coords = self.vision.find_and_get_pos(
            screen, 
            self.task["reward"]+ self.task["entry"]
        )
        
        if target_name in self.task["reward"] and coords is not None:
            logger.info("🎁 看到獎勵畫面了！點擊領取。")
            self.adb.tap(*coords)
            smart_sleep(2)
            return "IDLE"  # 領完收工
            
        elif target_name in self.task["entry"]:
            logger.info("🏠 直接回到主畫面了，廣告徹底結束。")
            return "IDLE"

        # ==========================================
        # 🛡️ 防線一：XML 解析尋找關閉按鈕
        # ==========================================
        print("🔍 [防線一] 嘗試解析 XML 尋找關閉按鈕...")
        close_keywords = [
            "Close", "close", "Close Ad", "close_button",
            "Skip", "skip", "Skip All",
            "關閉", "跳過", "略過", 
            "X", "x", "×"
        ]

        if coords := self.adb.find_element_by_keywords(close_keywords):
            logger.info(f"✅ 成功透過 XML 找到關閉節點！座標: {coords}")
            self.adb.tap(coords[0], coords[1]) 
            smart_sleep(2)
            return "WAIT_REWARD"
        else:
            logger.info("⚠️ XML 中找不到明確的關閉節點，進入視覺掃描。")
            
        # ==========================================
        # 🛡️ 防線二：OpenCV 視覺找圖
        # ==========================================
        logger.info("👁️ [防線二] 啟動視覺掃描系統...")
        screen_masked = self.vision.apply_blackout(
            screen, 
            x_range=(200, 880) 
        )
        target_name, coords = self.vision.find_and_get_pos(
            screen_masked, 
            VisionConfig.AD_CLOSES, threshold=0.85 
        )

        if target_name and coords is not None:
            logger.info(f"✅ OpenCV 成功狙擊廣告叉叉: {target_name}！座標: {coords}")
            self.adb.tap(*coords)
            smart_sleep(3)
            return "WATCHING_AD"
            
        # ==========================================
        # 🛡️ 防線三：延遲綁架審查與「先禮後兵」遣返
        # ==========================================
        # 只有在廣告看了超過 15 秒，且畫面完全找不到叉叉時，才去查 App 名字
        if time.time() - self.ad_start_time > 15:
            try:
                current_app = self.adb.get_foreground_app()
                if current_app and self.adbconfig.TARGET_APP_PACKAGE not in current_app:
                    
                    # 紀錄綁架次數
                    self.kidnap_count = getattr(self, 'kidnap_count', 0) + 1
                    logger.warning(f"⚠️ 確認遭到綁架至 {current_app}！(第 {self.kidnap_count} 次遣返)")
                    
                    if self.kidnap_count <= 2:
                        logger.info("實施溫和遣返：按下實體返回鍵...")
                        self.adb.press_back()
                        smart_sleep(2)
                        return "WATCHING_AD"
                    else:
                        logger.warning("實施強硬遣返：返回鍵無效，強制召喚遊戲！")
                        self.adb.start_app(self.adbconfig.TARGET_APP_PACKAGE)
                        self.kidnap_count = 0 # 歸零重新計算
                        smart_sleep(3)
                        return "WATCHING_AD"
                else:
                    self.kidnap_count = 0 # 乖乖在遊戲內，歸零
            except Exception as e:
                logger.debug(f"查勤失敗，略過: {e}")

        # ==========================================
        # ⏳ 盲等區
        # ==========================================
        logger.info("⏳ 廣告關閉失敗，繼續監視中...")
        smart_sleep(3) 
        return "WATCHING_AD"

# ==========================================
# 程式進入點
# ==========================================
if __name__ == "__main__":
    try:
        current_job = "game"  #STEP_AD,GAME_AD
        bot = AdWatcherBot(current_job)
        bot.run()
    except KeyboardInterrupt:
        logger.info("🛑 收到手動中斷指令 (Ctrl+C)，腳本安全退出。")
    except Exception as e:
        logger.exception("💥 發生未預期的系統崩潰！")