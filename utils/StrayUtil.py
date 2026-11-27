import os
import threading
import time
import time
import webbrowser

import ctypes

import win32api
import win32con
import win32gui
import win32process
import win32security
from injector import singleton, inject

from utils import VolumeGuard
from utils.ConfigUtil import ConfigUtil
from utils.PathUtil import resource_path
from utils.GetProcessUtil import get_all_audio_sessions, get_all_window_processes
from utils.LoggerUtil import LoggerUtil

# ---- Shell_NotifyIcon 常量（避免依赖 win32gui 里不一定存在的名字）----
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10

WM_TRAY = win32con.WM_APP + 1
MENU_ID_BASE = 1000


def _open_site():
    webbrowser.open('https://github.com/stevenghost/APAutoMuteBG')


class TrayIcon:
    """用原生 Shell_NotifyIcon 实现的托盘图标（替代 pystray）。

    只依赖 pywin32，避免 pystray 在 PyInstaller 冻结环境下
    ChangeWindowMessageFilterEx 报 WinError 5 导致托盘线程退出的问题。
    """

    def __init__(self, icon_path, tooltip, menu_items, logger=None):
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.menu_items = menu_items  # [(文本, 回调), ...]
        self.logger = logger
        self.hwnd = None
        self.hicon = None
        self._class_name = "AutoMuteBGTrayWindow"
        self._class_atom = None
        # Explorer 重启后会广播该消息，需要重新添加图标
        self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")

    # ---------- 对外接口 ----------
    def run(self, on_ready=None):
        self._create_window()
        ok = self._add_icon()
        # 通知/日志不要等图标重试，立即回调，避免启动被托盘拖到 10 秒
        if on_ready:
            try:
                on_ready()
            except Exception:
                if self.logger:
                    self.logger.exception("Tray on_ready failed")
        if not ok:
            threading.Thread(target=self._retry_add_icon,
                             name="TrayRetryThread", daemon=True).start()
        win32gui.PumpMessages()

    def _retry_add_icon(self, attempts=12, delay=1.0):
        for _ in range(attempts):
            if self._add_icon():
                return
            time.sleep(delay)

    def stop(self):
        if self.hwnd:
            try:
                win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass

    def notify(self, message, title=None):
        if not self.hwnd:
            return
        nid = (self.hwnd, 0, NIF_INFO, WM_TRAY, self.hicon, self.tooltip,
               message, 5000, title or self.tooltip)
        try:
            win32gui.Shell_NotifyIcon(NIM_MODIFY, nid)
        except Exception as exc:
            if self.logger:
                self.logger.warning("Tray notify failed: %s", exc)

    # ---------- 内部实现 ----------
    def _create_window(self):
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = self._class_name
        wc.lpfnWndProc = self._wnd_proc
        wc.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = win32con.COLOR_WINDOW
        try:
            self._class_atom = win32gui.RegisterClass(wc)
        except win32gui.error:
            # 已注册过（比如同一进程内重复创建）就直接用类名
            self._class_atom = self._class_name

        self.hwnd = win32gui.CreateWindow(
            self._class_atom, "AutoMuteBG", win32con.WS_OVERLAPPED,
            0, 0, 0, 0, 0, 0, wc.hInstance, None)
        if not self.hwnd:
            raise RuntimeError("CreateWindow failed")

        self.hicon = win32gui.LoadImage(
            0, self.icon_path, win32con.IMAGE_ICON, 0, 0,
            win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
        if not self.hicon:
            raise RuntimeError(f"LoadImage failed: {self.icon_path}")

    def _add_icon(self):
        nid = (self.hwnd, 0, NIF_ICON | NIF_MESSAGE | NIF_TIP,
               WM_TRAY, self.hicon, self.tooltip)
        try:
            ok = win32gui.Shell_NotifyIcon(NIM_ADD, nid)
        except Exception as exc:
            ok = False
            if self.logger:
                self.logger.warning("Shell_NotifyIcon NIM_ADD raised: %s", exc)
        if not ok:
            if self.logger:
                self.logger.error("Shell_NotifyIcon NIM_ADD failed: %s", win32api.GetLastError())
                self._log_diagnostics()
        return bool(ok)

    def _log_diagnostics(self):
        """NIM_ADD 失败时记录环境信息，便于定位权限问题。"""
        try:
            pid = os.getpid()
            kernel32 = ctypes.windll.kernel32

            def _session_of(process_id):
                session_id = ctypes.c_ulong()
                ok = kernel32.ProcessIdToSessionId(
                    ctypes.c_ulong(process_id), ctypes.byref(session_id))
                return session_id.value if ok else None

            my_session = _session_of(pid)
            tray_hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
            tray_pid = 0
            tray_session = None
            if tray_hwnd:
                _, tray_pid = win32process.GetWindowThreadProcessId(tray_hwnd)
                tray_session = _session_of(tray_pid)

            integrity = "?"
            try:
                token = win32security.OpenProcessToken(
                    win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
                sid = win32security.GetTokenInformation(
                    token, win32security.TokenIntegrityLevel)[0]
                integrity = win32security.ConvertSidToStringSid(sid)
            except Exception as exc:
                integrity = f"unknown({exc})"

            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            self.logger.error(
                "Tray diagnostics: pid=%s session=%s integrity=%s admin=%s | "
                "Shell_TrayWnd=%s tray_pid=%s tray_session=%s",
                pid, my_session, integrity, is_admin,
                tray_hwnd, tray_pid, tray_session)
        except Exception as exc:
            if self.logger:
                self.logger.error("Tray diagnostics failed: %s", exc)

    def _add_icon_with_retry(self, attempts=5, delay=2):
        for i in range(attempts):
            if self._add_icon():
                return True
            if i < attempts - 1:
                time.sleep(delay)
        if self.logger:
            self.logger.error("Tray icon could not be added after %d attempts", attempts)
        return False

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam in (win32con.WM_RBUTTONUP, win32con.WM_LBUTTONDBLCLK):
                self._show_menu()
            return 0
        if msg == self._taskbar_created:
            self._add_icon()
            return 0
        if msg == win32con.WM_CLOSE:
            win32gui.Shell_NotifyIcon(NIM_DELETE, (hwnd, 0))
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        menu = win32gui.CreatePopupMenu()
        for index, (text, _) in enumerate(self.menu_items):
            win32gui.AppendMenu(menu, win32con.MF_STRING, MENU_ID_BASE + index, text)

        x, y = win32gui.GetCursorPos()
        # 先置前，否则点击空白处菜单不会消失
        win32gui.SetForegroundWindow(self.hwnd)
        cmd = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
            x, y, 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

        if cmd:
            index = cmd - MENU_ID_BASE
            if 0 <= index < len(self.menu_items):
                try:
                    self.menu_items[index][1]()
                except Exception:
                    if self.logger:
                        self.logger.exception("Tray menu callback failed")


@singleton
class StrayUtil:
    @inject
    def __init__(self, config_util: ConfigUtil, logger_util: LoggerUtil, event: threading.Event):
        self.setup_msg = config_util.config["setting"]["setup_msg"]
        self.config_util = config_util
        self.logger = logger_util.logger
        self.event = event

        icon_path = resource_path("resource/mute.ico")
        self.tray = TrayIcon(
            icon_path=icon_path,
            tooltip="后台静音",
            menu_items=[
                ("关于", self.show_version_info),
                ("开源地址", _open_site),
                ("进程列表", self._save_process_list_to_txt),
                ("退出", self.exit_app),
            ],
            logger=self.logger,
        )

    @staticmethod
    def show_version_info():
        version_info = (
            "后台应用自动静音器\n"
            "让设定的进程在后台时自动静音，切换到前台恢复。\n"
            "版本: 0.2.2 Dev\n"
            "开源地址: github.com/stevenghost/APAutoMuteBG"
        )
        win32api.MessageBox(0, version_info, "关于Auto Mute Background", 0x40)

    def run_detached(self):
        def on_ready():
            threading.current_thread().setName("StrayRunCallbackThread")
            if self.setup_msg:
                self.tray.notify("程序启动成功，在系统托盘右键菜单中退出")
            self.logger.info("Stray is running.")

        self.logger.info("Starting stray.")
        threading.Thread(target=self.tray.run, args=(on_ready,), name="StrayThread").start()

    def _save_process_list_to_txt(self):
        filename = "process_name.txt"
        window_processes = get_all_window_processes()
        print(window_processes)
        audio_sessions = get_all_audio_sessions()
        with open(filename, 'w', encoding="utf-8") as file:
            if window_processes:
                file.write("当前在窗口管理器中注册的进程：\n窗口标题 - 进程名\n")
            else:
                file.write("当前在窗口管理器中没有进程，请先启动任意进程并打开窗口。")
            for process_name, window_title in window_processes:
                mark = " [已配置]" if self._is_configured(process_name) else ""
                file.write(f"{window_title} - {process_name}{mark}\n")
            file.write("\n")
            if audio_sessions:
                file.write("当前在音量合成器中注册的进程：\n进程名\n")
            else:
                file.write("当前在音量合成器中没有进程，请先启动任意进程并播放声音。")
            for session in audio_sessions:
                try:
                    process_name = session.Process.name()
                except Exception:
                    continue
                mark = " [已配置]" if self._is_configured(process_name) else ""
                file.write(f"{process_name}{mark}\n")
        self.logger.info(f"Process list saved to {filename}.")
        os.startfile(filename)

    def _is_configured(self, process_name):
        """配置里是否包含该进程名（不区分大小写）。"""
        try:
            configured = {
                str(name).lower()
                for name in self.config_util.config.get("processes", {})
            }
        except Exception:
            return False
        return str(process_name).lower() in configured

    def exit_app(self):
        self.logger.info("Exiting by StrayUtil.")
        VolumeGuard.restore_all(self.logger)
        self.event.set()
        self.tray.stop()










