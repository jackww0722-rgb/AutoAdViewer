import numpy as np
import cv2
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from . import config
from .config import logger
import adbutils


class AdbController:
    def __init__(self,sys_config:type[config.SysConfig], adb_config: type[config.AdbConfig]):
        """
        1. 初始化階段：只綁定設定檔，預設所有屬性。
        絕對不碰網路連線，保證瞬間建立物件不報錯。
        """
        self.sys_config = sys_config
        self.adb_config = adb_config
        self.device: Any = None
        
        # 預設解析度與縮放屬性
        self.real_w = 0
        self.real_h = 0
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        # 設定 ADB 路徑可以放在這裡，因為這只是修改本地變數
        if self.adb_config.ADB_PATH.exists():
            adbutils.adb_path = self.adb_config.ADB_PATH

    def connect(self) -> bool:
        """
        2. 連線階段：由外部主動呼叫，負責連線並更新設備狀態。
        """
        target_serial = self.adb_config.DEVICE_SERIAL.strip()
        logger.info(f"🔗 正在準備連線...")

        try:
            if not target_serial:
                logger.info("🔍 未指定序號，正在自動搜尋裝置...")
                devices = adbutils.adb.device_list()
                if not devices:
                    raise RuntimeError("未偵測到任何 ADB 裝置！請確認模擬器已開啟。")
                self.device = devices[0]
                self.device.shell("echo hello") # 測試連線
                logger.info(f"✅ 自動鎖定裝置: {self.device.serial}")
            else:
                self.device = adbutils.adb.device(serial=target_serial)
                self.device.shell("echo hello") # 測試連線
                logger.info(f"✅ 連線成功: {self.device.serial}")
            
            # 連線成功後，順便呼叫計算解析度的方法
            self._update_resolution_and_scale()
            return True
            
        except Exception as e:
            logger.error(f"❌ 連線失敗: {e}")
            raise RuntimeError("ADB_DEVICE_NOT_FOUND")

    def _update_resolution_and_scale(self):
        """
        3. 計算階段：負責向設備要解析度，並計算縮放比例與偏移量。
        設為私有方法 (前面加底線)，因為外部不需要直接呼叫它。
        """
        if not self.device:
            return

        self.real_w, self.real_h = self._get_device_resolution()
        
        ratio_w = self.real_w / self.adb_config.DESIGN_WIDTH
        ratio_h = self.real_h / self.adb_config.DESIGN_HEIGHT
        
        self.scale = min(ratio_w, ratio_h)
        actual_content_w = self.adb_config.DESIGN_WIDTH * self.scale
        actual_content_h = self.adb_config.DESIGN_HEIGHT * self.scale
        
        self.offset_x = (self.real_w - actual_content_w) / 2
        self.offset_y = (self.real_h - actual_content_h) / 2
        
        logger.debug(f"📱 解析度: {self.real_w}x{self.real_h}")
        logger.debug(f"⚖️ 縮放比: {self.scale:.3f} | ↔ X偏移: {self.offset_x:.1f} | ↕ Y偏移: {self.offset_y:.1f}")

    def _get_device_resolution(self) -> tuple[int, int]:
        """ 
        使用 ADB 獲取解析度
        回傳: (寬, 高) 
        保證不會回傳 None，失敗時回傳預設值 
        """
        try:
            # 1. 嘗試問手機
            output = self.device.shell("wm size")
            
            # 2. 嘗試抓數字
            if output:
                match = re.search(r"(\d+)x(\d+)", output)
                if match:
                    return int(match.group(1)), int(match.group(2))
            
        except Exception as e:
            logger.debug(f"⚠️ 解析度偵測失敗: {e}")
        
        # ==========================================
        # 🛡️ 安全網 (Safety Net)
        # 只要上面發生錯誤 (Exception) 或 沒抓到 (match is None)
        # 程式都會跑到這裡
        # ==========================================
        logger.warning(f"⚠️ 無法取得真實解析度，使用預設值: {self.adb_config.DESIGN_WIDTH}x{self.adb_config.DESIGN_HEIGHT}")
        return self.adb_config.DESIGN_WIDTH, self.adb_config.DESIGN_HEIGHT

    def get_screenshot(self):
        """ 
        [核心功能] 獲取畫面 -> 裁切黑邊 -> 縮放至標準大小
        回傳: OpenCV BGR 格式圖片
        """
        try:
            cmd = "screencap -p"
            connection = self.device.shell(cmd, stream=True)
            
            # 2. 【修正點】改用迴圈分批讀取
            # Pylance 抱怨 read() 需要參數，我們就每次讀 4096 bytes (4KB)
            # 這樣也比較不會因為網路延遲造成圖片讀取不完整
            data_buffer = bytearray()
            while True:
                chunk = connection.read(4096) # 每次讀 4KB
                if not chunk:
                    break # 讀不到東西代表結束了
                data_buffer.extend(chunk)
            
            raw_bytes = bytes(data_buffer)
            # 2. 直接解碼為 OpenCV 格式 (預設就是 BGR，不用再 cvtColor)
            img_array = np.frombuffer(raw_bytes, np.uint8)
            raw_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if raw_img is None:
                logger.error("❌ 截圖解碼失敗 (回傳 None)")
                return None

            # 3. 判斷是否需要縮放與裁切
            # 如果比例是 1.0 且沒有偏移，代表解析度完全一樣，直接回傳
            if self.scale == 1.0 and self.offset_x == 0 and self.offset_y == 0:
                return raw_img

            # --- 處理不同解析度 (等比縮放邏輯) ---
            
            # A. 裁切 (Crop): 去掉手機多餘的黑邊
            # 陣列切片語法: img[y1:y2, x1:x2]
            y_start = int(self.offset_y)
            y_end = int(self.real_h - self.offset_y)
            x_start = int(self.offset_x)
            x_end = int(self.real_w - self.offset_x)
            
            # 防呆：確保裁切範圍合理 (避免負數導致報錯)
            if y_start >= y_end or x_start >= x_end:
                 logger.warning(f"⚠️ 裁切參數異常，回傳原始圖片 (Offset: {self.offset_x}, {self.offset_y})")
                 return raw_img

            cropped_img = raw_img[y_start:y_end, x_start:x_end]

            # B. 縮放 (Resize): 變回標準大小 (Design Resolution)
            target_size = (self.adb_config.DESIGN_WIDTH, self.adb_config.DESIGN_HEIGHT)
            final_img = cv2.resize(cropped_img, target_size, interpolation=cv2.INTER_LINEAR)
            
            return final_img

        except Exception as e:
            logger.error(f"❌ 截圖流程發生錯誤: {e}")
            return None

    def tap(self, x, y):
        """
        [輸出端] 標準座標 -> 乘上比例 -> 加上偏移量 -> 真實座標
        """
        # 公式： (標準座標 * 縮放比) + 黑邊偏移
        real_x = int(x * self.scale + self.offset_x)
        real_y = int(y * self.scale + self.offset_y)
        
        logger.debug(f"👆 映射: ({x},{y}) -> ({real_x},{real_y})")
        self.device.click(real_x, real_y)

    def press_back(self):
        """模擬按下 Android 返回鍵 (KEYCODE_BACK = 4)"""
        logger.info("發送實體返回鍵指令")
        # 使用你原本封裝好的 execute_command 即可
        self.device.keyevent("BACK")


    def stop_app(self, package_name:str | None = None):
        target = package_name or self.adb_config.TARGET_APP_PACKAGE
        logger.info(f"正在關閉 APP: {target}")
        self.device.app_stop(target)

    def start_app(self, package_name:str | None = None):
        target = package_name or self.adb_config.TARGET_APP_PACKAGE
        logger.info(f"正在開啟 APP: {target}")
        self.device.app_start(target)

    def restart_app(self, package_name:str | None = None):
        """ [系統] 快速重啟 (殺掉 -> 打開) """
        self.stop_app(package_name)
        time.sleep(3.0) # 系統反應時間
        self.start_app(package_name)

    def get_foreground_app(self) -> str | None:
        """
        獲取當前前景運作的 APP 包名 (Package Name)
        回傳: 包名字串，若抓取失敗則回傳 None
        """
        try:
            app_info = self.device.app_current()
            return app_info.package if app_info else None
        except Exception as e:
            logger.debug(f"取得前景 APP 失敗 (可能正處於過場動畫): {e}")
            return None

    def get_ui_xml(self, save_dir=None):
        """
        獲取當前模擬器畫面的 UI 結構 (XML)，並存回本地電腦。
        """
        try:
            # 魔法在這裡！adbutils 內建 dump_hierarchy() 
            # 它會直接把 Android 畫面的 XML 當作純文字字串抓回來，不用 pull 檔案！
            xml_content = self.device.dump_hierarchy(timeout=2.0)
            if save_dir is None:
                save_dir = self.sys_config.DEBUG_DIR
            # 使用 pathlib 優雅地將字串寫入本地檔案
            if self.sys_config.DEBUG_MODE:
                save_path = Path(save_dir)
                save_path.mkdir(parents=True, exist_ok=True)
                local_xml_path = save_path / "window_dump.xml"
                local_xml_path.write_text(xml_content, encoding="utf-8")
            
                logger.info(f"✅ UI 結構已成功儲存至: {local_xml_path.resolve()}")
            return xml_content
            
        except Exception as e:
            logger.warning(f"❌ 獲取 UI 失敗，錯誤訊息: {e}")
            return None
        
    def find_element_by_keywords(self, keywords):
        """
        解析當前畫面的 XML，尋找符合關鍵字的按鈕，回傳 (x, y) 座標。
        keywords: list，例如 ["Close Ad", "Close", "跳過", "關閉", "X"]
        """
        xml_content = self.get_ui_xml()
        if not xml_content:
            return None
            
        try:
            # 直接從記憶體中的字串解析 XML，不用讀取實體檔案！
            root = ET.fromstring(xml_content)
            
            for node in root.iter('node'):
                text = node.get('text', '')
                content_desc = node.get('content-desc', '')
                resource_id = node.get('resource-id', '')
                
                # 只要屬性中包含關鍵字就抓取
                if any(k in text or k in content_desc or k in resource_id for k in keywords):
                    bounds = node.get('bounds')
                    if bounds:
                        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
                        if match:
                            x1, y1, x2, y2 = map(int, match.groups())
                            center_x = (x1 + x2) // 2
                            center_y = (y1 + y2) // 2
                            
                            logger.info(f"✅ 透過 XML 找到關鍵字按鈕{keywords} -> 座標: ({center_x}, {center_y})")
                            return (center_x, center_y)
                            
        except Exception as e:
            logger.warning(f"❌ 解析 XML 發生錯誤: {e}")
            
        return None