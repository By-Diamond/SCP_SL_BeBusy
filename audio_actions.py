# -*- coding: utf-8 -*-
"""
媒体层（无界面）：系统媒体键 + 「播放/暂停」的信仰状态
======================================================

* `send_media_play_pause()`：发一次 Windows 媒体键（VK 0xB3），**盲发**（和以前一样）。
* `AudioBackend`：把发键动作放到**独立线程**执行（不阻塞判定回调、不阻塞 UI）。
* **播放 / 暂停语义**：媒体键是**一个切换键**，所以这里记住「我们最后一次知道的状态」
  （`playing`：True 播放中 / False 暂停中 / None 未知），
  `play()` 只在"确信不是播放中"时才发键，`pause()` 只在"确信不是暂停中"时才发键
  —— 这样「播放」不会被按成暂停（**播放不能播放两次**），反之亦然。
* 状态未知时按需要发键（和以前盲发的行为一致）；用户用手动播放/暂停对齐即可。
* 键**没发出去**（非 Windows / 发键失败）时，信仰状态退回「未知」—— 不谎报成播放/暂停。
* 若要更精确（能查询播放器真实状态），将来可接 SMTC；本版按用户要求沿用现有媒体键。
"""

import ctypes
import queue
import threading

MEDIA_PLAY_PAUSE_VK = 0xB3

try:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.keybd_event.argtypes = [
        ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_void_p
    ]
    _user32.keybd_event.restype = None
except Exception:
    _user32 = None                       # 非 Windows / 测试环境

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


def send_media_play_pause():
    """发一次媒体播放/暂停键。返回是否真的发了。"""
    if _user32 is None:
        log("⚠ 非 Windows 环境：媒体键未发送")
        return False
    _user32.keybd_event(MEDIA_PLAY_PAUSE_VK, 0, 0, 0)      # 按下
    _user32.keybd_event(MEDIA_PLAY_PAUSE_VK, 0, 2, 0)      # 抬起
    return True


class AudioBackend:
    """媒体键执行器：独立线程 + 播放状态记忆。"""

    def __init__(self, logger=None):
        self.q = queue.Queue()
        self._thread = None
        self._started = False
        self.log = logger if logger is not None else log
        self.lock = threading.RLock()
        self.playing = None               # None 未知 / True 播放中 / False 暂停中

    # ---------------- 线程 ----------------

    def start(self):
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="media")
        self._thread.start()

    def _worker(self):
        while True:
            job = self.q.get()
            try:
                if job is None:
                    return
                job()
            except Exception as e:
                self.log("⚠ 媒体键动作出错：%r" % (e,))
            finally:
                self.q.task_done()

    def _post(self, fn):
        if not self._started:                     # 未启动也能用（同步兜底）
            fn()
            return
        self.q.put(fn)

    def stop(self):
        if self._started:
            self.q.put(None)

    def wait_idle(self, timeout=2.0):
        """等队列里的动作跑完（自检 / 测试用）。"""
        if not self._started:
            return True
        done = threading.Event()
        self.q.put(done.set)
        return done.wait(timeout)

    # ---------------- 动作 ----------------

    def _send(self, note=""):
        ok = send_media_play_pause()
        suffix = ("（%s）" % note) if note else ""
        if ok:
            self.log("[media] 已发媒体播放/暂停键%s" % suffix)
        else:
            self.log("⚠ 媒体键未发送%s" % suffix)
        return ok

    def _confirm(self, ok, believed):
        """键**真的发出去了**才保留信仰状态；发失败就退回「未知」——不谎报。"""
        if ok:
            return
        with self.lock:
            if self.playing is believed:
                self.playing = None
        self.log("[media] 键没发成功 → 媒体状态退回「未知」（不是播放/暂停）")

    def play(self, note=""):
        """确保**播放**。已在播放（确信）则跳过。返回是否发了键。"""
        with self.lock:
            if self.playing is True:
                self.log("[media] 已在播放，跳过（不重复按，避免按成暂停）")
                return False
            self.playing = True
        self._post(lambda: self._confirm(self._send(note or "播放"), True))
        return True

    def pause(self, note=""):
        """确保**暂停**。已暂停（确信）则跳过。返回是否发了键。"""
        with self.lock:
            if self.playing is False:
                self.log("[media] 已在暂停，跳过（不重复按）")
                return False
            self.playing = False
        self._post(lambda: self._confirm(self._send(note or "暂停"), False))
        return True

    def toggle(self, note=""):
        """不判断状态，直接切一下（托盘手动测试用）。"""
        with self.lock:
            self.playing = (not self.playing) if self.playing is not None else None
            believed = self.playing
        self._post(lambda: self._confirm(self._send(note or "切换"), believed))
        return True

    # ---------------- 状态 ----------------

    def mark(self, playing):
        """手动对齐信仰状态（None/True/False）。"""
        with self.lock:
            self.playing = playing
        return playing

    def state_text(self):
        with self.lock:
            return {None: "未知", True: "播放中", False: "暂停中"}[self.playing]
