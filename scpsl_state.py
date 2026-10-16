# -*- coding: utf-8 -*-
"""
SCPSL 玩家状态判定核心（v7 算法｜纯判定：无界面、无音频动作）
=============================================================

对外只暴露三件事：

* `det.state`            —— 当前判定：`"alive"` / `"dead"`
* `on_change(...)`       —— **状态切换**时回调 `(state, reason, detail)`
* `on_death_seen(...)`   —— **每次读到死亡行**时回调 `(reason, detail)`
  （即使状态本来就是"死亡"也会回调一次；用于"第一次死亡也能触发动作"）

判定规则（v7：纯映射 + 尾跳例外）
---------------------------------
* **死亡**：`Player.log` 出现 `you died`（大小写不敏感）
* **存活**：SCPSL 窗口收到 `HSHELL_REDRAW`（游戏"请求注意"）
* 只吞**死亡那一对的尾跳**（每次死亡最多吞一跳），两种识别方式：

  1. **已知 A**（死亡行前 0.45s 内有过跳）：这一跳与 A 的间隔在 **0.28~0.75s** → 尾跳
     （实测 0.323 / 0.518 / 0.520 / 0.529 / 0.533 / 0.546）；
     间隔不在此范围 → 复活 → 立刻判存活（实测 0.18s 那一跳）。
  2. **未知 A**（这次死亡只发了尾跳）：这一跳落在死亡行后 **0.20~0.70s** → 尾跳
     （实测 0.32~0.51）。

安全性
------
* **只读**：读日志 + 监听**自己注册**的 Shell 钩子（自建隐藏窗口）。
* **不注入游戏、不挂钩游戏、不读游戏内存、不碰键盘。**
* 不装键盘钩子（本文件不涉及任何按键）。

线程模型
--------
* `start()` 起两个后台线程：`Player.log` 轮询 + Shell 钩子消息循环。
* 回调在**这些线程**里触发，且**不持有内部锁**（回调里可以随便调用本类的方法）。
"""

import csv
import ctypes
import os
import threading
import time
from ctypes import wintypes
from datetime import datetime

# ----------------------------- 配置 -----------------------------

LOG_POLL = 0.2                  # Player.log 轮询间隔（秒）

# ---- 尾跳判据（全部来自实测，见文件头）----
TAIL_MIN_GAP = 0.28             # 与 A 的间隔下限（实测最小 0.323）
TAIL_MAX_GAP = 0.75             # 上限
TAIL_MIN_AFTER = 0.20           # A 未知时的兜底：距死亡行下限
TAIL_MAX_AFTER = 0.70           # 上限（实测尾跳落在 0.32~0.51s）
A_LOOKBACK_S = 0.45             # 死亡行之前这么久内的最后一跳，算"死亡对第一跳 A"

STATE_ALIVE, STATE_DEAD = "alive", "dead"
PROCESS_KEYWORD = "scpsl"       # 进程名含它就算 SCPSL（大小写不敏感）

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_LOG = os.path.join(APP_DIR, "state_log.csv")

USERPROFILE = os.environ.get("USERPROFILE", "")
PLAYER_LOG = os.path.join(
    USERPROFILE, "AppData", "LocalLow", "Northwood", "SCPSL", "Player.log"
)

# ----------------------------- 日志 -----------------------------

_logger = print


def set_logger(fn):
    """让宿主程序接管日志输出（默认 print）。"""
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


def now_ms():
    return int(time.time() * 1000)


# ----------------------------- Win32 -----------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

try:                                            # 进程名优先用 psutil，拿不到就退回 Win32
    import psutil
except ImportError:
    psutil = None


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

HSHELL_REDRAW = 0x0006


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# 显式声明参数类型：64 位下句柄若按默认 c_int 传会被截断（踩过这个坑）
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND,
    wintypes.UINT, wintypes.UINT, wintypes.UINT,
]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_ssize_t

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.WORD
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.RegisterShellHookWindow.argtypes = [wintypes.HWND]
user32.RegisterShellHookWindow.restype = wintypes.BOOL
user32.DeregisterShellHookWindow.argtypes = [wintypes.HWND]
user32.DeregisterShellHookWindow.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL


# ----------------------------- 窗口小工具 -----------------------------

_proc_cache = {}


def proc_name(pid):
    """按 pid 取进程名（带缓存）。"""
    if pid in _proc_cache:
        return _proc_cache[pid]
    name = ""
    if psutil is not None and pid:
        try:
            name = psutil.Process(pid).name()
        except Exception:
            name = ""
    if not name and pid:
        try:
            h = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
            if h:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value)
                kernel32.CloseHandle(h)
        except Exception:
            pass
    _proc_cache[pid] = name
    return name


def get_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def pid_of(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def enum_windows():
    out = []

    def cb(hwnd, lparam):
        out.append(int(hwnd))
        return True

    cb_ref = ENUMPROC(cb)
    user32.EnumWindows(cb_ref, 0)
    return out


def find_scpsl_windows():
    """返回所有属于 SCPSL 进程的窗口（按可见面积从大到小）。"""
    found = []
    for hwnd in enum_windows():
        pid = pid_of(hwnd)
        if not pid or PROCESS_KEYWORD not in proc_name(pid).lower():
            continue
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
        found.append(
            {
                "hwnd": hwnd,
                "pid": pid,
                "title": get_title(hwnd),
                "cls": get_class(hwnd),
                "rect": [r.left, r.top, r.right, r.bottom],
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "area": area,
            }
        )
    found.sort(key=lambda x: (x["visible"], x["area"]), reverse=True)
    return found


def is_game_window(hwnd):
    """这个句柄**现在**还是不是 SCPSL 的窗口？

    句柄会被系统回收后再发给别的程序，所以**用之前必须现验** ——
    不能把上次锁定的 hwnd 当长期凭据（游戏重启、句柄回收都会变）。
    """
    if not hwnd:
        return False
    try:
        return PROCESS_KEYWORD in proc_name(pid_of(int(hwnd))).lower()
    except Exception:
        return False


# ----------------------------- 判定核心 -----------------------------


class Detector:
    """状态机：日志死亡行 = 死亡；REDRAW = 存活（只吞死亡对的尾跳）。

    参数
    ----
    on_change     : 状态**切换**时的回调 `(state, reason, detail)`
    on_death_seen : 每次读到死亡行时的回调 `(reason, detail)`（状态未必变化）
    on_note       : 每条"不改状态"的观察（每次 REDRAW 的判定）回调 `(reason, detail)`
    """

    def __init__(self, on_change=None, on_death_seen=None, on_note=None):
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.state = STATE_DEAD          # 默认：死亡 / 观察者（启动时并不知道真实状态）
        self.t_death = 0.0               # 最近一次死亡时刻（monotonic）
        self.last_redraw_t = None        # 上一个 REDRAW 时刻
        self.pre_log_jump_t = None       # 死亡行之前那最后一跳（死亡对第一跳 A）
        self.tail_pending = False        # 是否还在等死亡对的尾跳
        self.scpsl_hwnd = 0
        self.counts = {"death": 0, "alive": 0, "redraw": 0}

        self.on_change = on_change
        self.on_death_seen = on_death_seen
        self.on_note = on_note

        self._last_log_pos = self._log_size()
        self._f_log = self._csv = None
        self._open_state_log()

    # ---------- 落盘 ----------

    def _open_state_log(self):
        new = not os.path.exists(STATE_LOG)
        try:
            self._f_log = open(STATE_LOG, "a", newline="", encoding="utf-8")
            self._csv = csv.writer(self._f_log)
            if new:
                self._csv.writerow(["time", "ts_ms", "state", "reason", "detail"])
                self._f_log.flush()
        except Exception as e:
            self._f_log = self._csv = None
            log("⚠ 状态日志无法写入: %r" % (e,))

    def _record(self, state, reason, detail="", mark="→"):
        text = "存活" if state == STATE_ALIVE else "死亡·观察者"
        log("[state] %s %-10s (%s%s)" % (mark, text, reason, (" | " + detail) if detail else ""))
        if self._csv:
            try:
                self._csv.writerow([
                    datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    now_ms(), state, reason, detail,
                ])
                self._f_log.flush()
            except Exception as e:              # 不静默吞：写不进去要看得见
                self._csv = None
                log("⚠ 状态日志写入失败（后续只打控制台）: %r" % (e,))

    def _note(self, reason, detail=""):
        """记录一条"不改状态"的观察（每次 REDRAW 的判定）。"""
        with self.lock:
            self._record(self.state, reason, detail, mark="·")
        self._safe(self.on_note, reason, detail)

    # ---------- 回调 ----------

    @staticmethod
    def _safe(fn, *args):
        """回调在锁外执行，且异常不外溢（否则会打断监听线程）。"""
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as e:
            log("⚠ 回调出错: %r" % (e,))

    # ---------- 状态切换 ----------

    def _set_state(self, state, reason, detail=""):
        with self.lock:
            changed = state != self.state
            self.state = state
            self.counts["alive" if state == STATE_ALIVE else "death"] += 1
            self._record(state, reason, detail)
        if changed:
            self._safe(self.on_change, state, reason, detail)
        return changed

    # ---------- 事件 ----------

    def on_death(self, line):
        """Player.log 里出现死亡行 → 判死亡，并尽量锁定"死亡对第一跳 A"。"""
        now = time.monotonic()
        with self.lock:
            self.t_death = now
            last = self.last_redraw_t
            # 死亡行之前 0.45s 内的最后一跳 = 死亡那一对的第一跳 A（实测早 0.03~0.20s）
            self.pre_log_jump_t = last if (last is not None and now - last <= A_LOOKBACK_S) else None
            self.tail_pending = True
            a = self.pre_log_jump_t
        self._set_state(STATE_DEAD, "日志死亡行", line)
        if a is None:
            log("        死亡行前 %.2fs 内没有跳（这次没看到 A）→ 兜底：死亡行后 %.2f~%.2fs 内的第一跳算尾跳"
                % (A_LOOKBACK_S, TAIL_MIN_AFTER, TAIL_MAX_AFTER))
        else:
            log("        已锁定死亡对第一跳 A（%.3fs 前）：与 A 相隔 %.2f~%.2fs 的那一跳才算尾跳"
                % (now - a, TAIL_MIN_GAP, TAIL_MAX_GAP))
        # 即使状态本来就是"死亡"（例如启动后第一次死亡），也要通知宿主
        self._safe(self.on_death_seen, "日志死亡行", line)

    def _tail_hit(self, now, a, t_death):
        """这一跳是不是死亡那一对的尾跳？是则返回说明文字，否则 None。"""
        if a is not None:
            gap = now - a
            if TAIL_MIN_GAP <= gap <= TAIL_MAX_GAP:
                return "距死亡第一跳 %.2fs" % gap
            return None
        after = now - t_death
        if TAIL_MIN_AFTER <= after <= TAIL_MAX_AFTER:
            return "死亡行前没看到跳，且这一跳落在死亡行后 %.2fs" % after
        return None

    def on_redraw(self, hwnd):
        """SCPSL 窗口收到 HSHELL_REDRAW → 判存活；只吞死亡那一对的尾跳。

        顺带**自愈**：红跳来自另一个游戏窗口（游戏重启过）→ 把锁定改到新句柄，
        免得窗口操作一直打在一个已经死掉的句柄上。
        """
        if hwnd != self.scpsl_hwnd:
            if not is_game_window(hwnd):
                return                                   # 别的窗口，忽略
            with self.lock:
                old = self.scpsl_hwnd
                self.scpsl_hwnd = hwnd
            log("已重新锁定 SCPSL 窗口 hwnd=%d (%s)（旧 hwnd=%d 已失效）"
                % (hwnd, get_title(hwnd) or "无标题", old))
        now = time.monotonic()
        with self.lock:
            self.counts["redraw"] += 1
            prev = self.last_redraw_t
            self.last_redraw_t = now
            t_death = self.t_death
            state = self.state
            a = self.pre_log_jump_t
            tail_pending = self.tail_pending

        gap_txt = "孤立一跳" if prev is None else "与上一跳相隔 %.2fs" % (now - prev)
        log("REDRAW  hwnd=%d  %s  距死亡行 %.2fs" % (hwnd, gap_txt, now - t_death))

        if state != STATE_DEAD:
            log("        （已经是存活，不改状态）")
            self._note("REDRAW｜已经是存活，不改状态", gap_txt)
            return
        why = self._tail_hit(now, a, t_death) if tail_pending else None
        if why:
            with self.lock:
                self.tail_pending = False
            log("        （死亡对的尾跳：%s，吞掉，不改状态）" % why)
            self._note("REDRAW｜死亡对的尾跳，吞掉", "%s（%s）" % (gap_txt, why))
            return
        with self.lock:
            self.tail_pending = False
        if a is not None:
            detail = "%s；距死亡第一跳 %.2fs → 不像尾跳，按复活处理" % (gap_txt, now - a)
        else:
            detail = "%s；死亡行前没有跳，且不落在尾跳档（%.2f~%.2fs）→ 按复活处理" % (
                gap_txt, TAIL_MIN_AFTER, TAIL_MAX_AFTER)
        self._set_state(STATE_ALIVE, "REDRAW 判存活",
                        "%s，距死亡行 %.2fs" % (detail, now - t_death))

    # ---------- Player.log 实时监听 ----------

    def _log_size(self):
        try:
            return os.path.getsize(PLAYER_LOG)
        except OSError:
            return 0

    def log_watch_loop(self):
        pos = self._last_log_pos
        pending = b""
        if not os.path.exists(PLAYER_LOG):
            log("⚠ 找不到 Player.log：%s（死亡检测将不可用）" % PLAYER_LOG)
        missing_warned = False
        while not self.stop.is_set():
            try:
                size = os.path.getsize(PLAYER_LOG)
                if size < pos:                      # 日志被轮转 / 清空
                    pos, pending = 0, b""
                if size > pos:
                    with open(PLAYER_LOG, "rb") as f:
                        f.seek(pos)
                        chunk = f.read(size - pos)
                    pos = size
                    data = pending + chunk
                    parts = data.split(b"\n")
                    pending = parts.pop() if not data.endswith(b"\n") else b""
                    for raw in parts:
                        line = raw.decode("utf-8", "replace").rstrip("\r")
                        if "you died" in line.lower():      # 两种前缀都只认这一句
                            self.on_death(line)
            except FileNotFoundError:
                if not missing_warned:
                    missing_warned = True
                    log("⚠ Player.log 暂时不存在（等游戏写入）")
            except Exception as e:
                log("日志监听出错: %r" % (e,))
            time.sleep(LOG_POLL)

    # ---------- Shell 钩子（自建隐藏窗口，只读） ----------

    def _find_scpsl(self):
        """现查游戏窗口并记录；查不到就记 0（**不保留过期句柄**）。返回句柄是否变了。"""
        wins = find_scpsl_windows()
        hwnd = int(wins[0]["hwnd"]) if wins else 0
        changed = hwnd != self.scpsl_hwnd
        self.scpsl_hwnd = hwnd
        return changed

    def _log_lock(self, rescan=False):
        """锁定 / 重锁窗口都写一行日志（以前重锁成功是静默的，出问题难查）。"""
        if self.scpsl_hwnd:
            log("已%s锁定 SCPSL 窗口 hwnd=%d (%s)"
                % ("重新" if rescan else "", self.scpsl_hwnd,
                   get_title(self.scpsl_hwnd) or "无标题"))
        elif rescan:
            log("SCPSL 窗口已失效（游戏关了？等它回来）")
        else:
            log("还没找到 SCPSL 窗口（游戏没开？找到后自动锁定）")

    def shell_hook_loop(self):
        try:
            shell_msg = user32.RegisterWindowMessageW("SHELLHOOK")
        except Exception as e:
            log("⚠ Shell 钩子不可用(%r)：复活检测将失效" % (e,))
            return
        if not shell_msg:
            log("⚠ Shell 钩子不可用：复活检测将失效")
            return

        hinst = kernel32.GetModuleHandleW(None)
        cls_name = "ScpslAutoPlayerHook"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == shell_msg and (int(wparam) & 0xFFFF) == HSHELL_REDRAW:
                try:
                    self.on_redraw(int(lparam or 0))
                except Exception as e:
                    log("处理 REDRAW 出错: %r" % (e,))
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wndproc)        # 必须保活，否则回调被回收
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        self._wc_ref = wc
        user32.RegisterClassW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(
            0, cls_name, "scpsl auto player hook", 0, 0, 0, 0, 0, None, None, hinst, None
        )
        if not hwnd or not user32.RegisterShellHookWindow(hwnd):
            log("⚠ Shell 钩子注册失败：复活检测将失效")
            return
        self._find_scpsl()
        self._log_lock()
        log("Shell 钩子已就绪（复活检测生效）")

        msg = wintypes.MSG()
        last_find = time.monotonic()
        while not self.stop.is_set():
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.02)
                # 1s 查一次：没锁定、或锁定的句柄已失效（游戏重启/退出）→ 重找
                if time.monotonic() - last_find >= 1.0:
                    last_find = time.monotonic()
                    if not is_game_window(self.scpsl_hwnd) and self._find_scpsl():
                        self._log_lock(rescan=True)
        try:
            user32.DeregisterShellHookWindow(hwnd)
            user32.DestroyWindow(hwnd)
        except Exception:
            pass

    # ---------- 生命周期 ----------

    def start(self):
        threading.Thread(target=self.log_watch_loop, daemon=True, name="logwatch").start()
        threading.Thread(target=self.shell_hook_loop, daemon=True, name="shellhook").start()

    def stop_all(self):
        self.stop.set()
