# -*- coding: utf-8 -*-
"""托盘：绿点 = 存活（媒体已按复活后的配置处理），红点 = 死亡·观察者。

* 左键点图标 = 显示界面（右键 = 菜单，系统默认行为）。
* 菜单：显示界面 / 隐藏界面 / 手动对齐媒体状态（播放/暂停，只改程序内状态）/ 退出。
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

import config as cfgmod
from ui import icons


class Tray(QObject):
    show_requested = Signal()
    hide_requested = Signal()
    manual_play = Signal()
    manual_pause = Signal()
    quit_requested = Signal()

    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self.icon = QSystemTrayIcon(icons.state_icon("dead"), parent)
        self.icon.setToolTip("%s v%s" % (cfgmod.APP_TITLE, cfgmod.VERSION))

        menu = QMenu()
        menu.addAction("显示界面", self.show_requested.emit)
        menu.addAction("隐藏界面", self.hide_requested.emit)
        menu.addSeparator()
        menu.addAction("手动设置：当前媒体处于播放状态", self.manual_play.emit)
        menu.addAction("手动设置：当前媒体处于暂停状态", self.manual_pause.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)
        self.menu = menu
        self.icon.setContextMenu(menu)

        self.icon.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_requested.emit()

    def show(self):
        self.icon.show()

    def set_state(self, state, reason=""):
        alive = (state == "alive")
        self.icon.setIcon(icons.state_icon(state))
        self.icon.setToolTip("%s v%s\n状态：%s%s"
                             % (cfgmod.APP_TITLE, cfgmod.VERSION,
                                "存活" if alive else "死亡·观察者",
                                ("（%s）" % reason) if reason else ""))

    def notify(self, title, msg):
        try:
            self.icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 4000)
        except Exception:
            pass
