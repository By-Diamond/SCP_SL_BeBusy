# -*- coding: utf-8 -*-
"""
操作注册表（可扩展的「动作」框架）
==================================

一个操作 = 一条 `OpSpec`（id / 名称 / 说明 / **是否允许同框多条** / 参数表 / 执行函数）。
以后加新功能：**写一个执行函数 + `register(OpSpec(...))`** 就行，
界面（功能配置页）、配置存储、执行器都会自动认识它 —— 不用改 UI 代码。

当前内置
--------
| id                | 名称         | 参数   | 同框可多条 |
|-------------------|--------------|--------|-----------|
| `media_play`      | 媒体播放     | -      | 否        |
| `media_pause`     | 媒体暂停     | -      | 否        |
| `open_url`        | 打开网页     | url    | **是**    |
| `focus_game`      | 切换到游戏界面 | -     | 否        |
| `minimize_game`   | 游戏最小化   | -      | 否        |
| `focus_window`    | 切换到界面   | target | **是**    |
| `minimize_window` | 最小化界面   | target | **是**    |
| `run_file`        | 执行文件     | path   | **是**    |

* `target` = 窗口的**标题或进程名**（执行时现搜窗口，所以程序随时开关都行）。
* `path` = 文件完整路径（执行 = 像双击一样打开）。

条目结构：`{"type": "open_url", "params": {"url": "https://..."}}`
"""

import os
import subprocess
import sys
import webbrowser

import win32_window

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


# ----------------------------- 条目与规格 -----------------------------


class OpSpec:
    def __init__(self, type, name, desc="", allow_multiple=False, params=(), run=None):
        self.type = type
        self.name = name
        self.desc = desc
        self.allow_multiple = bool(allow_multiple)
        self.params = tuple(params)          # ((key, 显示名, 默认值, 说明), ...)
        self.run = run

    def defaults(self):
        return {p[0]: p[2] for p in self.params}

    def __repr__(self):
        return "<OpSpec %s>" % self.type


REGISTRY = {}
ORDER = []


def register(spec):
    if spec.type in REGISTRY:
        raise ValueError("操作 id 重复：%s" % spec.type)
    REGISTRY[spec.type] = spec
    ORDER.append(spec.type)
    return spec


def all_specs():
    return [REGISTRY[t] for t in ORDER]


def get_spec(op_type):
    return REGISTRY.get(op_type)


def new_item(op_type, **params):
    """按操作类型造一个条目（未知类型返回 None）。"""
    spec = get_spec(op_type)
    if spec is None:
        return None
    p = spec.defaults()
    p.update(params)
    return {"type": op_type, "params": p}


def normalize_item(item):
    """把外部配置里的条目补齐参数（老配置缺参数也能跑）。"""
    if not isinstance(item, dict):
        return None
    spec = get_spec(item.get("type"))
    if spec is None:
        return None
    params = dict(spec.defaults())
    raw = item.get("params")
    if isinstance(raw, dict):
        params.update(raw)
    return {"type": spec.type, "params": params}


def param_text(item):
    """把条目参数显示成一行字（列表里用）。"""
    spec = get_spec((item or {}).get("type"))
    if spec is None:
        return ""
    parts = []
    for key, label, _d, _h in spec.params:
        v = (item.get("params") or {}).get(key)
        if v in (None, ""):
            continue
        parts.append(str(v))
    return " · ".join(parts)


def describe_item(item):
    """列表里显示的名字：`打开网页 — https://…`。"""
    spec = get_spec((item or {}).get("type"))
    if spec is None:
        return "未知操作（%s）" % ((item or {}).get("type"),)
    extra = param_text(item)
    return "%s — %s" % (spec.name, extra) if extra else spec.name


def validate_item(item):
    """条目是否可执行。返回 (ok, 说明)。"""
    spec = get_spec((item or {}).get("type"))
    if spec is None:
        return False, "未知操作类型：%s" % ((item or {}).get("type"),)
    for key, label, default, _h in spec.params:
        v = (item.get("params") or {}).get(key)
        if (v is None or str(v).strip() == "") and str(default).strip() == "":
            return False, "%s 缺少%s" % (spec.name, label)
    return True, ""


# ----------------------------- 执行上下文 -----------------------------


def normalize_url(url):
    """补全协议头。"""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    return u


def open_url_default(url):
    """用系统默认程序打开网址（默认浏览器）。"""
    u = normalize_url(url)
    if not u:
        return False, "网址为空"
    try:
        if os.name == "nt":
            os.startfile(u)                                  # noqa: S606 (Windows 专用)
        else:
            webbrowser.open(u)
        return True, "已打开 %s" % u
    except Exception as e:
        try:
            webbrowser.open(u)
            return True, "已打开 %s（回退方式）" % u
        except Exception:
            return False, "打开网页失败：%r" % (e,)


def _expand_path(p):
    """展开 %USERPROFILE% / ~ 之类的路径写法。"""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(str(p or "").strip().strip('"'))))


def open_file_default(path):
    """像双击桌面快捷方式一样打开一个文件/程序（Windows 走 os.startfile）。"""
    if not str(path or "").strip():
        return False, "没有填写文件"
    p = _expand_path(path)
    if not os.path.exists(p):
        return False, "文件不存在：%s" % p
    try:
        if os.name == "nt":
            os.startfile(p)                                  # noqa: S606 (Windows 专用)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])                     # noqa: S603
        else:
            subprocess.Popen(["xdg-open", p])                 # noqa: S603
        return True, "已打开 %s" % p
    except Exception as e:
        return False, "打开失败：%r" % (e,)


class OpContext:
    """执行操作时能用到的东西（测试时把这些换成假的即可）。"""

    def __init__(self, audio=None, hwnd=None, logger=None):
        self.audio = audio
        self.hwnd = hwnd                 # int 或 返回 int 的可调用对象
        self.log = logger or log
        self.open_url = open_url_default
        self.open_file = open_file_default
        self.lookup_window = win32_window.find_window
        self.focus = win32_window.focus_window
        self.minimize = win32_window.minimize_window

    def game_hwnd(self):
        h = self.hwnd() if callable(self.hwnd) else self.hwnd
        try:
            return int(h or 0)
        except Exception:
            return 0

    def emit(self, msg):
        self.log(msg)


# ----------------------------- 执行函数 -----------------------------


def _run_media_play(params, ctx):
    if ctx.audio is None:
        return False, "音频后端未就绪"
    sent = ctx.audio.play("动作：播放")
    return True, ("已发送播放键" if sent else "已是播放中，跳过")


def _run_media_pause(params, ctx):
    if ctx.audio is None:
        return False, "音频后端未就绪"
    sent = ctx.audio.pause("动作：暂停")
    return True, ("已发送暂停键" if sent else "已是暂停中，跳过")


def _run_open_url(params, ctx):
    url = (params or {}).get("url", "")
    if not str(url).strip():
        return False, "没有填写网址"
    return ctx.open_url(url)


def _run_focus_game(params, ctx):
    hwnd = ctx.game_hwnd()
    if not hwnd:
        return False, "还没锁定 SCPSL 窗口（游戏没开？）"
    ok = ctx.focus(hwnd)
    return bool(ok), ("已切到游戏界面" if ok else "切换到游戏界面失败")


def _run_minimize_game(params, ctx):
    hwnd = ctx.game_hwnd()
    if not hwnd:
        return False, "还没锁定 SCPSL 窗口（游戏没开？）"
    ok = ctx.minimize(hwnd)
    return bool(ok), ("已把游戏最小化" if ok else "游戏最小化失败")


def _run_focus_window(params, ctx):
    target = str((params or {}).get("target", "") or "").strip()
    if not target:
        return False, "没有填写窗口"
    hwnd = ctx.lookup_window(target)
    if not hwnd:
        return False, "没找到窗口：%s" % target
    ok = ctx.focus(hwnd)
    return bool(ok), ("已切到「%s」" % target if ok else "切换「%s」失败" % target)


def _run_minimize_window(params, ctx):
    target = str((params or {}).get("target", "") or "").strip()
    if not target:
        return False, "没有填写窗口"
    hwnd = ctx.lookup_window(target)
    if not hwnd:
        return False, "没找到窗口：%s" % target
    ok = ctx.minimize(hwnd)
    return bool(ok), ("已最小化「%s」" % target if ok else "最小化「%s」失败" % target)


def _run_run_file(params, ctx):
    path = str((params or {}).get("path", "") or "").strip()
    if not path:
        return False, "没有填写文件"
    return ctx.open_file(path)


# ----------------------------- 内置操作注册 -----------------------------

register(OpSpec("media_play", "媒体播放", "让系统媒体开始播放",
                False, (), _run_media_play))
register(OpSpec("media_pause", "媒体暂停", "让系统媒体暂停",
                False, (), _run_media_pause))
register(OpSpec("open_url", "打开网页", "用默认浏览器打开一个网址",
                True, (("url", "网址", "", "例如 https://www.bilibili.com"),),
                _run_open_url))
register(OpSpec("focus_game", "切换到游戏界面", "把 SCPSL 窗口切到前台（最小化了会还原）",
                False, (), _run_focus_game))
register(OpSpec("minimize_game", "游戏最小化", "把 SCPSL 窗口最小化",
                False, (), _run_minimize_game))
register(OpSpec("focus_window", "切换到界面", "把指定窗口切到前台（最小化了会还原）",
                True, (("target", "窗口", "", "标题或进程名，例如 chrome.exe"),),
                _run_focus_window))
register(OpSpec("minimize_window", "最小化界面", "把指定窗口最小化",
                True, (("target", "窗口", "", "标题或进程名，例如 chrome.exe"),),
                _run_minimize_window))
register(OpSpec("run_file", "执行文件", "像双击一样打开一个文件或程序",
                True, (("path", "文件", "", "例如 C:\\Tools\\a.exe"),),
                _run_run_file))


# ----------------------------- 执行器 -----------------------------


def run_item(item, ctx):
    """跑一个条目。返回 (ok, 说明)。异常不外溢，只记日志。"""
    spec = get_spec((item or {}).get("type"))
    if spec is None:
        return False, "未知操作类型：%s" % ((item or {}).get("type"),)
    if spec.run is None:
        return False, "%s 还没实现" % spec.name
    ok, msg = validate_item(item)
    if not ok:
        return False, msg
    try:
        res = spec.run(item.get("params") or {}, ctx)
        if isinstance(res, tuple) and len(res) == 2:
            return bool(res[0]), str(res[1])
        return True, "完成"
    except Exception as e:
        return False, "执行 %s 出错：%r" % (spec.name, e)


def run_list(items, ctx, label=""):
    """按顺序跑一遍列表：单个失败**不中断**后续。返回统计 dict。"""
    items = list(items or [])
    stat = {"total": len(items), "ok": 0, "skip": 0, "fail": 0}
    if not items:
        ctx.emit("[op] %s动作列表是空的 → 什么都不做" % (label + " " if label else ""))
        return stat
    for i, item in enumerate(items, 1):
        name = describe_item(item)
        ok, msg = run_item(item, ctx)
        if ok:
            stat["ok"] += 1
            ctx.emit("[op] %s(%d/%d) %s → %s" % (label + " " if label else "",
                                                 i, len(items), name, msg))
        else:
            stat["fail"] += 1
            ctx.emit("[op] %s(%d/%d) %s → ⚠ %s" % (label + " " if label else "",
                                                   i, len(items), name, msg))
    ctx.emit("[op] %s执行完毕：成功 %d / 失败 %d（共 %d）"
             % (label + " " if label else "", stat["ok"], stat["fail"], stat["total"]))
    return stat
