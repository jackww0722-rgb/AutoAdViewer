import cv2
import numpy as np
import logging
from . import config
from .config import logger
from .signals import check_stop

class ImageFinder:
    def __init__(self, sys_config : type[config.SysConfig], vision_config : type[config.VisionConfig]):
        self.sys_config = sys_config
        self.vision_config = vision_config

        self.template_cache = {}

    def _cv2_imread_safe(self, file_path):
        """ 
        [工具] 解決 Windows 路徑含有中文或特殊字元無法讀取的問題 
        這是 find_and_get_pos 需要呼叫的幫手函式
        """
        try:
            # 先用 numpy 讀取原始數據 (避開路徑編碼問題)
            img_array = np.fromfile(str(file_path), dtype=np.uint8)
            # 再解碼成圖片
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            logger.error(f"⚠️ 讀取圖片失敗: {file_path} | 錯誤: {e}")
            return None

    def _get_template_image(self, template_name: str):
        """ 讀取圖片的守門員：如果記憶體有，就直接給；沒有再去硬碟抓 """
        
        # 1. 檢查快取有沒有？
        if template_name in self.template_cache:
            return self.template_cache[template_name]
            
        # 2. 如果沒有，才真的去硬碟讀取
        template_path = self.vision_config.TEMPLATE_FOLDER / template_name
        template = self._cv2_imread_safe(template_path)
        
        if template is not None:
            # 3. 讀到之後，把它存進快取字典裡，下次就不用再讀硬碟了！
            self.template_cache[template_name] = template
            logger.debug(f"💾 已將 {template_name} 載入記憶體快取")
            
        return template

    def find_and_get_pos(self, screen, targets: str | list[str], threshold: float | None = None):
        """
        [視覺核心] 在畫面中尋找目標圖片。
        支援傳入單一字串或清單，統一回傳 (圖片名稱, (x, y)) 或 (None, None)。
        """
        # 1. 防呆檢查：螢幕截圖失敗 (拉到最上面，提早擋掉)
        if screen is None:
            logger.error("❌ 螢幕截圖失敗 (Screen is None)，請檢查 ADB 傳入的畫面")
            return None, None

        threshold = threshold or self.vision_config.CONFIDENCE_THRESHOLD

        # 2. 處理：不管傳字串還是清單，統一轉成清單
        target_list = [targets] if isinstance(targets, str) else targets

        # 3. 依序對清單內的圖片進行尋找
        for template_name in target_list:
            check_stop()
            # 呼叫上面的安全讀取法
            template = self._get_template_image(template_name)
            
            # ⚠️ 防呆檢查：圖片讀取失敗 -> 改用 continue 跳過，繼續找下一張
            if template is None:
                logger.error(f"⚠️ 找不到或無法讀取圖片: {template_name}，跳過這張。")
                continue

            # ⚠️ 防呆檢查：尺寸不合 -> 一樣用 continue 跳過
            if template.shape[0] > screen.shape[0] or template.shape[1] > screen.shape[1]:
                logger.error(f"⚠️ 圖片 {template_name} 尺寸大於螢幕，跳過這張。")
                continue

            # 開始 OpenCV 匹配
            if template.shape[2] == 4:
                # 這是 4 通道的去背圖！
                # 分離出 RGB 顏色層與 Alpha 遮罩層
                template_rgb = template[:, :, :3]
                alpha_mask = template[:, :, 3]

                # 🌟 注意：有遮罩時，演算法必須換成 TM_CCORR_NORMED
                result = cv2.matchTemplate(
                    screen, 
                    template_rgb, 
                    cv2.TM_CCORR_NORMED, 
                    mask=alpha_mask
                )
            else:
                # 這是普通的 3 通道圖片，走傳統比對流程
                result = cv2.matchTemplate(
                    screen, 
                    template, 
                    cv2.TM_CCOEFF_NORMED
                )

            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            logger.debug(f"🔍 目前跟 {template_name} 比對 相似度: {max_val:.2f}")
            # 如果信心值達標，計算中心點並立刻回傳
            if max_val >= threshold:
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                
                # 統一天下：永遠回傳 (名稱, 座標)
                return template_name, (center_x, center_y)
                
        # 4. 整個清單的圖片都找完了，還是沒有達標的
        return None, None

    def find_text_button(self, screen, template_name, threshold=0.7):
        """
        [專門找文字] 使用二值化 (Binarization) 處理
        這能有效解決「字體顏色太淡」或「背景半透明」的問題
        """
        # 1. 讀取模板 (強制轉灰階)
        template_path = self.vision_config.TEMPLATE_FOLDER/template_name
        if not template_path.exists():
            logger.error(f"❌ 找不到模板: {template_name}")
            return False, None
        
        template = cv2.imdecode(
            np.fromfile(str(template_path), dtype=np.uint8), 
            cv2.IMREAD_GRAYSCALE # 🌟 這裡可以直接指定灰階
            )
        
        # 2. 將螢幕截圖也轉灰階
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

        if template is None:
            logger.error(f"❌ 找不到圖片: {template_path}")
            return  # 沒讀到就提早結束

        # === 🔥 關鍵魔法：二值化處理 ===
        # 設定一個切分點 (例如 180)，低於這個亮度(字體)變 255(白)，高於這個亮度(背景)變 0(黑)
        # THRESH_BINARY_INV 代表「反向」，讓深色字體變亮，淺色背景變暗
        _, screen_bin = cv2.threshold(screen_gray, 180, 255, cv2.THRESH_BINARY_INV)
        _, template_bin = cv2.threshold(template, 180, 255, cv2.THRESH_BINARY_INV)

        # (Debug用) 如果您想看處理完長怎樣，可以把這行打開存下來看
        # cv2.imwrite(f"debug_bin_{template_name}", screen_bin)

        # 3. 進行匹配
        result = cv2.matchTemplate(screen_bin, template_bin, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            # 計算中心點
            h, w = template.shape
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            logger.debug(f"   🔍 [TextMode] 找到 {template_name} (信心度: {max_val:.2f})")
            return True, (center_x, center_y)
        else:
            return False, None

    def apply_blackout(self, image_array, x_range=None, y_range=None):
        """
        [視覺工具] 在畫面上貼上黑膠布（排除干擾區域）。
        支援傳入負數（代表從邊緣往回扣）。
        :param image_array: 原始截圖的 numpy 陣列
        :param x_range: Tuple (起始X, 結束X)，若為 None 代表 X 軸全包
        :param y_range: Tuple (起始Y, 結束Y)，若為 None 代表 Y 軸全包
        """
        masked = image_array.copy()
        
        # 取得圖片的總高(h)與總寬(w)
        h, w = masked.shape[:2]
        
        # 如果沒給範圍，預設就是 0 到最大值
        x1, x2 = x_range if x_range else (0, w)
        y1, y2 = y_range if y_range else (0, h)
        
        # 🌟 進階防呆與負數支援：例如傳入 -150，就會自動換算成 w - 150
        x1 = x1 if x1 >= 0 else w + x1
        x2 = x2 if x2 >= 0 else w + x2
        y1 = y1 if y1 >= 0 else h + y1
        y2 = y2 if y2 >= 0 else h + y2
        
        # 將指定區塊塗黑 (像素設為 0)
        masked[y1:y2, x1:x2] = 0
        
        return masked