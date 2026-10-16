# -*- coding: utf-8 -*-
"""
窗口操作（查找 / 置前 / 最小化）
================================

* `list_windows()`：列出当前可见的顶层窗口 → `[(hwnd, 标题, 进程名)]`
  （进程名如 `chrome.exe`，纯粹用 ctypes，不需要装 psutil）。
* `find_window(标题或进程名)`：**包含匹配、不区分大小写**，按
  ①进程名全等 → ②标题包含 → ③进程名包含 的顺序找，返回 hwnd（0 = 没找到）。
* `focus_window(hwnd)`：最小化了就还原，然后 `SetForegroundWindow`；
  被前台锁挡住时用「置顶一下再取消置顶」兜底（不改窗口大小/位置）。
* `minimize_window(hwnd)`：`ShowWindow(SW_MINIMIZE)`。
* 非 Windows（Linux 侧验证）一律返回空/False，不抛异常。
* **只调用窗口 API**：不注入、不发消息给游戏、不改内存。
"""

import ctypes
import os

SW_MINIMIZE = 6
SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

try:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_int
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.IsIconic.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint]
    user32.SetWindowPos.restype = ctypes.c_int
except Exception:                                    # 非 Windows
    user32 = None

# 「枚举窗口」这套单独包一层：万一哪条声明在老系统上不支持，也不会把上面的核心 API 拖死
try:
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_uint32)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_uint32
    # EnumWindows 的 argtypes 故意不设：回调直接传，让 ctypes 自己转指针
    user32.EnumWindows.restype = ctypes.c_int
except Exception:
    pass

try:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                                    ctypes.c_wchar_p,
                                                    ctypes.POINTER(ctypes.c_uint)]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
except Exception:                                    # 非 Windows
    kernel32 = None

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


def available():
    """能不能真的操作窗口。"""
    return user32 is not None


def is_window(hwnd):
    if not available() or not hwnd:
        return False
    try:
        return bool(user32.IsWindow(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def is_minimized(hwnd):
    if not available() or not hwnd:
        return False
    try:
        return bool(user32.IsIconic(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def _proc_name(pid):
    """进程可执行文件名（小写，如 chrome.exe）；拿不到就返回空串。"""
    if kernel32 is None or not pid:
        return ""
    h = None
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return ""
        size = ctypes.c_uint(260)
        buf = ctypes.create_unicode_buffer(260)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value or "").lower()
    except Exception:
        return ""
    finally:
        if h:
            try:
                kernel32.CloseHandle(h)
            except Exception:
                pass


def list_windows():
    """当前可见的顶层窗口：[(hwnd, 标题, 进程名)]（进程名可能为空串）。"""
    if not available():
        return []
    out = []
    try:
        cbtype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                n = int(user32.GetWindowTextLengthW(hwnd))
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = (buf.value or "").strip()
                if not title:
                    return True
                pid = ctypes.c_uint32(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((int(hwnd), title, _proc_name(pid.value)))
            except Exception:
                pass
            return True

        user32.EnumWindows(cbtype(_cb), 0)
    except Exception as e:
        log("⚠ 枚举窗口失败：%r" % (e,))
    return out


def find_window(target):
    """按标题/进程名找窗口（包含匹配，不区分大小写）。返回 hwnd；找不到返回 0。"""
    t = str(target or "").strip().lower()
    if not t:
        return 0
    t_proc = t if t.endswith(".exe") else t + ".exe"
    wins = list_windows()
    for hwnd, _title, proc in wins:                  # ① 进程名全等（最稳）
        if proc and proc == t_proc:
            return hwnd
    for hwnd, title, _proc in wins:                  # ② 标题包含
        if t in (title or "").lower():
            return hwnd
    for hwnd, _title, proc in wins:                  # ③ 进程名包含
        if proc and t in proc:
            return hwnd
    return 0


def focus_window(hwnd):
    """切到游戏界面（最小化则先还原）。返回是否执行成功。"""
    if not available() or not hwnd:
        return False
    h = ctypes.c_void_p(int(hwnd))
    try:
        if user32.IsIconic(h):
            user32.ShowWindow(h, SW_RESTORE)
        ok = bool(user32.SetForegroundWindow(h))
        if not ok:                                   # 前台锁兜底
            user32.SetWindowPos(h, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetWindowPos(h, ctypes.c_void_p(HWND_NOTOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            ok = True
        return ok
    except Exception as e:
        log("⚠ 切换到游戏界面失败：%r" % (e,))
        return False


def minimize_window(hwnd):
    """把游戏最小化。返回是否执行成功。"""
    if not available() or not hwnd:
        return False
    try:
        user32.ShowWindow(ctypes.c_void_p(int(hwnd)), SW_MINIMIZE)
        return True
    except Exception as e:
        log("⚠ 游戏最小化失败：%r" % (e,))
        return False
