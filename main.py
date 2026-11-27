import ctypes
import sys
import threading

import pywintypes
import win32api
import win32con
from injector import Injector, singleton

from utils.AutoClickUtil import AutoClickUtil
from utils.LoggerUtil import LoggerUtil
from utils.PIDLockUtil import PIDLockUtil
from utils.ShutdownUtil import ShutdownUtil
from utils.StrayUtil import StrayUtil
from utils.ThreadUtil import ThreadUtil


def ensure_admin():
    """非管理员时通过 UAC 重新启动自己。

    实测本机：非提权进程调用 Shell_NotifyIcon 会被系统拒绝（WinError 5），
    提权后托盘图标正常，所以统一以管理员身份运行。
    """
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
    except Exception:
        return

    args = " ".join(f'"{a}"' for a in sys.argv[1:])
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, args, None, 1)
    # result <= 32 表示启动失败（例如用户拒绝了 UAC）
    sys.exit(0 if result > 32 else 1)


def configure(binder):
    binder.bind(threading.Event, scope=singleton)


def check_lock():
    cur_lock_util = injector.get(PIDLockUtil)
    if cur_lock_util.is_locked():
        logger.info("Application is already running.")
        response = win32api.MessageBox(
            0,
            "仍然启动（若存在多个进程可能导致问题）",
            "后台静音正在运行",
            win32con.MB_ICONWARNING | win32con.MB_YESNO
        )
        if response == win32con.IDYES:
            logger.info("User chose to force start. Exiting other instance.")
            cur_lock_util.remove_lock()
            cur_lock_util.create_lock()
        else:
            logger.info("User chose not to force start. Exiting.")
            sys.exit(1)
    else:
        cur_lock_util.create_lock()
    return cur_lock_util


def main():
    # 让截图/坐标使用物理像素，避免 DPI 缩放导致点击偏移
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    stray_util = injector.get(StrayUtil)
    stray_util.run_detached()

    thread_util = injector.get(ThreadUtil)
    threading.Thread(
        target=thread_util.background_scanner,
        name="BGScannerThread",
        daemon=True
    ).start()

    auto_click_util = injector.get(AutoClickUtil)
    if auto_click_util.enabled:
        threading.Thread(
            target=auto_click_util.run,
            name="AutoClickThread",
            daemon=True
        ).start()

    shutdown_util = injector.get(ShutdownUtil)
    shutdown_util.loop()


if __name__ == '__main__':
    ensure_admin()

    try:
        injector = Injector(configure)

        logger = injector.get(LoggerUtil).logger
        lock_util = check_lock()

        logger.info("Starting main function.")
        main()

        lock_util.remove_lock()
    except Exception:
        # 窗口模式下看不到 traceback，落盘一份便于排查
        import traceback
        try:
            with open("crash.log", "a", encoding="utf-8") as fh:
                traceback.print_exc(file=fh)
        except Exception:
            pass
        raise

# 打包用
print(pywintypes)
# pyinstaller -Fw --add-data "resource/;resource/" -i "resource/mute.ico" -n background_muter.exe main.py

