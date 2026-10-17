# -*- coding: utf-8 -*-
"""
操作注册表（可扩展的「动作」框架）
==================================

一个操作 = 一条 `OpSpec`（id / 名称 / 说明 / **是否允许同框多条** / 参数表 / 执行函数）。
以后加新功能：**写一个执行函数 + `register(OpSpec(...))`** 就行，
界面（功能配置页）、配置存储、执行器都会自动认识它 —— 不用改 UI 代码。

当前内置
--------
| id                | 名称         | 参数                     | 同框可多条 |
|-------------------|--------------|--------------------------|-----------|
| `media_play`      | 媒体播放     | -                        | 否        |
| `media_pause`     | 媒体暂停     | -                        | 否        |
| `open_url`        | 打开网页     | url                      | **是**    |
| `focus_game`      | 切换到游戏界面 | -                       | 否        |
| `minimize_game`   | 游戏最小化   | -                        | 否        |
| `focus_window`    | 切换到界面   | target                   | **是**    |
| `minimize_window` | 最小化界面   | target                   | **是**    |
| `run_file`        | 执行文件     | path                     | **是**    |
| `set_volume`      | 调节程序音量 | proc / level / fade_ms   | **是**    |
| `speak`           | 语音播报     | text / file / file_volume / tts_volume | **是** |
| `toast`           | 发送通知     | title / body             | **是**    |
| `delay`           | 延迟执行     | ms                       | **是**    |
| `send_keys`       | 模拟按键     | keys                     | **是**    |

* `target` = 窗口的**标题或进程名**（执行时现搜窗口，所以程序随时开关都行）。
* **游戏窗口**（`切换到游戏界面` / `游戏最小化`）：执行时**现查**（进程名含 `scpsl`）。
  上次记住的句柄会**先验证、再用**，验不过就重新找 —— 游戏重启换窗口也照样生效，
  也不会因为句柄被系统回收而去操作别人的窗口。
* `path` = 文件完整路径（执行 = 像双击一样打开）。
* `set_volume` = 只改**这个程序自己**的音频会话（不动系统总音量）；目标=当前 → 跳过。
  `fade_ms` 的渐变**在后台自己跑**，操作立刻结束、不占用后面的操作（用户要求）。
* `speak` = 排进**同一个播报队列**（死亡/复活共用，绝不重合）；`file` 可不填；
  **提示音音量和语音朗读音量分开填**（各管各的）。
* `toast` = Windows 通知（标题 + 内容）；**没有按钮**，点它只是被系统收走。
* `delay` = 等 `ms` 毫秒（0-10000）；新的死亡/复活一来会**立刻打断**整条列表。
* `send_keys` = 真的按一下（发给**当时最前面的窗口**，不注入、不挂钩）。
* 参数带 `optional` 的不必填；`OpSpec.validate` 是参数级附加校验（添加时和执行时都跑）。

条目结构：`{"type": "open_url", "params": {"url": "https://..."}}`
"""

import os
import subprocess
import sys
import time
import webbrowser

import key_input
import toast_actions
import volume_actions
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
    def __init__(self, type, name, desc="", allow_multiple=False, params=(), run=None,
                 optional=(), validate=None):
        self.type = type
        self.name = name
        self.desc = desc
        self.allow_multiple = bool(allow_multiple)
        self.params = tuple(params)          # ((key, 显示名, 默认值, 说明), ...)
        self.optional = tuple(optional)      # 可以不填的参数键（空着也能加）
        self.validate = validate             # 附加校验：dict -> (ok, 说明)
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
        # 老配置的「语音播报」只有一个 volume：**提示音 / 朗读都按它来**（不丢用户设置）
        if spec.type == "speak":
            old = str(raw.get("volume") or "").strip()
            if old:
                for key in ("file_volume", "tts_volume"):
                    if not str(raw.get(key) or "").strip():
                        params[key] = old
            params.pop("volume", None)      # 老键不再留着（避免两处音量打架）
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
    params = item.get("params") or {}
    for key, label, default, _h in spec.params:
        if key in spec.optional:                 # 可选的参数不填也合法
            continue
        v = params.get(key)
        if (v is None or str(v).strip() == "") and str(default).strip() == "":
            return False, "%s 缺少%s" % (spec.name, label)
    if spec.validate is not None:                # 参数级附加校验（范围 / 写法）
        try:
            ok, why = spec.validate(params)
            if not ok:
                return False, why
        except Exception as e:
            return False, "%s 参数校验出错：%r" % (spec.name, e)
    return True, ""


# 新建条目时的**按框预填**：同一个操作放进「死亡后」和「复活后」，默认值不一样
# （典型：死了静音、活了恢复；死了说"你已死亡"、活了说"你已复活"）。
PREFILL = {
    "set_volume": {"level": {"death": "0", "alive": "100"}},
    "speak": {"text": {"death": "你已死亡", "alive": "你已复活"}},
    "toast": {"body": {"death": "检测到你已死亡", "alive": "检测到你已复活"}},
}


def prefill_for(op_type, key, which):
    """这个操作在这个框里，参数 `key` 该预填什么（没有特殊规则返回空串）。"""
    return ((PREFILL.get(op_type) or {}).get(key) or {}).get(which or "", "")


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

    def __init__(self, audio=None, hwnd=None, logger=None, speech=None,
                 cancel=None, trigger="", sleep=None):
        self.audio = audio
        self.hwnd = hwnd                 # int 或 返回 int 的可调用对象（**只是线索**，用前现验）
        self.log = logger or log
        self.speech = speech             # 语音播报队列（死亡/复活共用）
        self.cancel = cancel             # Event 或返回 bool 的函数：新的状态变化 → 置上
        self.trigger = trigger           # "death" / "alive" / "manual"（给预填/通知用）
        self.sleep = sleep or time.sleep  # 让「延迟」可测
        self.open_url = open_url_default
        self.open_file = open_file_default
        self.lookup_window = win32_window.find_window
        self.find_game = win32_window.find_game_window     # 现查游戏窗口
        self.is_game = win32_window.is_game_window         # 现验句柄还是不是游戏窗口
        self.focus = win32_window.focus_window
        self.minimize = win32_window.minimize_window
        self.set_proc_volume = volume_actions.start_fade    # 渐变在后台跑，操作立刻返回
        self.send_keys = key_input.press
        self.notify = toast_actions.send

    def cancelled(self):
        """现在是不是该中断了（新的死亡/复活来了）。"""
        c = self.cancel
        if c is None:
            return False
        try:
            if callable(c):
                return bool(c())
            return bool(c.is_set())
        except Exception:
            return False

    def game_hwnd(self):
        h = self.hwnd() if callable(self.hwnd) else self.hwnd
        try:
            return int(h or 0)
        except Exception:
            return 0

    def game_hwnd_live(self):
        """定位游戏窗口：缓存的句柄**验过**才用，否则**现查**。

        返回 `(hwnd, 是否重找过)`。游戏重启会换句柄，所以绝不能直接信任缓存值；
        句柄还可能被系统回收给别的程序，验不过就必须重找（否则会操作错窗口）。
        """
        h = self.game_hwnd()
        if h and self.is_game(h):
            return h, False
        h2 = self.find_game()
        try:
            h2 = int(h2 or 0)
        except Exception:
            h2 = 0
        return h2, bool(h and h2 and h2 != h)       # 只有"原来有缓存但换了"才算重找

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
    hwnd, refound = ctx.game_hwnd_live()
    if not hwnd:
        return False, "没找到游戏窗口（游戏没开？）"
    ok = ctx.focus(hwnd)
    if not ok:
        return False, "切换游戏界面没生效（窗口没到前台）"
    return True, "已切到游戏界面" + ("（窗口换了，已重找）" if refound else "")


def _run_minimize_game(params, ctx):
    hwnd, refound = ctx.game_hwnd_live()
    if not hwnd:
        return False, "没找到游戏窗口（游戏没开？）"
    ok = ctx.minimize(hwnd)
    if not ok:
        return False, "游戏最小化没生效（窗口可能已变）"
    return True, "已把游戏最小化" + ("（窗口换了，已重找）" if refound else "")


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


# ---------------- 新操作（音量 / 播报 / 通知 / 延迟 / 按键） ----------------

DELAY_MAX_MS = 10000                 # 延迟上限：10 秒（用户定的）
DELAY_SLICE_S = 0.05                 # 延迟切片：每 50ms 查一次"要不要打断"


def _run_set_volume(params, ctx):
    p = params or {}
    proc = str(p.get("proc", "") or "").strip()
    return ctx.set_proc_volume(proc, p.get("level", ""), p.get("fade_ms", 0), logger=ctx.log)


def _run_speak(params, ctx):
    p = params or {}
    text = str(p.get("text", "") or "").strip()
    path = str(p.get("file", "") or "").strip()
    if ctx.speech is None:
        return False, "语音后端未就绪"
    return ctx.speech.say(text, path, p.get("file_volume", "100"), p.get("tts_volume", "100"))


def _run_toast(params, ctx):
    p = params or {}
    title = str(p.get("title", "") or "").strip()
    body = str(p.get("body", "") or "").strip()
    return ctx.notify(title, body, logger=ctx.log)


def _run_delay(params, ctx):
    raw = str((params or {}).get("ms", "") or "").strip()
    ok, ms = parse_delay_ms(raw)
    if not ok:
        return False, ms
    if ms == 0:
        return True, "延迟 0ms（等于不延迟）"
    total = ms / 1000.0
    slices = max(1, int(round(total / DELAY_SLICE_S)))    # 固定片数：总时长正好，也能随时被查打断
    step = total / slices
    t0 = time.monotonic()
    for _i in range(slices):
        if ctx.cancelled():
            return False, "延迟被打断（已等 %.2fs / %.2fs）" % (time.monotonic() - t0, total)
        ctx.sleep(step)
    if ctx.cancelled():                                  # 最后一片刚睡完，状态就变了
        return False, "延迟被打断（已等 %.2fs / %.2fs）" % (time.monotonic() - t0, total)
    return True, "已延迟 %dms" % ms


def parse_delay_ms(raw):
    """延迟毫秒：0-10000 的整数。返回 (ok, int 或 原因)。"""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return False, "还没填延迟时间"
    try:
        v = int(float(s))
    except Exception:
        return False, "延迟要填 0-%d 的整数毫秒（现在填的是 %r）" % (DELAY_MAX_MS, raw)
    if v < 0 or v > DELAY_MAX_MS:
        return False, "延迟必须在 0-%d 毫秒之间（现在填的是 %s）" % (DELAY_MAX_MS, v)
    return True, v


def _run_send_keys(params, ctx):
    combo = str((params or {}).get("keys", "") or "").strip()
    if not combo:
        return False, "还没设置按键"
    return ctx.send_keys(combo, logger=ctx.log)


# ---------------- 参数级附加校验（添加时 / 执行时都跑） ----------------


def _v_set_volume(p):
    if not str(p.get("proc", "") or "").strip():
        return False, "没有填进程名"
    ok, why = volume_actions.parse_level(p.get("level", ""))
    if not ok:
        return False, why
    return volume_actions.parse_fade_ms(p.get("fade_ms", ""))


def _v_speak(p):
    if not (str(p.get("text", "") or "").strip() or str(p.get("file", "") or "").strip()):
        return False, "「播报文本」和「提示音文件」至少填一个"
    for key, label in (("file_volume", "提示音音量"), ("tts_volume", "语音音量")):
        ok, why = volume_actions.parse_level(p.get(key, "100"))
        if not ok:
            return False, "%s：%s" % (label, why)
    return True, ""


def _v_toast(p):
    if not (str(p.get("title", "") or "").strip() or str(p.get("body", "") or "").strip()):
        return False, "「标题」和「内容」至少填一个"
    return True, ""


def _v_delay(p):
    return parse_delay_ms(p.get("ms", ""))


def _v_send_keys(p):
    return key_input.parse(p.get("keys", ""))


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
register(OpSpec("set_volume", "调节程序音量",
                "把某个程序自己的音量渐弱/渐强到指定值（不动系统总音量）",
                True, (("proc", "进程名", "SCPSL.exe", "例如 SCPSL.exe（下拉里可选现在有声音的程序）"),
                       ("level", "目标音量", "0", "0-100；和当前一样就跳过"),
                       ("fade_ms", "渐变时长", "0", "毫秒，0=直接切，最长 3000；渐变在后台跑")),
                _run_set_volume, validate=_v_set_volume))
register(OpSpec("speak", "语音播报",
                "先播一段本地提示音（可选），再朗读文本（可选）；死亡/复活共用一个队列",
                True, (("text", "播报文本", "", "留空则只播提示音"),
                       ("file", "提示音文件", "", "可选，mp3 / m4a / wav 都行"),
                       ("file_volume", "提示音音量", "100", "0-100"),
                       ("tts_volume", "语音音量", "100", "0-100")),
                _run_speak, optional=("text", "file"), validate=_v_speak))
register(OpSpec("toast", "发送通知",
                "发一条 Windows 通知（标题 + 内容）",
                True, (("title", "标题", "SCP:SL BeBusy", ""),
                       ("body", "内容", "检测到你已死亡", "")),
                _run_toast, validate=_v_toast))
register(OpSpec("delay", "延迟执行",
                "等一会儿再接着执行后面的操作（新的状态变化会打断）",
                True, (("ms", "延迟", "1000", "毫秒，0-10000"),),
                _run_delay, validate=_v_delay))
register(OpSpec("send_keys", "模拟按键",
                "按一下你设定的按键（发给当时最前面的窗口）",
                True, (("keys", "按键", "", "例如 Ctrl+D / F12 / Shift+Alt+→ / Win"),),
                _run_send_keys, validate=_v_send_keys))


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
    """按顺序跑一遍列表：单个失败**不中断**后续。

    * **打断**：一旦 `ctx.cancelled()`（新的死亡/复活来了），**剩下的条目一条都不跑**，
      正在等的那条（延迟/渐变）也会自己停下 —— 用户要求：新状态变化直接终止旧列表。
    * 返回统计 dict（`ok` / `fail` / `skip` / `total` / `aborted`）。
    """
    items = list(items or [])
    tag = label + " " if label else ""
    stat = {"total": len(items), "ok": 0, "skip": 0, "fail": 0, "aborted": 0}
    if not items:
        ctx.emit("[op] %s动作列表是空的 → 什么都不做" % tag)
        return stat
    for i, item in enumerate(items, 1):
        if ctx.cancelled():
            stat["aborted"] = len(items) - i + 1
            ctx.emit("[op] %s被新的状态变化打断：第 %d 条起（共 %d 条）不再执行"
                     % (tag, i, len(items) - i + 1))
            break
        name = describe_item(item)
        ok, msg = run_item(item, ctx)
        if ok:
            stat["ok"] += 1
            ctx.emit("[op] %s(%d/%d) %s → %s" % (tag, i, len(items), name, msg))
        elif ctx.cancelled():
            stat["skip"] += 1
            ctx.emit("[op] %s(%d/%d) %s → ⏹ %s" % (tag, i, len(items), name, msg))
        else:
            stat["fail"] += 1
            ctx.emit("[op] %s(%d/%d) %s → ⚠ %s" % (tag, i, len(items), name, msg))
    if stat["aborted"]:
        ctx.emit("[op] %s被中断：成功 %d / 失败 %d / 跳过 %d（共 %d 条）"
                 % (tag, stat["ok"], stat["fail"], stat["skip"], stat["total"]))
    else:
        ctx.emit("[op] %s执行完毕：成功 %d / 失败 %d（共 %d）"
                 % (tag, stat["ok"], stat["fail"], stat["total"]))
    return stat
