# -*- coding: utf-8 -*-
"""
触发门（无界面）：把「死亡 / 复活」变成「跑一遍动作列表」
=========================================================

* **死亡**：起一个 `DEATH_SETTLE_S`（0.7s）的稳定门；到点时状态仍是死亡才跑「死亡后」列表。
  这 0.7s 内复活 → **一点都不跑**（这是用户要求的行为）。
* **复活**：**立即**跑「复活后」列表，同时取消未到期的死亡门。
* **启动不动作**：程序刚起来时并不知道真实状态，所以「第一次判存活」不跑列表
  （不打扰用户正在放的音乐）；第一次死亡行照常跑（那是真事件）。
* **去重**：`applied` 记住最后一次跑过哪个列表，同一方向不重复跑（比如同一秒两条死亡行）。
* 所有回调都在**锁外**执行（不会和判定线程互相卡住）。
"""

import threading

DEATH_SETTLE_S = 0.7

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


class Trigger:
    """把状态信号变成动作列表执行。`is_dead` 是可调用对象（返回当前是否死亡）。"""

    def __init__(self, is_dead, run_death, run_alive,
                 settle_s=DEATH_SETTLE_S, logger=None):
        self.is_dead = is_dead
        self.run_death = run_death
        self.run_alive = run_alive
        self.settle_s = float(settle_s)
        self.log = logger if logger is not None else log
        self.lock = threading.RLock()
        self.timer = None
        self.applied = None            # None / "dead" / "alive"
        self.death_reason = ""

    # ---------------- 内部 ----------------

    def _cancel_locked(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
            return True
        return False

    def cancel(self):
        with self.lock:
            return self._cancel_locked()

    # ---------------- 事件 ----------------

    def on_death(self, reason="", detail=""):
        """死亡信号（Player.log 死亡行）：起 0.7s 稳定门。"""
        with self.lock:
            self._cancel_locked()
            self.death_reason = reason
            t = threading.Timer(self.settle_s, self._fire_death)
            t.daemon = True
            self.timer = t
            t.start()
        self.log("[gate] 死亡信号（%s）→ 等 %.1fs 确认；这期间复活则完全不动作"
                 % (reason or "?", self.settle_s))

    def on_alive(self, reason="", detail=""):
        """存活信号（REDRAW）：立即跑「复活后」列表；取消未到期的死亡门。"""
        with self.lock:
            cancelled = self._cancel_locked()
            if self.applied == "dead":
                self.applied = "alive"
                act = True
            elif self.applied is None:
                self.applied = "alive"           # 启动至今没动过 → 不打扰
                act = False
            else:
                act = False
        if act:
            if cancelled:
                self.log("[gate] 死亡门未到期就复活 → 取消死亡动作，改跑「复活后」列表")
            self.log("[action] 复活（%s）→ 执行「复活后」动作列表" % (reason or "?",))
            self._safe(self.run_alive, reason, detail)
        else:
            self.log("[gate] 复活（%s）：程序还没动过 → 不动作" % (reason or "?",))

    def _fire_death(self):
        with self.lock:
            self.timer = None
        if not self.is_dead():
            self.log("[gate] 死亡后 %.1fs 内状态已变（复活）→ 取消，不作任何操作"
                     % self.settle_s)
            return
        with self.lock:
            if self.applied == "dead":
                return
            self.applied = "dead"
        self.log("[action] 死亡保持 %.1fs 未复活 → 执行「死亡后」动作列表" % self.settle_s)
        self._safe(self.run_death, self.death_reason, "")

    @staticmethod
    def _safe(fn, *args):
        try:
            fn(*args)
        except Exception as e:
            log("⚠ 动作列表执行出错：%r" % (e,))

    # ---------------- 手动 ----------------

    def reset(self):
        """清掉「跑过哪个列表」的记忆（测试 / 手动复位用）。"""
        with self.lock:
            self._cancel_locked()
            self.applied = None
