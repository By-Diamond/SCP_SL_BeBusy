# -*- coding: utf-8 -*-
"""主窗口：左侧导航 + 右侧页面栈；状态栏显示存活/死亡、Player.log、媒体状态。

* 点 ✕ = **隐藏到托盘**（不退出）；退出走托盘菜单。
* 「页面」顺序：日志 / 功能配置 / 设置 / 关于。
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QMainWindow,
                               QStackedWidget, QWidget)

import config as cfgmod
from ui import util
from ui.page_about import AboutPage
from ui.page_features import FeaturePage
from ui.page_log import LogPage
from ui.page_settings import SettingsPage

PAGES = ("日志", "功能配置", "设置", "关于")


class MainWindow(QMainWindow):
    hidden_to_tray = Signal()

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self._really_quit = False
        self._told_about_tray = False

        self.setWindowTitle("%s v%s" % (cfgmod.APP_TITLE, cfgmod.VERSION))
        self.resize(980, 660)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setFixedWidth(150)
        self.nav.addItems(PAGES)
        self.nav.setCurrentRow(0)
        layout.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.log_page = LogPage(core)
        self.feature_page = FeaturePage(core)
        self.settings_page = SettingsPage(core)
        self.about_page = AboutPage(core)
        for w in (self.log_page, self.feature_page, self.settings_page, self.about_page):
            self.stack.addWidget(w)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._on_nav)
        try:
            self.nav.setCurrentRow(int((core.cfg.get("ui") or {}).get("page", 0) or 0))
        except Exception:
            self.nav.setCurrentRow(0)

        # 状态栏
        self._alive = False
        self._plog_found = False
        self._plog_path = None
        self.lbl_state = QLabel()
        self.lbl_plog = QLabel()
        self.lbl_media = QLabel()
        self.lbl_media.setToolTip(util.MEDIA_TIP)
        sb = self.statusBar()
        sb.setStyleSheet(
            "QStatusBar::item { border: none; }"            # 去掉 Qt 自带那道贴着文字的竖线
            "QStatusBar QLabel { padding-left: 6px; padding-right: 6px; }")
        sb.addWidget(self.lbl_state)
        sb.addPermanentWidget(self.lbl_media)
        sb.addPermanentWidget(self.lbl_plog)
        self.refresh_status()

        # 每秒刷一次状态栏：媒体键是我们自己发的（系统不通知界面），
        # Player.log 也可能在小窗起来之后才出现 —— 光等「状态变化」会一直显示旧值。
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

    # ---------------- 页面 ----------------

    def _on_nav(self, row):
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            if row == 0:
                self.log_page.refresh_path_label()
            elif row == 1:
                self.feature_page.sync_from_config()
            elif row == 2:
                self.settings_page.refresh()
            elif row == 3:
                self.about_page.refresh()
        try:
            self.core.set_ui_state(page=int(row))
        except Exception:
            pass

    # ---------------- 状态 ----------------

    def set_state(self, state, reason="", detail=""):
        self._alive = (state == "alive")
        tip = "存活" if self._alive else "死亡·观察者"
        self.setWindowTitle("%s v%s — %s" % (cfgmod.APP_TITLE, cfgmod.VERSION, tip))
        self.refresh_status()

    def refresh_status(self):
        """状态栏全刷：状态 / 媒体 / Player.log（定时器 + 状态变化 + 显示窗口时都会调）。"""
        try:
            path, exists = self.core.player_log_now()
        except Exception as e:
            path, exists = "", False
            self._log("⚠ 读 Player.log 状态失败：%r" % (e,))
        self._plog_found = bool(exists)
        if (path or "") != self._plog_path:            # 没变就别每秒重设一遍提示
            self._plog_path = path or ""
            self.lbl_plog.setToolTip(self._plog_path)
        self._paint_status()

    def refresh_media(self):
        """只刷状态栏（刚发过媒体键时用，不碰文件系统）。"""
        self._paint_status()

    def _paint_status(self):
        t = util.status_texts(self._alive, self._plog_found, self._media_text())
        self.lbl_state.setText(t["state"])
        self.lbl_media.setText(t["media"])
        self.lbl_plog.setText(t["plog"])

    def _media_text(self):
        try:
            return self.core.audio.state_text()
        except Exception as e:
            self._log("⚠ 读媒体状态失败：%r" % (e,))
            return "未知"

    def _log(self, msg):
        try:
            self.core.log.log(msg)
        except Exception:
            pass

    def append_log(self, line, level="info"):
        """由 Bridge 信号调用（永远在界面线程）。"""
        self.log_page.append_line(line, level)
        if line.startswith("[media]"):
            self.refresh_media()        # 我们自己发的媒体键 → 状态栏那栏立刻跟上

    # ---------------- 窗口 ----------------

    def show_and_raise(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.refresh_status()

    def force_close(self):
        self._really_quit = True
        self.close()

    def closeEvent(self, event):
        if self._really_quit:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.hidden_to_tray.emit()
