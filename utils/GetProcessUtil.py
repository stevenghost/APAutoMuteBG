import psutil
import win32gui
import win32process
from pycaw.utils import AudioUtilities


def get_all_audio_sessions():
    """返回当前有效的音频会话。

    Windows 的音频会话在进程退出后还可能残留一段时间（由音频服务持有），
    所以这里额外检查进程是否真的还活着，避免把已退出的程序列出来。
    """
    res = []
    for session in AudioUtilities.GetAllSessions():
        proc = session.Process
        if proc is None:
            continue
        try:
            if not proc.is_running():
                continue
            proc.name()          # 进程已退出时会抛 NoSuchProcess
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        res.append(session)
    return res


def get_all_window_processes():
    window_processes = []
    ignore_list = ['TextInputHost.exe']  # 添加过滤列表

    def enum_window_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                p = psutil.Process(pid)
                process_name = p.name()
                if process_name not in ignore_list:
                    window_title = win32gui.GetWindowText(hwnd)
                    window_processes.append((process_name, window_title))
            except psutil.NoSuchProcess:
                pass

    win32gui.EnumWindows(enum_window_callback, None)
    return window_processes

