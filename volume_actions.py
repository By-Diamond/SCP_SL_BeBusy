# -*- coding: utf-8 -*-
"""
程序音量（无界面）：把「某个程序自己的音频会话」调大 / 调小
==========================================================

* 走 Windows 自带的音频会话接口（Core Audio / `ISimpleAudioVolume`，用 pycaw 调用）：
  **只改这一个程序自己的音量**，不动系统总音量、不动别的程序、不动游戏本体。
* 支持**渐变**：`fade_ms` 毫秒内从当前音量线性走到目标音量（0 = 直接切过去）。
  **渐变在后台线程里自己跑完**，调用方立刻拿到结果、继续做后面的事（用户要求：
  渐变耗时不算延迟执行）；同一个程序再来一次渐变 → **新的接管旧的**。
* **目标 == 当前** → 什么都不做（这也算"无效"，如实写日志，不当成失败）。
* **找不到这个程序的音频会话**（程序没开 / 没在出声）→ 老实报失败，不假装成功。
* `list_processes()`：现在**有声音的程序**（选择进程用）。
* 没装 pycaw / 不是 Windows → 报"用不了"，不崩。
"""

import os
import threading
import time

LEVEL_MIN, LEVEL_MAX = 0, 100
FADE_MAX_MS = 3000                 # 渐变最长 3 秒（用户定的）
STEP_MS = 40                       # 渐变的步进粒度（后台线程里每 40ms 走一步）

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


# ----------------------------- 参数解析 -----------------------------


def parse_level(raw):
    """目标音量：0-100 的整数。返回 (ok, int 或 原因)。"""
    s = str(raw if raw is not None else "").strip().rstrip("%").strip()
    if not s:
        return False, "还没填目标音量"
    try:
        v = int(round(float(s)))
    except Exception:
        return False, "目标音量要填 0-100 的整数（现在填的是 %r）" % (raw,)
    if not (LEVEL_MIN <= v <= LEVEL_MAX):
        return False, "目标音量必须在 %d-%d 之间（现在填的是 %s）" % (LEVEL_MIN, LEVEL_MAX, v)
    return True, v


def parse_fade_ms(raw):
    """渐变时长：0-3000 毫秒。返回 (ok, int 或 原因)。"""
    s = str(raw if raw is not None else "").strip()
    if s == "":
        return True, 0
    try:
        v = int(float(s))
    except Exception:
        return False, "渐变时长要填 0-%d 的整数毫秒（现在填的是 %r）" % (FADE_MAX_MS, raw)
    if v < 0 or v > FADE_MAX_MS:
        return False, "渐变时长必须在 0-%d 毫秒之间（现在填的是 %s）" % (FADE_MAX_MS, v)
    return True, v


# ----------------------------- pycaw 后端 -----------------------------


class _PycawBackend(object):
    """真的走后端：pycaw → Core Audio 会话。"""

    name = "pycaw"

    def __init__(self):
        from pycaw.pycaw import AudioUtilities
        self._AU = AudioUtilities

    def _sessions(self):
        try:
            return list(self._AU.GetAllSessions())
        except Exception as e:
            log("⚠ 枚举音频会话失败：%r" % (e,))
            return []

    def find(self, pid=None, proc=None):
        """找一路音频会话。返回 (handle, 当前音量 0..1) 或 None。"""
        want = (proc or "").strip().lower()
        for s in self._sessions():
            p = None
            try:
                p = s.Process                       # 程序已经退了会抛异常
            except Exception:
                p = None
            if p is None:
                continue
            try:
                name = (p.name() or "").lower()
                p_pid = int(p.pid)
            except Exception:
                continue
            if pid is not None and p_pid != int(pid):
                continue
            if pid is None and want and name != want:
                continue
            sav = getattr(s, "SimpleAudioVolume", None)
            if sav is None:
                continue
            try:
                return sav, float(sav.GetMasterVolume())
            except Exception:
                continue
        return None

    def set(self, handle, value_0_1):
        try:
            handle.SetMasterVolume(float(max(0.0, min(1.0, value_0_1))), None)
            return True
        except Exception as e:
            log("⚠ 设置音量失败：%r" % (e,))
            return False

    def list_processes(self):
        """现在有音频会话的程序：[(名字, 音量 0-100), ...]（同名只留第一路）。"""
        out = {}
        for s in self._sessions():
            try:
                p = s.Process                       # 程序已经退了会抛异常
                if p is None:
                    continue
                name = (p.name() or "").strip()
                sav = getattr(s, "SimpleAudioVolume", None)
                if not name or sav is None:
                    continue
                pct = int(round(float(sav.GetMasterVolume()) * 100))
            except Exception:
                continue
            if name.lower() not in out:
                out[name.lower()] = (name, pct)
        return sorted(out.values(), key=lambda x: x[0].lower())


_backend_cache = None
_backend_tried = False


def backend():
    """懒加载后端（只试一次；测试里可以替换这个函数或 reset_backend()）。"""
    global _backend_cache, _backend_tried
    if _backend_cache is None and not _backend_tried:
        _backend_tried = True
        if os.name == "nt":
            try:
                _backend_cache = _PycawBackend()
            except Exception as e:
                log("⚠ 读不到音频会话接口（没装 pycaw？）：%r" % (e,))
    return _backend_cache


def reset_backend():
    """清掉缓存（测试用）。"""
    global _backend_cache, _backend_tried
    _backend_cache = None
    _backend_tried = False


def available():
    return backend() is not None


# ----------------------------- 对外动作 -----------------------------


def _cancelled(cancel):
    """cancel 可以是 threading.Event，也可以是返回 bool 的函数。"""
    if cancel is None:
        return False
    try:
        if callable(cancel):
            return bool(cancel())
        return bool(cancel.is_set())
    except Exception:
        return False


def _pct_to_frac(pct):
    return max(0.0, min(1.0, float(pct) / 100.0))


def set_process_volume(proc, level, fade_ms=0, cancel=None, sleep=None, logger=None):
    """把 `proc`（进程名，例如 SCPSL.exe）的音量调到 `level`（0-100）。

    返回 (ok, 说明)。**没真调到就返回 False**（不谎报）。
    """
    say = logger or log
    slp = sleep or time.sleep
    proc = str(proc or "").strip()
    if not proc:
        return False, "没有填进程名"
    ok, lv = parse_level(level)
    if not ok:
        return False, lv
    ok, fade = parse_fade_ms(fade_ms)
    if not ok:
        return False, fade
    bk = backend()
    if bk is None:
        return False, "读不到音频会话接口（Windows 才有；本机可能没装 pycaw）"

    hit = bk.find(proc=proc)
    if hit is None:
        return False, "没找到 %s 的音频会话（程序没开，或它现在没在出声）" % proc
    handle, cur = hit

    if abs(cur - _pct_to_frac(lv)) < 0.005:            # 目标 == 当前 → 无效（用户要求）
        say("[vol] %s 音量本来就是 %d%%，跳过" % (proc, lv))
        return True, "%s 音量本来就是 %d%%，跳过" % (proc, lv)

    way = "渐弱" if lv < cur * 100 else "渐强"
    if fade <= 0:
        if not bk.set(handle, _pct_to_frac(lv)):
            return False, "设置 %s 音量失败" % proc
        return True, "已把 %s 音量设成 %d%%" % (proc, lv)

    steps = max(1, int(round(fade / float(STEP_MS))))
    per = (fade / 1000.0) / steps
    target = _pct_to_frac(lv)
    for i in range(1, steps + 1):
        if _cancelled(cancel):                          # 停在哪儿就说停在哪儿
            return False, "%s 音量%s到一半被打断（停在 %d%%）" % (
                proc, way, int(round(cur * 100)))
        slp(per)
        v = target if i == steps else cur + (target - cur) * (float(i) / steps)
        if not bk.set(handle, v):
            return False, "设置 %s 音量失败" % proc
        cur = v
    return True, "已把 %s 音量%s到 %d%%（%dms）" % (proc, way, lv, fade)


# ----------------------------- 后台渐变（不占用后续操作） -----------------------------

_fades = {}                        # proc(小写) -> FadeJob（只记每个程序最后一个渐变）
_fades_lock = threading.RLock()


class FadeJob(object):
    """一次后台渐变：自己走完，走完/被打断都写日志。"""

    def __init__(self, proc, level, fade_ms, cur, handle, bk):
        self.proc = proc
        self.level = int(level)
        self.fade_ms = int(fade_ms)
        self.start_pct = int(round(cur * 100))
        self.now_pct = self.start_pct
        self.handle = handle
        self.bk = bk
        self.stop_ev = threading.Event()
        self.done_ev = threading.Event()
        self.state = "排队中"                     # 排队中 / 已完成 / 被打断 / 失败 / 出错
        self.thread = None


def _way_of(level, start_pct):
    return "渐弱" if level < start_pct else "渐强"


def start_fade(proc, level, fade_ms=0, logger=None):
    """把 `proc` 的音量调到 `level`：0ms = 立刻切；>0 = **后台**渐变。

    返回 (ok, 说明)。后台渐变也是"已经开始了"才算成功（失败照样老实报）。
    """
    say = logger or log
    proc = str(proc or "").strip()
    if not proc:
        return False, "没有填进程名"
    ok, lv = parse_level(level)
    if not ok:
        return False, lv
    ok, fade = parse_fade_ms(fade_ms)
    if not ok:
        return False, fade
    bk = backend()
    if bk is None:
        return False, "读不到音频会话接口（Windows 才有；本机可能没装 pycaw）"

    hit = bk.find(proc=proc)
    if hit is None:
        return False, "没找到 %s 的音频会话（程序没开，或它现在没在出声）" % proc
    handle, cur = hit
    start_pct = int(round(cur * 100))

    if abs(cur - _pct_to_frac(lv)) < 0.005:               # 目标 == 当前 → 无效（用户要求）
        say("[vol] %s 音量本来就是 %d%%，跳过" % (proc, lv))
        return True, "%s 音量本来就是 %d%%，跳过" % (proc, lv)

    way = _way_of(lv, start_pct)
    if fade <= 0:
        if not bk.set(handle, _pct_to_frac(lv)):
            return False, "设置 %s 音量失败" % proc
        return True, "已把 %s 音量设成 %d%%" % (proc, lv)

    job = FadeJob(proc, lv, fade, cur, handle, bk)
    _hand_over(job, say)                                  # 同一程序的旧渐变让位给新的
    job.thread = threading.Thread(target=_run_fade, args=(job, say), daemon=True,
                                  name="fade-%s" % proc)
    job.thread.start()
    return True, "已开始把 %s 音量%s到 %d%%（%dms，后台执行，不占用后面的操作）" % (
        proc, way, lv, fade)


def _hand_over(job, say):
    """同一个程序的上一个渐变让位（新的说了算）。"""
    key = job.proc.lower()
    with _fades_lock:
        old = _fades.get(key)
        if old is not None and not old.done_ev.is_set():
            old.stop_ev.set()
            say("[vol] %s 上一个渐变让位（新目标 %d%%）" % (job.proc, job.level))
        _fades[key] = job


def _run_fade(job, say):
    """后台线程：线性走到目标，**每一步都精确落在算出来的值上**，最后一步正好是目标。"""
    steps = max(1, int(round(job.fade_ms / float(STEP_MS))))
    per = (job.fade_ms / 1000.0) / steps
    cur = _pct_to_frac(job.start_pct)
    target = _pct_to_frac(job.level)
    way = _way_of(job.level, job.start_pct)
    say("[vol] %s 开始%s到 %d%%（%dms，后台执行）" % (job.proc, way, job.level, job.fade_ms))
    try:
        for i in range(1, steps + 1):
            if job.stop_ev.wait(per):                     # 被新渐变接管 / 程序退出
                job.state = "被打断"
                say("[vol] %s 的渐变让位（停在 %d%%）" % (job.proc, job.now_pct))
                return
            v = target if i == steps else cur + (target - cur) * (float(i) / steps)
            if not job.bk.set(job.handle, v):
                job.state = "失败"
                say("⚠ [vol] %s 渐变失败（停在 %d%%）" % (job.proc, job.now_pct))
                return
            cur = v
            job.now_pct = int(round(cur * 100))
        job.state = "已完成"
        say("[vol] %s 已%s到 %d%%（%dms，后台执行完毕）" % (job.proc, way, job.level, job.fade_ms))
    except Exception as e:
        job.state = "出错"
        say("⚠ [vol] %s 渐变出错：%r" % (job.proc, e))
    finally:
        job.done_ev.set()


def fade_state(proc):
    """这个程序最后一个渐变的状态：返回 (状态, 现在音量) 或 None（自检 / 诊断用）。"""
    with _fades_lock:
        job = _fades.get(str(proc or "").strip().lower())
    return (job.state, job.now_pct) if job is not None else None


def wait_fades(timeout=5.0):
    """等所有后台渐变跑完（自检用）。返回是否**全部**结束。"""
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        with _fades_lock:
            jobs = [j for j in _fades.values() if not j.done_ev.is_set()]
        if not jobs:
            return True
        if time.monotonic() > deadline:
            return False
        jobs[0].done_ev.wait(0.02)


def stop_fades(why="程序退出", wait=2.0):
    """程序退出时：把还在跑的渐变停掉（不留在后台偷偷改音量）。返回停掉的个数。"""
    with _fades_lock:
        jobs = [j for j in _fades.values() if not j.done_ev.is_set()]
    for j in jobs:
        j.stop_ev.set()
    for j in jobs:
        j.done_ev.wait(max(0.0, float(wait)))
    if jobs:
        log("[vol] %s：停掉 %d 个还在跑的渐变" % (why, len(jobs)))
    return len(jobs)


def list_processes():
    """现在**有声音的程序**：[(名字, 音量 0-100), ...]（给「选进程」用）。"""
    bk = backend()
    fn = getattr(bk, "list_processes", None)
    if fn is None:
        return []
    try:
        return list(fn())
    except Exception as e:
        log("⚠ 列音频进程失败：%r" % (e,))
        return []
