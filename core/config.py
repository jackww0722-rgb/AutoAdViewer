import sys
import configparser
from pathlib import Path
import logging
from logging.handlers import TimedRotatingFileHandler

def get_base_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    else:
        return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_path()
_INI_PATH = BASE_DIR / "settings.ini"
_TEMPLATE_DIR = BASE_DIR / "templates"


# ==========================
# 將設定依照「職權」嚴格拆分！
# ==========================

class SysConfig:
    """系統層級設定 (給主程式 main.py 用)"""
    DEBUG_MODE:bool = True
    DEBUG_DIR = BASE_DIR / "debug_dumps"

class AdbConfig:
    """ADB 連線專用設定 (只給 adb_controller.py 用)"""
    ADB_PATH:Path = BASE_DIR / "adb_tools" / "adb.exe"
    TARGET_APP_PACKAGE = "com.linecorp.LGWKTW"
    DEVICE_SERIAL:str  = "" 
    DESIGN_WIDTH = 1080
    DESIGN_HEIGHT = 2340

class VisionConfig:
    """視覺辨識專用設定 (只給 vision.py 用)"""

    TEMPLATE_FOLDER = _TEMPLATE_DIR

    AD_CLOSES = [
        str(img_path.relative_to(_TEMPLATE_DIR)) 
        for img_path in (_TEMPLATE_DIR / "close_buttons").rglob("*.png")
    ]
    CROP_RADIUS = 35                 
    CONFIDENCE_THRESHOLD = 0.80      

class TaskProfiles:
    GAME_AD = {
        "name": "遊戲廣告",
        "portal":["GAME_AD_ENTRY_BUTTON.png"],
        "empty": ["level_ad_empty.png", "level_ad_empty2.png"],
        "entry": ["level_ad_entry.png"],
        "confirm": ["level_ad_confirm.png"],
        "reward": ["ad_reward.png"]
    }
    
    STEP_AD = {
        "name": "步數廣告",
        "portal":["STEP_AD_ENTRY_BUTTON.png"],
        "empty": ["step_ad_empty.png"],
        "entry":["step_ad_entry.png"],
        "confirm": ["step_ad_confirm.png"],
        "reward": ["ad_reward.png"]
    }

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

def setup_logger():
    """建立一個支援「終端機顯示」與「檔案寫入」的雙向記錄器"""
    log = logging.getLogger("AutoAdBot")
    
    # 預設攔截 INFO 等級以上的訊息
    # 如果 SysConfig 裡的 DEBUG_MODE 有開，就連 DEBUG 等級也一起攔截
    log.setLevel(logging.DEBUG if SysConfig.DEBUG_MODE else logging.INFO)

    # 避免重複綁定處理器 (這在熱重載時很重要)
    if not log.handlers:
        # 1. 檔案處理器 (寫入 txt 檔，指定 utf-8 避免 Windows 亂碼)


        #每天切割一次，保留最近 3 天
        file_handler = TimedRotatingFileHandler(
            filename=str(LOG_DIR / "bot_run.log"),
            when="midnight",     # 每天午夜結算
            interval=1,          # 間隔 1 天
            backupCount=3,       # 保留 3 天
            encoding='utf-8'
        )
        # 檔案裡的格式要嚴謹一點，包含完整日期
        file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)

        # 2. 終端機處理器 (印在螢幕上)
        console_handler = logging.StreamHandler(sys.stdout)
        # 螢幕上的格式可以精簡一點，只要時間就好
        console_formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
        console_handler.setFormatter(console_formatter)

        # 把兩個處理器裝上機器
        log.addHandler(file_handler)
        log.addHandler(console_handler)

    return log

logger = setup_logger()
# ==========================
# 載入邏輯 (統一在這裡更新所有小類別)
# ==========================
def load_settings():
    if not _INI_PATH.exists():
        return

    config = configparser.ConfigParser()
    config.read(_INI_PATH, encoding='utf-8')

    if 'ADB' in config:
        adb_section = config['ADB']
        if adb_path := adb_section.get('adb_path', ''):
            AdbConfig.ADB_PATH = Path(adb_path)
        if serial := adb_section.get('device_serial', ''):
            AdbConfig.DEVICE_SERIAL = serial

    if 'GAME' in config:
        SysConfig.DEBUG_MODE = config.getboolean('GAME', 'debug_mode', fallback=SysConfig.DEBUG_MODE)

load_settings()