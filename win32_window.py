# -*- coding: utf-8 -*-
"""
窗口操作（查找 / 置前 / 最小化）
================================

* `list_windows()`：列出当前可见的顶层窗口 → `[(hwnd, 标题, 进程名)]`
  （进程名如 `chrome.exe`，纯粹用 ctypes，不需要装 psutil）。
* `find_window(标题或进程名)`：**包含匹配、不区分大小写**，按
  ①进程名全等 → ②标题包含 → ③进程名包含 的顺序找，返回 hwnd（0 = 没找到）。
* `find_game_window()` / `is_game_window(hwnd)`：游戏窗口**现查现验**（进程名含 `scpsl`）。
  句柄会被系统回收再发给别的程序，所以**用之前必须现验**，不能存着当长期凭据。
* `focus_window(hwnd)`：最小化了就还原，然后 `SetForegroundWindow`；
  被前台锁挡住时用「置顶一下再取消置顶」兜底（不改窗口大小/位置）。
  **执行后复核**：认**同进程**的窗口、并给几次机会（`SetForegroundWindow` 是异步的，
  游戏到前台的句柄未必就是我们操作的那个 —— 都是实测出来的宽容）。
* `minimize_window(hwnd)`：`ShowWindow(SW_MINIMIZE)`，**执行后复核**（`IsIconic`，同样给几次机会）；没生效返回 False。
* 非 Windows（Linux 侧验证）一律返回空/False，不抛异常。
* **只调用窗口 API**：不注入、不发消息给游戏、不改内存。
"""

import ctypes
import os
import time

SW_MINIMIZE = 6
SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GAME_KEYWORD = "scpsl"                               # 进程名含它就认作游戏窗口


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

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
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
    user32.GetWindowRect.restype = ctypes.c_int
    user32.GetForegroundWindow.restype = ctypes.c_void_p
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


def pid_of(hwnd):
    """hwnd 所属进程的 pid（拿不到返回 0）。"""
    if not available() or not hwnd:
        return 0
    try:
        pid = ctypes.c_uint32(0)
        user32.GetWindowThreadProcessId(ctypes.c_void_p(int(hwnd)), ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def proc_name_of(hwnd):
    """hwnd 所属进程的可执行文件名（小写；拿不到返回空串）。"""
    return _proc_name(pid_of(hwnd))


def foreground_is(hwnd, tries=5, gap=0.03):
    """前台是不是这个窗口（**或者同一个进程的窗口**）？

    两点宽容，都是实测出来的：
    ① `SetForegroundWindow` 是**异步**的 —— 返回时系统可能还没换完，所以要给它几次机会；
    ② 游戏（Unity）到前台的那个句柄，未必就是我们找/操作的那个句柄 ——
       所以只要**同进程**的窗口在前台就算数，免得真成功了还报失败。
    """
    if not available() or not hwnd:
        return False
    hwnd = int(hwnd)
    pid = pid_of(hwnd)
    for i in range(tries):
        fg = int(user32.GetForegroundWindow() or 0)
        if fg == hwnd or (fg and pid and pid_of(fg) == pid):
            return True
        if i < tries - 1:
            time.sleep(gap)
    return False


def window_area(hwnd):
    """窗口面积（多个候选里挑主窗口用）；拿不到返回 0。"""
    if not available() or not hwnd:
        return 0
    try:
        r = _RECT()
        if not user32.GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(r)):
            return 0
        return max(0, r.right - r.left) * max(0, r.bottom - r.top)
    except Exception:
        return 0


def is_game_window(hwnd, keyword=GAME_KEYWORD):
    """这个句柄**现在**还是不是游戏窗口？

    句柄会被系统回收后发给别的程序，所以**每次用之前都要现验**，
    不能把上次找到的 hwnd 当长期凭据（否则会去操作别人的窗口）。
    """
    if not is_window(hwnd):
        return False
    return keyword.lower() in proc_name_of(hwnd).lower()


def find_game_window(keyword=GAME_KEYWORD):
    """**现查**游戏窗口：进程名含 keyword 的可见顶层窗口。

    有多个时挑「没被最小化 + 面积最大」的那个（游戏的主窗口）。
    返回 hwnd；没找到返回 0 —— **绝不返回过期句柄**。
    """
    if not available():
        return 0
    kw = keyword.lower()
    cands = [hwnd for hwnd, _title, proc in list_windows() if kw in (proc or "").lower()]
    if not cands:
        return 0
    if len(cands) == 1:
        return cands[0]
    return max(cands, key=lambda h: (0 if is_minimized(h) else 1, window_area(h)))


def focus_window(hwnd):
    """切到游戏界面（最小化则先还原）。**执行后复核**是否真的到了前台。"""
    if not available() or not hwnd or not is_window(hwnd):
        return False
    h = ctypes.c_void_p(int(hwnd))
    try:
        if user32.IsIconic(h):
            user32.ShowWindow(h, SW_RESTORE)
        if not user32.SetForegroundWindow(h):         # 前台锁兜底：置顶一下再取消置顶
            user32.SetWindowPos(h, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.SetWindowPos(h, ctypes.c_void_p(HWND_NOTOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        if foreground_is(hwnd):
            return True
        log("⚠ 切前台没成功（窗口没到前台）")
        return False
    except Exception as e:
        log("⚠ 切换到游戏界面失败：%r" % (e,))
        return False


def minimize_window(hwnd):
    """把窗口最小化。**执行后复核**（IsIconic）；没真生效就返回 False（不谎报）。"""
    if not available() or not hwnd:
        return False
    h = ctypes.c_void_p(int(hwnd))
    try:
        user32.ShowWindow(h, SW_MINIMIZE)
        for i in range(3):                            # 最小化也是异步的，给几次机会再判失败
            if user32.IsIconic(h):
                return True
            if i < 2:
                time.sleep(0.03)
        log("⚠ 最小化没生效（句柄可能已失效）")
        return False
    except Exception as e:
        log("⚠ 游戏最小化失败：%r" % (e,))
        return False
