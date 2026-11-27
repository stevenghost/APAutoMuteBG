import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np
import psutil
import win32api
import win32con
import win32gui
import win32process
import win32ui
from injector import singleton, inject

from utils.ConfigUtil import ConfigUtil
from utils.PathUtil import resource_path
from utils.LoggerUtil import LoggerUtil

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def _send_left_click():
    """用 SendInput 发送一次左键按下/抬起（比 mouse_event 兼容性更好）。"""
    down = _INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)))
    up = _INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=_MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)))
    inputs = (_INPUT * 2)(down, up)
    ctypes.windll.user32.SendInput(2, inputs, ctypes.sizeof(_INPUT))


# 默认参数（可被 config.yaml 的 auto_click 段覆盖）
DEFAULTS = {
    "enabled": True,
    "process": "AzurPromilia.exe",
    "interval": 0.1,          # 检测间隔（秒）
    "click_interval": 0.1,    # 命中后连点间隔（秒）
    "threshold": 0.75,        # NCC 阈值
    "center_x": 2408,         # 按钮中心（2560x1440 客户区坐标）
    "center_y": 61,
    "search": 3,              # 匹配时的滑动半径（像素）
    "max_click_seconds": 30,  # 单轮连点最长时间；按钮一直不消失就放弃本轮
    "stop_misses": 6,         # 连续多少次检测不到才算"按钮消失"（0.1s/次 ≈ 0.6s）
    "cooldown": 0.2,          # 一轮连点结束后的冷却（秒）
    "max_blue_shift": 25,     # 字形亮像素的 B-R 均值超过它判为蓝色光效，不算按钮
    "overlay_x": 1720,        # 遮罩上「跳过剧情」按钮中心
    "overlay_y": 1078,
    "overlay_threshold": 0.65,
    "overlay_search": 4,
    "overlay_max_seconds": 5,  # 遮罩连点最长时间
    "overlay_stop_misses": 10, # 遮罩连续多少次检测不到才算消失（0.1s/次 ≈ 1s）
    "overlay_click_interval": 0.1,
    "overlay_marker_threshold": 0.70,  # 「继续观看」按钮作为遮罩存在的判据
    "overlay_marker_x": 850,           # 「继续观看」按钮中心
    "overlay_marker_y": 1055,
}


@singleton
class AutoClickUtil:
    """检测 AzurPromilia 剧情界面的「>>」按钮并连点。

    实现要点：
    - 只在游戏窗口位于前台时工作；
    - 每 interval 秒抓取按钮周围的小区域（窗口 DC + BitBlt），
      用圆形掩码的归一化互相关（NCC）判断按钮是否存在；
    - 命中后每 click_interval 秒点一次，直到检测不到按钮为止；
    - 不依赖 OpenCV/Pillow，运行时只多做一次 74x74 的灰度匹配。
    """

    @inject
    def __init__(self, config_util: ConfigUtil, logger_util: LoggerUtil,
                 event: threading.Event):
        self.logger = logger_util.logger
        self.event = event

        cfg = dict(DEFAULTS)
        cfg.update(config_util.config.get("auto_click") or {})
        self.enabled = bool(cfg["enabled"])
        self.process_name = cfg["process"]
        self.interval = float(cfg["interval"])
        self.click_interval = float(cfg["click_interval"])
        self.threshold = float(cfg["threshold"])
        self.center_x = int(cfg["center_x"])
        self.center_y = int(cfg["center_y"])
        self.search = int(cfg["search"])
        self.max_click_seconds = float(cfg["max_click_seconds"])
        self.stop_misses = max(1, int(cfg["stop_misses"]))
        self.cooldown = float(cfg["cooldown"])
        self.max_blue_shift = float(cfg["max_blue_shift"])
        self.overlay_x = int(cfg["overlay_x"])
        self.overlay_y = int(cfg["overlay_y"])
        self.overlay_threshold = float(cfg["overlay_threshold"])
        self.overlay_search = int(cfg["overlay_search"])
        self.overlay_max_seconds = float(cfg["overlay_max_seconds"])
        self.overlay_stop_misses = max(1, int(cfg["overlay_stop_misses"]))
        self.overlay_click_interval = float(cfg["overlay_click_interval"])

        self.template = self._load_template()
        self.overlay_template = self._load_overlay_template()
        self.overlay_marker = self._load_overlay_marker()
        self.overlay_marker_threshold = float(cfg["overlay_marker_threshold"])
        self.overlay_marker_x = int(cfg["overlay_marker_x"])
        self.overlay_marker_y = int(cfg["overlay_marker_y"])
        self.mask = self._build_mask(self.template.shape[0])
        self._hwnd = None
        self._last_score = 0.0
        self._last_near_log = 0.0
        self._last_blue = 0.0
        self._last_color_log = 0.0
        self._last_overlay_score = 0.0
        self._click_pos_logged = False

    # ---------- 初始化 ----------
    @staticmethod
    def _load_template():
        path = resource_path("resource/azur_skip.npy")
        return np.load(path).astype(np.float32)

    @staticmethod
    def _load_overlay_template():
        path = resource_path("resource/azur_skip_story.npy")
        return np.load(path).astype(np.float32)

    @staticmethod
    def _load_overlay_marker():
        path = resource_path("resource/azur_overlay_marker.npy")
        return np.load(path).astype(np.float32)

    @staticmethod
    def _build_mask(size):
        radius = size // 2 - 2
        yy, xx = np.mgrid[0:size, 0:size]
        cy = cx = (size - 1) / 2.0
        return ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius ** 2

    # ---------- 主循环 ----------
    def run(self):
        if not self.enabled:
            self.logger.info("AutoClick disabled.")
            return
        self.logger.info(
            "AutoClick started: process=%s interval=%.2fs click=%.2fs threshold=%.2f",
            self.process_name, self.interval, self.click_interval, self.threshold)

        while not self.event.is_set():
            try:
                hwnd = self._find_window()
                if hwnd and self._is_foreground(hwnd):
                    present = self._button_present(hwnd)
                    self._log_near_miss(present)
                    if present:
                        self.logger.info(
                            "Skip button detected (score=%.3f, blue=%.0f), clicking.",
                            self._last_score, self._last_blue)
                        self._click_until_gone(hwnd)
                        self._handle_overlay(hwnd)
                        time.sleep(self.cooldown)
            except Exception as exc:
                self.logger.error("AutoClick loop error: %s", exc, exc_info=True)
            time.sleep(self.interval)

    def _log_color_reject(self, score, blue):
        """分数够但颜色偏蓝，按光效处理；限频记录。"""
        now = time.time()
        if now - self._last_color_log < 2.0:
            return
        self._last_color_log = now
        self.logger.info(
            "AutoClick: score=%.3f but blue=%.0f, treated as effect.", score, blue)

    def _log_near_miss(self, present):
        """接近阈值但未命中时，每 2 秒记一次分数，便于排查误判/漏检。"""
        if present:
            return
        if self._last_score < 0.5:
            return
        now = time.time()
        if now - self._last_near_log < 2.0:
            return
        self._last_near_log = now
        self.logger.info("AutoClick: near miss, score=%.3f", self._last_score)

    # ---------- 窗口 ----------
    def _find_window(self):
        if self._hwnd and win32gui.IsWindow(self._hwnd) and win32gui.IsWindowVisible(self._hwnd):
            return self._hwnd

        found = []
        target = self.process_name.lower()
        old_hwnd = self._hwnd

        def _callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                name = psutil.Process(pid).name().lower()
            except Exception:
                return True
            if name == target:
                found.append(hwnd)
                return False
            return True

        try:
            win32gui.EnumWindows(_callback, None)
        except Exception:
            pass
        self._hwnd = found[0] if found else None
        if self._hwnd != old_hwnd:
            if self._hwnd:
                self.logger.info("AutoClick: game window found hwnd=0x%X", self._hwnd)
            elif old_hwnd:
                self.logger.info("AutoClick: game window lost")
        return self._hwnd

    @staticmethod
    def _is_foreground(hwnd):
        fg = win32gui.GetForegroundWindow()
        return fg == hwnd or win32gui.GetAncestor(fg, win32con.GA_ROOT) == hwnd

    # ---------- 截图 ----------
    def _grab_gray(self, hwnd, left, top, width, height):
        # 从"屏幕"抓图而不是窗口 DC：这样能抓到覆盖在游戏窗口之上的
        # 全屏遮罩（剧情梗概等），避免把遮罩下面的旧画面当成按钮。
        sx, sy = win32gui.ClientToScreen(hwnd, (left, top))
        screen_dc = win32gui.GetDC(0)
        mfc_dc = win32ui.CreateDCFromHandle(screen_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bmp)
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (sx, sy), win32con.SRCCOPY)
            bits = bmp.GetBitmapBits(True)
            arr = np.frombuffer(bits, dtype=np.uint8).reshape(height, width, 4)
            # GetBitmapBits 返回 BGRA
            b = arr[:, :, 0].astype(np.float32)
            g = arr[:, :, 1].astype(np.float32)
            r = arr[:, :, 2].astype(np.float32)
            gray = b * 0.114 + g * 0.587 + r * 0.299
            return gray, b, r
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(0, screen_dc)

    # ---------- 匹配 ----------
    def _button_present(self, hwnd):
        size = self.template.shape[0]
        search = self.search
        region = size + 2 * search
        left = self.center_x - region // 2
        top = self.center_y - region // 2

        grabbed = self._grab_gray(hwnd, left, top, region, region)
        if not grabbed:
            return False
        gray, b, r = grabbed
        if float(gray.mean()) < 1.0:
            return False  # 全黑说明没抓到画面

        score, dy, dx = self._ncc(gray)
        self._last_score = score
        if score < self.threshold:
            return False

        # 只统计圆形区域内"字形亮像素"的颜色，背景再蓝也不影响判断
        patch_gray = gray[dy:dy + size, dx:dx + size]
        bright = (patch_gray > 200) & self.mask
        if int(bright.sum()) >= 10:
            patch_diff = (b - r)[dy:dy + size, dx:dx + size]
            blue_shift = float(patch_diff[bright].mean())
        else:
            blue_shift = 0.0
        self._last_blue = blue_shift
        if blue_shift > self.max_blue_shift:
            self._log_color_reject(score, blue_shift)
            return False
        return True

    # ---------- 遮罩（剧情梗概）----------
    def _match_at(self, hwnd, center_x, center_y, tpl, search):
        h, w = tpl.shape
        s = search
        region_w, region_h = w + 2 * s, h + 2 * s
        left = center_x - region_w // 2
        top = center_y - region_h // 2
        grabbed = self._grab_gray(hwnd, left, top, region_w, region_h)
        if not grabbed:
            return -1.0
        gray, _, _ = grabbed
        if float(gray.mean()) < 1.0:
            return -1.0
        return self._ncc_generic(gray, tpl, s)

    def _overlay_present(self, hwnd, search=None):
        s = self.overlay_search if search is None else search
        skip_score = self._match_at(
            hwnd, self.overlay_x, self.overlay_y, self.overlay_template, s)
        if skip_score >= self.overlay_threshold:
            self._last_overlay_score = skip_score
            return True
        marker_score = self._match_at(
            hwnd, self.overlay_marker_x, self.overlay_marker_y,
            self.overlay_marker, s)
        self._last_overlay_score = max(skip_score, marker_score)
        return marker_score >= self.overlay_marker_threshold

    @staticmethod
    def _ncc_generic(region, template, search):
        t = template
        t0 = t - t.mean()
        t_den = np.sqrt(float((t0 * t0).sum()))
        if t_den <= 0:
            return 0.0
        h, w = t.shape
        best = -1.0
        for dy in range(0, 2 * search + 1):
            for dx in range(0, 2 * search + 1):
                p = region[dy:dy + h, dx:dx + w]
                p0 = p - p.mean()
                den = np.sqrt(float((p0 * p0).sum())) * t_den
                if den <= 0:
                    continue
                score = float((p0 * t0).sum()) / den
                if score > best:
                    best = score
        return best

    def _handle_overlay(self, hwnd):
        """遮罩出现后持续点「跳过剧情」，直到遮罩消失。"""
        appeared = False
        for _ in range(10):
            if self.event.is_set():
                return False
            if self._overlay_present(hwnd):
                appeared = True
                break
            time.sleep(0.1)
        if not appeared:
            return False

        self.logger.info("Overlay detected, clicking skip-story until gone.")
        clicks = 0
        misses = 0
        start = time.time()
        while not self.event.is_set():
            if not win32gui.IsWindow(hwnd) or not self._is_foreground(hwnd):
                return True
            if not self._overlay_present(hwnd):
                misses += 1
                if misses >= self.overlay_stop_misses:
                    self.logger.info(
                        "Overlay gone after %d clicks (score=%.3f).",
                        clicks, self._last_overlay_score)
                    return True
            else:
                misses = 0
                elapsed = time.time() - start
                if elapsed > self.overlay_max_seconds:
                    self.logger.warning(
                        "Overlay still detected after %.1fs (%d clicks, score=%.3f), give up.",
                        elapsed, clicks, self._last_overlay_score)
                    return True
                self._click(hwnd, self.overlay_x, self.overlay_y)
                clicks += 1
            time.sleep(self.overlay_click_interval)
        return True

    def _ncc(self, region):
        """向量化的归一化互相关，返回 (best_score, dy, dx)。"""
        template = self.template
        mask = self.mask
        size = template.shape[0]
        s = self.search

        t0 = (template - template[mask].mean()) * mask
        t_den = float(np.sqrt((t0 * t0).sum()))
        if t_den <= 0:
            return 0.0, 0, 0

        windows = np.lib.stride_tricks.sliding_window_view(region, (size, size))
        windows = windows[:2 * s + 1, :2 * s + 1]
        p0 = windows - windows.mean(axis=(2, 3), keepdims=True)
        num = (p0 * t0).sum(axis=(2, 3))
        p_den = np.sqrt((p0 * p0 * mask).sum(axis=(2, 3))) * t_den
        scores = np.divide(num, p_den, out=np.full_like(num, -1.0), where=p_den > 0)
        idx = int(np.argmax(scores))
        dy, dx = divmod(idx, scores.shape[1])
        return float(scores[dy, dx]), dy, dx

    def _click(self, hwnd, x, y):
        sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
        if not self._click_pos_logged:
            self.logger.info(
                "AutoClick target: client=(%d,%d) screen=(%d,%d)", x, y, sx, sy)
            self._click_pos_logged = True
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        win32api.SetCursorPos((sx, sy))
        time.sleep(0.02)          # 等光标真正到位
        _send_left_click()

    def _click_message(self, hwnd, x, y):
        """备用方案：直接向鼠标下的窗口投递 WM_LBUTTONDOWN/UP。"""
        sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
        target = win32gui.WindowFromPoint((sx, sy)) or hwnd
        cx, cy = win32gui.ScreenToClient(target, (sx, sy))
        lparam = win32api.MAKELONG(cx, cy)
        win32gui.PostMessage(target, win32con.WM_MOUSEMOVE, 0, lparam)
        win32gui.PostMessage(target, win32con.WM_LBUTTONDOWN,
                             win32con.MK_LBUTTON, lparam)
        time.sleep(0.05)
        win32gui.PostMessage(target, win32con.WM_LBUTTONUP, 0, lparam)

    def _click_until_gone(self, hwnd):
        old_pos = win32api.GetCursorPos()
        clicks = 0
        misses = 0
        start = time.time()
        try:
            while not self.event.is_set():
                if not win32gui.IsWindow(hwnd) or not self._is_foreground(hwnd):
                    return
                if self._overlay_present(hwnd, 0):
                    self.logger.info("Overlay appeared, stop clicking skip button.")
                    return
                if not self._button_present(hwnd):
                    misses += 1
                    if misses >= self.stop_misses:
                        self.logger.info(
                            "Skip button gone (score=%.3f), stop after %d clicks.",
                            self._last_score, clicks)
                        return
                else:
                    misses = 0
                    elapsed = time.time() - start
                    if self.max_click_seconds and elapsed > self.max_click_seconds:
                        self.logger.warning(
                            "Skip button still detected after %.1fs (%d clicks, score=%.3f), "
                            "give up this burst.", elapsed, clicks, self._last_score)
                        return
                    self._click(hwnd, self.center_x, self.center_y)
                    clicks += 1
                time.sleep(self.click_interval)
        finally:
            try:
                win32api.SetCursorPos(old_pos)
            except Exception:
                pass









