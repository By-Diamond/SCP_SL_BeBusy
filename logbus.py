# -*- coding: utf-8 -*-
"""
日志总线（无界面）：一条日志同时给 文件 + UI 订阅者（+ 可选控制台）
====================================================================

* 文件：默认按大小轮转（`xxx.log` → `xxx.log.1` → `xxx.log.2` …），可热切换路径。
* UI：`subscribe(cb)`，回调签名 `cb(line, level)`；回调异常不影响写文件。
* 分级 `level`：`error`（含 ⚠/❌/失败/错误/异常）/ `key`（动作、门、状态、配置等关键行）/ `info`。
* 线程安全：所有写入在锁内；订阅回调在锁**外**调用（UI 侧只应把它塞进队列）。

`is_key(level)` / `is_error(level)` 给 UI 的「级别过滤」用。
"""

import os
import threading
import time

KEY_TAGS = ("[action]", "[gate]", "[state]", "[op]", "[manual]", "[cfg]",
            "[tray]", "[media]", "[hook]", "[start]")
ERR_TAGS = ("⚠", "❌", "失败", "出错", "错误", "异常")

LEVELS = ("all", "key", "error")


def classify(text):
    t = text or ""
    for k in ERR_TAGS:
        if k in t:
            return "error"
    for k in KEY_TAGS:
        if k in t:
            return "key"
    return "info"


def is_key(level):
    return level in ("key", "error")


def is_error(level):
    return level == "error"


class LogBus:
    def __init__(self, path="", max_bytes=5 * 1024 * 1024, backups=2,
                 echo=False, timestamp=True):
        self.lock = threading.RLock()
        self.path = path or ""
        self.max_bytes = int(max_bytes or 0)
        self.backups = max(0, int(backups or 0))
        self.echo = bool(echo)
        self.timestamp = bool(timestamp)
        self._subs = []
        self._f = None
        self.last_error = ""
        self._open()

    # ---------------- 文件 ----------------

    def _open(self):
        self._close_file()
        if not self.path:
            return
        try:
            d = os.path.dirname(self.path) or "."
            os.makedirs(d, exist_ok=True)
            self._f = open(self.path, "a", encoding="utf-8", newline="\n")
        except Exception as e:
            self._f = None
            self.last_error = "日志文件打开失败：%r" % (e,)

    def _close_file(self):
        if self._f:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None

    def _rotate_if_needed(self):
        if not self._f or not self.max_bytes:
            return
        try:
            size = self._f.tell()
        except Exception:
            return
        if size < self.max_bytes:
            return
        self._close_file()
        try:
            for i in range(self.backups - 1, 0, -1):
                src = "%s.%d" % (self.path, i)
                dst = "%s.%d" % (self.path, i + 1)
                if os.path.exists(src):
                    os.replace(src, dst)
            if self.backups >= 1 and os.path.exists(self.path):
                os.replace(self.path, self.path + ".1")
        except Exception as e:
            self.last_error = "日志轮转失败：%r" % (e,)
        self._open()

    def set_path(self, path):
        """热切换日志文件（原文件留着）。"""
        with self.lock:
            self.path = path or ""
            self._open()
        return self.path

    def reload_settings(self, path, max_mb=None, backups=None):
        with self.lock:
            if max_mb is not None:
                self.max_bytes = int(float(max_mb) * 1024 * 1024)
            if backups is not None:
                self.backups = max(0, int(backups))
            if path and os.path.normcase(path) != os.path.normcase(self.path or ""):
                self.path = path
                self._open()
        return self.path

    def close(self):
        with self.lock:
            self._close_file()

    # ---------------- 订阅 ----------------

    def subscribe(self, cb):
        with self.lock:
            if cb not in self._subs:
                self._subs.append(cb)
        return cb

    def unsubscribe(self, cb):
        with self.lock:
            if cb in self._subs:
                self._subs.remove(cb)

    # ---------------- 写入 ----------------

    def log(self, msg, level=None, write_file=True):
        text = msg if isinstance(msg, str) else str(msg)
        lvl = level or classify(text)
        stamp = time.strftime("%H:%M:%S")
        line = "[%s] %s" % (stamp, text) if self.timestamp else text
        with self.lock:
            if write_file and self._f:
                try:
                    self._rotate_if_needed()
                    if self._f:
                        self._f.write(line + "\n")
                        self._f.flush()
                except Exception as e:
                    self.last_error = "日志写入失败：%r" % (e,)
            subs = list(self._subs)
        if self.echo:
            try:
                print(line)
            except Exception:
                pass
        for cb in subs:
            try:
                cb(line, lvl)
            except Exception:
                pass
        return line
