# -*- coding: utf-8 -*-
"""Qt 信号桥：把**后台线程**里的事件安全地送进界面线程。"""

from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """后台线程 emit，界面线程收（Qt 自动排队，不会跨线程碰控件）。"""

    log_line = Signal(str, str)          # (文本, 级别 all/key/error)
    state_changed = Signal(str, str, str)  # (state, reason, detail)
    ops_changed = Signal()               # 动作列表被改动
