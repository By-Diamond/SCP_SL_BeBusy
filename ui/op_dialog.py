# -*- coding: utf-8 -*-
"""「添加操作」弹窗 + 参数询问（网址 / 窗口 / 文件）。

* **默认选中第一个「可用」的操作**（不是第一项 —— 第一项可能因为"同框已有一条"被置灰，
  焦点落在灰项上会让用户以为"添加没反应"）。
* 一个都不能加时：禁用「添加」按钮 + 明确提示。
* 有必填参数的操作（「打开网页」的网址、「切换到界面」的窗口、「执行文件」的文件）
  选完后由 `ask_param()` 按参数键弹对应的窗口问。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout)

import config as cfgmod
import operations
import win32_window


def ask_url(parent, default=""):
    """问用户要一个网址。返回 (url, 是否已作答)。"""
    text, answered = QInputDialog.getText(
        parent, "打开网页", "网址（例如 https://www.bilibili.com）：", text=default or "")
    if not answered:
        return "", False
    return (text or "").strip(), True


def ask_text(parent, label, default="", hint=""):
    """普通文字输入（新参数忘了配专用弹窗时的兜底）。"""
    tip = ("%s（%s）：" % (label, hint)) if hint else ("%s：" % label)
    text, answered = QInputDialog.getText(parent, label, tip, text=default or "")
    if not answered:
        return "", False
    return (text or "").strip(), True


class WindowPickerDialog(QDialog):
    """选窗口：列出当前所有窗口（标题 — 进程名），也能直接手打标题/进程名。"""

    def __init__(self, parent=None, default=""):
        super().__init__(parent)
        self.setWindowTitle("选择窗口")
        self.resize(540, 420)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("填标题或进程名（双击下面的窗口 = 用它）："))

        self.ed = QLineEdit(default or "")
        self.ed.setPlaceholderText("例如 chrome.exe")
        root.addWidget(self.ed)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._pick)
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.reload)
        row.addWidget(self.btn_refresh)
        self.count = QLabel("")
        row.addWidget(self.count)
        row.addStretch(1)
        root.addLayout(row)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        root.addWidget(self.box)

        self.reload()

    def reload(self):
        """重新枚举当前窗口（开了/关了程序，点「刷新」）。"""
        try:
            wins = list(win32_window.list_windows())
        except Exception:
            wins = []
        self.list.clear()
        n = 0
        for hwnd, title, proc in wins:
            title = (title or "").strip()
            proc = (proc or "").strip()
            if not title or cfgmod.APP_TITLE in title:
                continue                                  # 跳过没标题的窗口和本程序自己
            text = ("%s    — %s" % (title, proc)) if proc else title
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, proc or title)
            self.list.addItem(item)
            n += 1
        self.count.setText("共 %d 个窗口" % n if n else "没找到窗口，直接在上面输入")

    def _pick(self, item):
        """双击 = 用它的**进程名**（标题会随内容变，进程名更稳）。"""
        v = (item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""
        if v:
            self.ed.setText(v)
        self.accept()

    def chosen(self):
        return self.ed.text().strip()


def ask_window(parent, default=""):
    """问用户要一个窗口（标题或进程名）。返回 (target, 是否已作答)。"""
    dlg = WindowPickerDialog(parent, default)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return "", False
    return dlg.chosen(), True


def ask_file(parent, default=""):
    """问用户要一个文件（像双击一样打开）。返回 (path, 是否已作答)。"""
    start = ""
    if default:
        start = default if os.path.isdir(default) else (os.path.dirname(default) or "")
    path, _flt = QFileDialog.getOpenFileName(parent, "选择文件", start, "所有文件 (*.*)")
    if not path:
        return "", False
    return path, True


ASKERS = {
    "url": ask_url,           # 网址 → 输入框
    "target": ask_window,     # 窗口 → 带上「当前窗口列表」的选择弹窗
    "path": ask_file,         # 文件 → 系统文件选择框
}


def ask_param(parent, key, label, default="", hint=""):
    """按参数键问用户。返回 (值, 是否已作答)。"""
    fn = ASKERS.get(key)
    if fn is not None:
        return fn(parent, default)
    return ask_text(parent, label, default, hint)


def item_enabled(item):
    """列表项现在是否可点（没被置灰）。"""
    if item is None:
        return False
    try:
        return bool(item.flags() & Qt.ItemFlag.ItemIsEnabled)
    except Exception:
        return True


class AddOpDialog(QDialog):
    """选一个操作类型。已在框里的（且不允许重复的）会置灰。"""

    def __init__(self, op_list, parent=None, preselect=None):
        super().__init__(parent)
        self.op_list = op_list
        self.setWindowTitle("添加操作")
        self.resize(480, 400)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("选择要添加的操作（灰色表示已选不可重复选择）："))

        self.list = QListWidget()
        first_enabled = -1
        wanted = -1
        for spec in operations.all_specs():
            can, why = op_list.can_add(spec.type)
            text = spec.name
            if spec.desc:
                text += "    — %s" % spec.desc
            if not can:
                text += "    （已添加）"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, spec.type)
            if can:
                if first_enabled < 0:
                    first_enabled = self.list.count()
                if preselect and spec.type == preselect:
                    wanted = self.list.count()
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        root.addWidget(self.list, 1)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.btn_ok = self.box.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setText("添加")
        self.btn_ok.setDefault(True)
        self.box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        root.addWidget(self.box)

        self.list.currentItemChanged.connect(self._on_current)
        target = wanted if wanted >= 0 else first_enabled
        if target >= 0:
            self.list.setCurrentRow(target)
            self.list.setFocus()
        self.btn_ok.setEnabled(target >= 0)
        self._on_current(self.list.currentItem(), None)
        if target < 0:
            self.hint.setText("能加的都加过了（「打开网页」可多条）。")

    def _on_current(self, item, _prev=None):
        if not item_enabled(item):
            self.hint.setText("已添加")
            return
        spec = operations.get_spec(item.data(Qt.ItemDataRole.UserRole))
        if spec is None:
            self.hint.setText("")
            return
        if spec.params:
            keys = "、".join(p[1] for p in spec.params)
            self.hint.setText("需要填写：%s" % keys)
        elif spec.allow_multiple:
            self.hint.setText("允许重复添加")
        else:
            self.hint.setText("不允许重复添加")

    def chosen_type(self):
        """选中的操作 id；没选/选中的是灰项 → 空串。"""
        item = self.list.currentItem()
        if not item_enabled(item):
            return ""
        return item.data(Qt.ItemDataRole.UserRole) or ""
