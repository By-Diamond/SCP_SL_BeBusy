# -*- coding: utf-8 -*-
"""
模拟按键（无界面）：把「Ctrl+D」「F12」「Shift+Alt+→」变成真实的按下 / 松开
==========================================================================

* 用 Windows 的 `SendInput` 发**真实按键事件**（和真人敲键盘走同一条路）——
  它会进到**当时最前面的那个窗口**。所以想发进游戏，就用列表顺序先把游戏切到前台
  （例如：「切换到游戏界面」→「模拟按键」）。
* **不注入、不挂钩、不改内存**：只是"替你按一下"。但请注意：按键真的会进游戏。
* 发完**核对系统收下的条数**（`SendInput` 返回成功插入的事件数）：
  没全收下就报 ⚠，**绝不谎报**成"已按下"。
* **被系统拦下是正常的**：锁屏 / UAC 安全桌面 / 前台窗口是**管理员权限**的程序时，Windows 会拒绝
  合成按键（错误码 5 = 拒绝访问），这时日志会写明「系统只收下 0/N 条（错误码 5）」。
* 非 Windows → 老实报失败，不崩。
* 写法（不区分大小写）：`D` / `F12` / `Insert` / `Ctrl+D` / `Shift+Alt+→`；
  修饰键顺序随便，箭头可以写 `↑↓←→` 或 `Up/Down/Left/Right`；
  **修饰键本身也能当主键**（`Ctrl` / `Alt`）—— 只想按一下 Ctrl 键就写 `Ctrl`。
* **全键盘都能写**：字母 / 数字 / F1-F24 / 编辑键 / 方向键 / 小键盘（`NumPad1`、
  `NumPad+`、`NumPad.` …，和主键盘的数字**分开**）/ `CapsLock` / `NumLock` / `ScrollLock` /
  `PrintScreen` / `Pause` / `Clear` / `Menu`（右键菜单键）/ 符号键 / 媒体键。
* **Win 键不收录**（界面里按 Win 会提示不支持）：Windows 把它和一堆组合键自己留着了，
  按下去先弹开始菜单，发了也未必到游戏。解析层还认 `Win`（老配置不会坏）。
"""

import ctypes
import os

KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

# ----------------------------- 名字 ↔ 键码 -----------------------------

MOD_ORDER = ("Ctrl", "Shift", "Alt", "Win")
MOD_VK = {"Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12, "Win": 0x5B}
MOD_ALIAS = {"CTRL": "Ctrl", "CONTROL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt",
             "WIN": "Win", "WINDOWS": "Win", "META": "Win", "SUPER": "Win",
             "CMD": "Win"}

# 修饰键本身也能当「主键」按（例如只想按一下 Ctrl 键）：`Ctrl` / `Alt` …
MOD_AS_KEY = {"WIN": 0x5B, "CTRL": 0x11, "CONTROL": 0x11, "SHIFT": 0x10, "ALT": 0x12}

KEYS = {}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYS[_c] = ord(_c)
for _d in "0123456789":
    KEYS[_d] = ord(_d)
for _i in range(1, 25):
    KEYS["F%d" % _i] = 0x6F + _i
for _i in range(10):
    KEYS["NUMPAD%d" % _i] = 0x60 + _i
KEYS.update({
    "WIN": 0x5B, "CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12,
    "ESC": 0x1B, "ESCAPE": 0x1B, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "BACKSPACE": 0x08, "INSERT": 0x2D, "INS": 0x2D, "DELETE": 0x2E, "DEL": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "PGUP": 0x21, "PGDN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "↑": 0x26, "↓": 0x28, "←": 0x25, "→": 0x27,
    "SPACE": 0x20, "空格": 0x20, "CAPSLOCK": 0x14, "NUMLOCK": 0x90,
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA,
    "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "PLUS": 0xBB, "加号": 0xBB,
    "MEDIAPLAY": 0xB3, "MEDIANEXT": 0xB0, "MEDIAPREV": 0xB1,
    "VOLUMEUP": 0xAF, "VOLUMEDOWN": 0xAE, "VOLUMEMUTE": 0xAD,
})
# 小键盘（数字区）单独一套键码：和主键盘的数字/符号**不是同一个键**（游戏里能分开）
KEYS.update({
    "NUMPAD*": 0x6A, "NUMPAD+": 0x6B, "NUMPAD-": 0x6D, "NUMPAD.": 0x6E, "NUMPAD/": 0x6F,
    "*": 0x6A, "乘号": 0x6A,
})
# 其余「全键盘」键：锁键 / 屏幕键 / 菜单键 / 清空键 / 停止键
KEYS.update({
    "SCROLLLOCK": 0x91, "PRINTSCREEN": 0x2C, "PRTSC": 0x2C, "PAUSE": 0x13,
    "CLEAR": 0x0C, "APPS": 0x5D, "MENU": 0x5D, "MEDIASTOP": 0xB2,
})

# 显示名：箭头用符号（和用户写法一致），其余按上面的大写名
DISPLAY = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→",
           "PAGEUP": "PageUp", "PAGEDOWN": "PageDown", "CAPSLOCK": "CapsLock",
           "NUMLOCK": "NumLock", "SCROLLLOCK": "ScrollLock",
           "PRINTSCREEN": "PrintScreen", "PRTSC": "PrintScreen", "PAUSE": "Pause",
           "CLEAR": "Clear", "APPS": "Menu", "MENU": "Menu",
           "ESC": "Esc", "ESCAPE": "Esc", "DEL": "Delete", "DELETE": "Delete",
           "INS": "Insert", "INSERT": "Insert", "RETURN": "Enter", "SPACE": "Space",
           "空格": "Space", "加号": "+", "PLUS": "+", "乘号": "*",
           "BACKSPACE": "Backspace", "TAB": "Tab", "HOME": "Home", "END": "End",
           "MEDIAPLAY": "MediaPlay", "MEDIANEXT": "MediaNext", "MEDIAPREV": "MediaPrev",
           "MEDIASTOP": "MediaStop", "VOLUMEUP": "VolumeUp",
           "VOLUMEDOWN": "VolumeDown", "VOLUMEMUTE": "VolumeMute",
           "NUMPAD*": "NumPad*", "NUMPAD+": "NumPad+", "NUMPAD-": "NumPad-",
           "NUMPAD.": "NumPad.", "NUMPAD/": "NumPad/",
           "WIN": "Win", "CTRL": "Ctrl", "SHIFT": "Shift", "ALT": "Alt"}
for _i in range(10):
    DISPLAY["NUMPAD%d" % _i] = "NumPad%d" % _i

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


# ----------------------------- 发键（Windows） -----------------------------

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
except Exception:                                        # 非 Windows / 测试环境
    _user32 = None


if _user32 is not None:
    # 注意：这三个结构体的**大小必须和系统一致**（x64 上 INPUT = 40 字节）——
    # 差一个字节 SendInput 就直接返回 0（它校验 cbSize），而且不抛异常。
    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                    ("wParamH", ctypes.c_ushort)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]

    try:
        _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
        _user32.SendInput.restype = ctypes.c_uint
        _SEND_OK = True
    except Exception:
        _SEND_OK = False
else:
    _SEND_OK = False


def available():
    """能不能真的发按键。"""
    return bool(_user32 is not None and _SEND_OK)


def _send(events):
    """events = [(vk, flags), ...]；返回系统收下的条数（失败 0）。"""
    if not available() or not events:
        return 0
    n = len(events)
    arr = (_INPUT * n)()
    for i, (vk, flags) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].u.ki.wVk = int(vk)
        arr[i].u.ki.wScan = 0
        arr[i].u.ki.dwFlags = int(flags)
        arr[i].u.ki.time = 0
        arr[i].u.ki.dwExtraInfo = None
    try:
        sent = int(_user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(_INPUT)))
    except Exception as e:
        log("⚠ 发按键出错：%r" % (e,))
        return 0
    if sent != n:                                        # 系统只收下一部分 → 把原因记下来
        err = int(ctypes.get_last_error() or 0)
        log("⚠ 发按键：系统只收下 %d/%d 条（错误码 %d）" % (sent, n, err))
    return sent


# ----------------------------- 解析 / 格式化 -----------------------------


def parse(combo):
    """把「Shift+Alt+→」解析成 {"mods": [...], "key": "→", "vk": ...}。

    返回 (True, info) 或 (False, 原因)。
    """
    raw = str(combo or "").strip()
    if not raw:
        return False, "还没设置按键"
    parts = [p.strip() for p in raw.replace("＋", "+").split("+")]
    if parts and parts[-1] == "":            # 「Ctrl++」这种：末尾的 + 是加号键本身
        parts = parts[:-1] + ["PLUS"]
    parts = [p for p in parts if p != ""]
    if len(parts) >= 2 and parts[-1].upper() == "PLUS" and parts[-2].upper() == "NUMPAD":
        parts = parts[:-2] + ["NUMPAD+"]     # 「NumPad+」被加号拆开了，合回一个键名
    if not parts:
        return False, "还没设置按键"
    mods, key_name = [], parts[-1]
    for p in parts[:-1]:
        m = MOD_ALIAS.get(p.upper()) or (p if p in MOD_VK else None)
        if m is None:
            return False, "看不懂这个修饰键：%s" % p
        if m not in mods:
            mods.append(m)
    key_up = key_name.upper()
    vk = KEYS.get(key_up)
    display = key_name
    if vk is None and key_name in KEYS:       # 符号键（原来就存的符号）
        vk = KEYS[key_name]
    if vk is None:
        return False, "看不懂这个按键：%s" % key_name
    if key_up in MOD_AS_KEY and mods:         # 「Ctrl+Shift」这种：只写了修饰键，还差主键
        return False, "只写了修饰键，还得再按一个主键（例如 Ctrl+D）"
    if len(key_up) > 1:                       # 多字符 → 统一显示名
        display = DISPLAY.get(key_up, key_up)
    else:
        display = key_up
    mods = [m for m in MOD_ORDER if m in mods]          # 固定顺序，便于比较
    return True, {"mods": mods, "key": display, "vk": int(vk)}


def format_combo(mods, key):
    """把修饰键 + 主键拼成「Ctrl+Shift+D」。"""
    ms = [m for m in MOD_ORDER if m in (mods or [])]
    return "+".join(ms + [str(key)]) if ms else str(key)


def describe(combo):
    """规范写法（存进配置 / 显示用）；看不懂就原样返回。"""
    ok, info = parse(combo)
    if not ok:
        return str(combo or "")
    return format_combo(info["mods"], info["key"])


def press(combo, logger=None):
    """真的按一下。返回 (ok, 说明) —— 说明只讲我们做了什么，不吹目标收到了。"""
    ok, info = parse(combo)
    if not ok:
        return False, "按键写法看不懂：%s" % info
    name = format_combo(info["mods"], info["key"])
    if not available():
        (logger or log)("⚠ 非 Windows 环境：按键没发出去（%s）" % name)
        return False, "非 Windows 环境，按键没发出去"
    events = [(MOD_VK[m], 0) for m in info["mods"]]
    events.append((info["vk"], 0))
    events.append((info["vk"], KEYEVENTF_KEYUP))
    events += [(MOD_VK[m], KEYEVENTF_KEYUP) for m in reversed(info["mods"])]
    sent = _send(events)
    if sent == len(events):
        return True, "已按下 %s（发给当时最前面的窗口）" % name
    return False, "按键没全发出去（系统只收下 %d/%d 条）" % (sent, len(events))
