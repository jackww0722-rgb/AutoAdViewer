# signals.py
import threading

class AppStopException(Exception):
    """自訂停止例外"""
    pass

# 🌟 唯一指定的全域紅綠燈 (加上底線代表是私有變數，不讓別人亂摸)
_global_stop_event = threading.Event()

# 提供三個遙控器按鈕給外面用
def set_stop():
    """亮紅燈 (UI 按停止時呼叫)"""
    _global_stop_event.set()

def clear_stop():
    """轉綠燈 (UI 按啟動時呼叫)"""
    _global_stop_event.clear()

def check_stop():
    """查哨 (底層工具呼叫，連參數都不用傳了！)"""
    if _global_stop_event.is_set():
        raise AppStopException("🚨 偵測到停止訊號，立刻自爆！")
    
def smart_sleep(seconds):
    """大腦專用：取代 time.sleep。睡覺時如果亮紅燈，會瞬間驚醒並自爆"""
    if _global_stop_event.wait(seconds):
        raise AppStopException("🚨 在等待期間偵測到停止訊號！")