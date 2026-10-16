# -*- coding: utf-8 -*-
"""日志页：级别过滤 + 跟随滚动 + 清空 / 导出 / 打开日志文件。"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

import logbus
from ui import util

MAX_LINES = 5000
FILTERS = (("全部", "all"), ("关键", "key"), ("仅错误", "error"))


class LogPage(QWidget):
    def __init__(self, core, title="日志输出", compact=False, parent=None):
        super().__init__(parent)
        self.core = core
        self.compact = compact
        self._buf = []                       # [(line, level)] 完整历史，供切换过滤时重画

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(title))
        bar.addStretch(1)

        if not compact:
            bar.addWidget(QLabel("级别："))
            self.filter_box = QComboBox()
            for label, key in FILTERS:
                self.filter_box.addItem(label, key)
            self.filter_box.currentIndexChanged.connect(self._on_filter)
            bar.addWidget(self.filter_box)

            self.follow = QCheckBox("跟随最新")
            self.follow.setChecked(bool((core.cfg.get("ui") or {}).get("follow_log", True)))
            bar.addWidget(self.follow)

            self.btn_clear = QPushButton("清空")
            self.btn_clear.clicked.connect(self.clear)
            bar.addWidget(self.btn_clear)

            self.btn_export = QPushButton("导出…")
            self.btn_export.clicked.connect(self.export)
            bar.addWidget(self.btn_export)

            self.btn_open = QPushButton("打开日志文件")
            self.btn_open.clicked.connect(self.open_log_file)
            bar.addWidget(self.btn_open)

            self.btn_folder = QPushButton("打开所在文件夹")
            self.btn_folder.clicked.connect(self.open_log_folder)
            bar.addWidget(self.btn_folder)

        root.addLayout(bar)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(MAX_LINES)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        try:
            self.text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        except Exception:
            pass
        self.text.setPlaceholderText("日志会显示在这里……")
        root.addWidget(self.text, 1)

        if not compact:
            self.path_label = QLabel("")
            self.path_label.setWordWrap(True)
            root.addWidget(self.path_label)
            self.refresh_path_label()
            # 启动时把日志文件尾部读进来，免得界面空白
            self.load_tail(300)

    # ---------------- 数据 ----------------

    def current_filter(self):
        if self.compact:
            return "all"
        return self.filter_box.currentData()

    def _passes(self, level):
        f = self.current_filter()
        if f == "all":
            return True
        if f == "key":
            return logbus.is_key(level)
        return logbus.is_error(level)

    def append_line(self, line, level="info"):
        """由界面线程调用（后台线程通过 Bridge 信号送过来）。"""
        self._buf.append((line, level))
        if len(self._buf) > MAX_LINES:
            del self._buf[:len(self._buf) - MAX_LINES]
        if not self._passes(level):
            return
        self._append_to_view(line)

    def _append_to_view(self, line):
        self.text.appendPlainText(line)
        if self.compact or self.follow.isChecked():
            self.text.moveCursor(QTextCursor.End)

    def reload_view(self):
        self.text.clear()
        for line, level in self._buf:
            if self._passes(level):
                self.text.appendPlainText(line)
        if self.compact or self.follow.isChecked():
            self.text.moveCursor(QTextCursor.End)

    def clear(self):
        self._buf = []
        self.text.clear()
        self.core.log.log("[ui] 界面日志已清空（文件里的日志不受影响）")

    def load_tail(self, n=300):
        """把日志文件最后 n 行读进界面（只用于显示）。"""
        path = self.core.log.path
        if not path or not os.path.isfile(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.readlines()[-n:]
        except Exception:
            return 0
        for line in tail:
            line = line.rstrip("\n")
            self._buf.append((line, logbus.classify(line)))
        self.reload_view()
        return len(tail)

    # ---------------- 按钮 ----------------

    def _on_filter(self, _idx):
        self.core.set_ui_state(log_filter=self.current_filter())
        self.reload_view()

    def export(self):
        from PySide6.QtWidgets import QFileDialog
        default = os.path.join(os.path.dirname(self.core.log.path or "."), "日志导出.log")
        path, _f = QFileDialog.getSaveFileName(self, "导出日志", default,
                                               "文本文件 (*.log *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                for line, _lvl in self._buf:
                    f.write(line + "\n")
            self.core.log.log("[ui] 日志已导出到 %s（%d 行）" % (path, len(self._buf)))
        except Exception as e:
            self.core.log.log("⚠ 日志导出失败：%r" % (e,))

    def open_log_file(self):
        ok, msg = util.open_path(self.core.log.path)
        if not ok:
            self.core.log.log("⚠ %s" % msg)

    def open_log_folder(self):
        ok, msg = util.open_folder_of(self.core.log.path)
        if not ok:
            self.core.log.log("⚠ %s" % msg)

    def refresh_path_label(self):
        path = self.core.log.path or "（未设置）"
        size = ""
        try:
            if path and os.path.isfile(path):
                size = "（%s）" % util.human_size(os.path.getsize(path))
        except Exception:
            pass
        self.path_label.setText("日志文件：%s%s" % (path, size))
