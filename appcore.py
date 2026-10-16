# -*- coding: utf-8 -*-
"""
应用内核（**无界面**）：把 判定 / 触发门 / 动作列表 / 配置 / 日志 串起来
======================================================================

界面（PySide6）只做两件事：**显示** + **调用这里的方法**。
所以「死亡 → 跑列表」「0.7s 门」「热生效」这些逻辑都能在没有 Qt 的环境里被测到。

职责
----
* 持有 `Config` / `LogBus` / `AudioBackend` / `Trigger` / `Detector`
* `on_change` / `on_death_seen` → Trigger（0.7s 门）
* Trigger 到点 → `operations.run_list(配置里的动作列表)`
* 配置改动 → **立即生效**（日志路径、日志文件、开机自启动、Player.log 热切换）
* 状态变化 → 回调 `on_state`（界面拿去改托盘图标 / 状态栏）
"""

import os
import threading
import time

import audio_actions
import autostart
import config as cfgmod
import logbus as logmod
import operations
import scpsl_state
import trigger as triggermod
import win32_window

HERE = os.path.dirname(os.path.abspath(__file__))


class AppCore:
    def __init__(self, cfg=None, log_bus=None):
        self.cfg = cfg if cfg is not None else cfgmod.Config()
        self.log = log_bus if log_bus is not None else logmod.LogBus()
        self.log.set_path(cfgmod.effective_log_file(self.cfg))
        self.log.reload_settings(self.log.path,
                                 self.cfg.get("log_max_mb"),
                                 self.cfg.get("log_backups"))

        # 所有模块的日志都汇到总线（文件 + 界面）
        for mod in (audio_actions, operations, triggermod, scpsl_state, win32_window):
            if hasattr(mod, "set_logger"):
                mod.set_logger(self.log.log)

        self.audio = audio_actions.AudioBackend(logger=self.log.log)
        self.trigger = triggermod.Trigger(is_dead=self._is_dead,
                                         run_death=self._on_death_fired,
                                         run_alive=self._on_alive_fired,
                                         logger=self.log.log)
        self.detector = None
        self.state = scpsl_state.STATE_DEAD
        self.started = False
        self._stopped = False
        # 界面挂钩（由 UI 设置）
        self.on_state = None            # (state, reason, detail)
        self.on_ops_changed = None      # ()

    # ================= 生命周期 =================

    def start(self):
        if self.started:
            return
        self.started = True
        self.log.log("[start] %s v%s 启动" % (cfgmod.APP_TITLE, cfgmod.VERSION))
        self.log.log("[start] 配置文件：%s" % self.cfg.path)
        self.log.log("[start] 日志文件：%s" % self.log.path)
        if self.cfg.last_error:
            self.log.log("⚠ %s" % self.cfg.last_error)
        if self.cfg.loaded:
            self.log.log("[start] 配置已加载（death_ops=%d 条，alive_ops=%d 条）"
                         % (len(self.cfg.ops("death")), len(self.cfg.ops("alive"))))
        else:
            self.log.log("[start] 首次运行：用默认配置（死亡后=媒体播放，复活后=媒体暂停）")
            try:
                self.cfg.save()                     # 落一份 settings.json，方便用户直接看/改
                self.log.log("[start] 已写出默认配置文件：%s" % self.cfg.path)
            except Exception as e:
                self.log.log("⚠ 默认配置写出失败：%r" % (e,))
        self.audio.start()
        self._apply_autostart()
        self._start_detector()
        self.log.log("[start] 就绪：死亡/复活会自动执行各自的动作列表")

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            self.trigger.cancel()
        except Exception:
            pass
        try:
            self.audio.stop()
        except Exception:
            pass
        self._stop_detector()
        try:
            self.log.log("[start] 退出程序")
            self.log.close()
        except Exception:
            pass
        self.started = False

    # ================= 判定核心 =================

    def _start_detector(self):
        plog, exists = self.player_log_now()
        scpsl_state.PLAYER_LOG = plog
        # state_log.csv 放到配置目录（打包成 exe 时 __file__ 在临时解压目录里，会随退出被删）
        try:
            scpsl_state.STATE_LOG = os.path.join(os.path.dirname(self.cfg.path) or ".",
                                                 "state_log.csv")
        except Exception:
            pass
        self.log.log("[start] Player.log：%s%s"
                     % (plog or "（未指定）", "" if exists else "（文件当前不存在，等游戏写）"))
        self.detector = scpsl_state.Detector(
            on_change=self._on_change, on_death_seen=self._on_death_seen)
        self.detector.start()

    def _stop_detector(self):
        det, self.detector = self.detector, None
        if det is None:
            return
        try:
            det.stop_all()
        except Exception:
            pass
        time.sleep(0.35)                     # 等旧钩子线程退出（避免两个钩子同时在场）
        try:
            if det._f_log:                   # 关掉旧的状态日志句柄
                det._f_log.close()
        except Exception:
            pass

    def _on_change(self, state, reason, detail):
        self.state = state
        if state == scpsl_state.STATE_ALIVE:
            self.trigger.on_alive(reason, detail)
        if self.on_state:
            try:
                self.on_state(state, reason, detail)
            except Exception as e:
                self.log.log("⚠ 界面状态回调出错：%r" % (e,))

    def _on_death_seen(self, reason, detail):
        self.trigger.on_death(reason, detail)

    def _on_note(self, reason, detail):
        pass

    def _is_dead(self):
        det = self.detector
        return bool(det and det.state == scpsl_state.STATE_DEAD)

    def game_hwnd(self):
        return int(getattr(self.detector, "scpsl_hwnd", 0) or 0)

    # ================= 动作列表 =================

    def op_context(self):
        return operations.OpContext(audio=self.audio,
                                    hwnd=self.game_hwnd,
                                    logger=self.log.log)

    def _on_death_fired(self, reason, detail):
        operations.run_list(self.cfg.ops("death"), self.op_context(), label="[死亡后]")

    def _on_alive_fired(self, reason, detail):
        operations.run_list(self.cfg.ops("alive"), self.op_context(), label="[复活后]")

    def save_ops(self, which, items):
        """界面改了列表 → 立即写配置（下次触发就用新的）。"""
        canon = []
        for i in items:
            n = operations.normalize_item(i)
            if n:
                canon.append(n)
        self.cfg.set_ops(which, canon)
        self.cfg.save()
        if self.on_ops_changed:
            try:
                self.on_ops_changed()
            except Exception:
                pass
        self.log.log("[cfg] 已保存「%s」动作列表（%d 条）：%s"
                     % ("死亡后" if which == "death" else "复活后", len(canon),
                        "、".join(operations.describe_item(i) for i in canon) or "空"))
        return canon

    # ================= 手动（托盘菜单） =================

    def manual_play(self):
        self.log.log("[manual] 手动：媒体播放")
        return operations.run_list([operations.new_item("media_play")],
                                   self.op_context(), label="[手动]")

    def manual_pause(self):
        self.log.log("[manual] 手动：媒体暂停")
        return operations.run_list([operations.new_item("media_pause")],
                                   self.op_context(), label="[手动]")

    def manual_test_ops(self, which):
        """手动跑一遍某个列表（界面上的「试跑」按钮）。"""
        items = self.cfg.ops(which)
        self.log.log("[manual] 手动试跑「%s」动作列表（%d 条）"
                     % ("死亡后" if which == "death" else "复活后", len(items)))
        return operations.run_list(items, self.op_context(), label="[手动试跑]")

    # ================= 配置热生效 =================

    def player_log_now(self):
        return cfgmod.effective_player_log(self.cfg)

    def set_player_log_path(self, path):
        """改 Player.log 路径 → 立即重挂监听。返回 (ok, 说明)。"""
        path = (path or "").strip()
        self.cfg.set("player_log", path)
        self.cfg.save()
        plog, exists = self.player_log_now()
        if path and not exists:
            msg = "已保存路径，但文件当前不存在：%s（游戏运行后会自动出现）" % plog
        else:
            msg = "已切换 Player.log：%s" % (plog or "（未指定）")
        self.log.log("[cfg] %s" % msg)
        self._stop_detector()
        self._start_detector()
        return True, msg

    def autodetect_player_log(self):
        """自动识别并落盘。返回 (path, exists, 说明)。"""
        path, exists, how = cfgmod.autodetect_player_log()
        if path:
            self.cfg.set("player_log", path)
            self.cfg.save()
            self.log.log("[cfg] Player.log %s：%s" % (how, path))
            self._stop_detector()
            self._start_detector()
        return path, exists, how

    def set_log_file(self, path="", max_mb=None, backups=None):
        """改日志文件路径/大小上限（立即生效）。"""
        self.cfg.set("log_file", (path or "").strip())
        if max_mb is not None:
            self.cfg.set("log_max_mb", int(max_mb))
        if backups is not None:
            self.cfg.set("log_backups", int(backups))
        self.cfg.save()
        target = cfgmod.effective_log_file(self.cfg)
        self.log.reload_settings(target, self.cfg.get("log_max_mb"),
                                 self.cfg.get("log_backups"))
        self.log.log("[cfg] 日志文件已切换：%s（上限 %sMB × %s 份）"
                     % (target, self.cfg.get("log_max_mb"), self.cfg.get("log_backups")))
        return target

    def set_config_location(self, path):
        """迁移配置文件位置（立即生效）。返回 (ok, 说明)。"""
        saved, msg = self.cfg.move_to(path)
        if not saved:
            self.log.log("⚠ 配置迁移失败：%s" % msg)
            return False, msg
        self.log.log("[cfg] %s" % msg)
        return True, msg

    def reset_config_location(self):
        saved, msg = self.cfg.reset_location()
        self.log.log("[cfg] %s" % msg)
        return True, msg

    def set_autostart(self, enabled):
        """开/关开机自启动（立即写注册表）。返回 (ok, 说明)。"""
        enabled = bool(enabled)
        ok, msg = autostart.apply(enabled)
        # 失败就把配置回退到原来的状态，避免「界面说关了、配置说开着」
        self.cfg.set("autostart", enabled if ok else (not enabled))
        self.cfg.save()
        self.log.log("[cfg] %s" % msg if ok else "⚠ %s" % msg)
        return ok, msg

    def _apply_autostart(self):
        want = bool(self.cfg.get("autostart"))
        ok, msg = autostart.apply(want)
        self.log.log("[start] 开机自启动：%s" % msg if ok else "⚠ 开机自启动：%s" % msg)
        return ok, msg

    def set_open_url_default(self, url):
        self.cfg.set("open_url_default", (url or "").strip())
        self.cfg.save()
        self.log.log("[cfg] 「打开网页」默认网址：%s" % self.cfg.get("open_url_default"))
        return self.cfg.get("open_url_default")

    def set_ui_state(self, **kw):
        ui = dict(self.cfg.get("ui") or {})
        ui.update(kw)
        self.cfg.set("ui", ui)
        self.cfg.save()
        return ui

    # ================= 诊断信息（关于页「复制」用） =================

    def diagnostics(self):
        st = autostart.status()
        plog, exists = self.player_log_now()
        lines = [
            "%s v%s（%s）" % (cfgmod.APP_TITLE, cfgmod.VERSION, cfgmod.APP_NAME),
            cfgmod.DESCRIPTION,
            "作者：%s" % cfgmod.AUTHOR,
            "",
            "配置文件：%s（存在=%s）" % (self.cfg.path, os.path.isfile(self.cfg.path)),
            "日志文件：%s" % self.log.path,
            "Player.log：%s（存在=%s）" % (plog, exists),
            "开机自启动：%s" % ("已开启" if st["enabled"] else "未开启"),
            "注册表命令：%s" % (st["registered"] or st["wanted"]),
            "运行方式：%s" % ("打包 exe" if cfgmod.is_frozen() else "源码"),
            "当前状态：%s" % ("存活" if self.state == scpsl_state.STATE_ALIVE else "死亡·观察者"),
            "媒体状态：%s" % self.audio.state_text(),
            "死亡后动作：%s" % (self._describe_ops("death") or "（空）"),
            "复活后动作：%s" % (self._describe_ops("alive") or "（空）"),
        ]
        return "\n".join(lines)

    def _describe_ops(self, which):
        return " → ".join(operations.describe_item(i) for i in self.cfg.ops(which))
