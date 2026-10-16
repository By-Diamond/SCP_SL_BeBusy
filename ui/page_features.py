# -*- coding: utf-8 -*-
"""功能配置页：**死亡后** / **复活后** 两个动作框，各自可增删改排序。

* 规则都在 `opsmodel.OpList` 里（同框不重复 / 部分操作可多条、可上移下移）。
* 任何改动**立即写配置、立即生效**（不用点保存）。
* 「测试」= 现在就把这个列表跑一遍（不动游戏、不影响判定）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

import operations
import opsmodel
from ui import op_dialog

NOTE_TEXT = "同一个操作可出现在两个框里；同一个框里部分操作不能重复选。"


class OpBox(QGroupBox):
    """一个框（死亡后 / 复活后）。"""

    def __init__(self, core, which, title, parent=None):
        super().__init__(title, parent)
        self.core = core
        self.which = which                       # "death" / "alive"
        self.op_list = opsmodel.OpList(core.cfg.ops(which), label=title)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _i: self.guard(self.edit))
        root.addWidget(self.list, 1)

        row1 = QHBoxLayout()
        self.btn_add = QPushButton("添加…")
        self.btn_add.clicked.connect(lambda: self.guard(self.add))
        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(lambda: self.guard(self.edit))
        self.btn_del = QPushButton("删除")
        self.btn_del.clicked.connect(lambda: self.guard(self.remove))
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row1.addWidget(b)
        row1.addStretch(1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.btn_up = QPushButton("上移")
        self.btn_up.clicked.connect(lambda: self.guard(lambda: self.move(-1)))
        self.btn_down = QPushButton("下移")
        self.btn_down.clicked.connect(lambda: self.guard(lambda: self.move(1)))
        self.btn_test = QPushButton("测试")
        self.btn_test.clicked.connect(lambda: self.guard(self.test_run))
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(lambda: self.guard(self.clear))
        for b in (self.btn_up, self.btn_down, self.btn_test, self.btn_clear):
            row2.addWidget(b)
        row2.addStretch(1)
        root.addLayout(row2)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.reload()

    # ---------------- 出错护栏 ----------------
    # （打包成 exe 是 --windowed，没有控制台；界面回调里一旦抛异常就会"看起来完全没反应"，
    #   所以这里统一兜住：弹窗 + 写日志，绝不静默失败。）

    def guard(self, fn):
        try:
            return fn()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            try:
                self.core.log.log("⚠ 界面操作出错：\n%s" % tb)
            except Exception:
                pass
            QMessageBox.critical(self, "操作失败", "出错了，详见日志：\n%s"
                                 % tb.strip().splitlines()[-1])
            return None

    # ---------------- 显示 ----------------

    def reload(self):
        sel = self.list.currentRow()
        self.list.clear()
        for item in self.op_list:
            self.list.addItem(operations.describe_item(item))
        if 0 <= sel < self.list.count():
            self.list.setCurrentRow(sel)
        self.hint.setText("共 %d 条" % len(self.op_list))

    def _refresh_all(self):
        self.reload()
        self.core.save_ops(self.which, self.op_list.to_config())

    # ---------------- 按钮 ----------------

    def add(self):
        dlg = op_dialog.AddOpDialog(self.op_list, self)
        if dlg.exec() != QDialog.Accepted:
            return
        op_type = dlg.chosen_type()
        if not op_type:
            QMessageBox.warning(self, "添加操作", "请选一项白色的操作。")
            return
        self._add_type(op_type)

    def _add_type(self, op_type):
        """把某个操作加进本框（含参数询问）。独立出来便于单测。"""
        spec = operations.get_spec(op_type)
        if spec is None:
            QMessageBox.warning(self, "添加操作", "未知操作类型：%s" % op_type)
            return False
        kwargs, ok = self._ask_params(spec, None, "添加操作")
        if not ok:
            return False
        ok, msg = self.op_list.add(op_type, **kwargs)
        if not ok:
            QMessageBox.warning(self, "添加操作", msg)
            return False
        self._refresh_all()
        self.list.setCurrentRow(len(self.op_list) - 1)
        self.core.log.log("[ui] 「%s」已添加操作" % self.which)
        return True

    def _ask_params(self, spec, current, title):
        """按参数表逐个问（网址/窗口/文件各有专用弹窗）。返回 (kwargs, 是否继续)。"""
        values = {}
        for key, label, default, hint in spec.params:
            cur = (current or {}).get(key) or ""
            if not cur:
                # 新建时「打开网页」用配置里的默认网址
                cur = (self.core.cfg.get("open_url_default") or "") if key == "url" \
                    else (default or "")
            val, answered = op_dialog.ask_param(self, key, label, cur, hint)
            if not answered:
                return {}, False
            val = (val or "").strip()
            if not val:
                QMessageBox.warning(self, title, "「%s」不能为空。" % label)
                return {}, False
            values[key] = val
        return values, True

    def edit(self):
        i = self.list.currentRow()
        if i < 0:
            QMessageBox.information(self, "编辑", "先在列表里选一条。")
            return
        item = self.op_list.items[i]
        spec = operations.get_spec(item["type"])
        if spec is None or not spec.params:
            QMessageBox.information(self, "编辑", "「%s」没有可改的参数。"
                                    % (spec.name if spec else "未知操作"))
            return
        values, ok = self._ask_params(spec, item.get("params") or {}, "编辑")
        if not ok:
            return
        self.op_list.set_params(i, **values)
        self._refresh_all()

    def remove(self):
        i = self.list.currentRow()
        if i < 0:
            QMessageBox.information(self, "删除", "先在左边选一条。")
            return
        name = operations.describe_item(self.op_list.items[i])
        if QMessageBox.question(self, "删除", "确定删除「%s」？" % name) != QMessageBox.Yes:
            return
        self.op_list.remove(i)
        self._refresh_all()

    def move(self, delta):
        i = self.list.currentRow()
        if i < 0:
            return
        ok, _msg = self.op_list.move(i, delta)
        if not ok:
            return
        self._refresh_all()
        self.list.setCurrentRow(i + delta)

    def clear(self):
        if not len(self.op_list):
            return
        if QMessageBox.question(self, "清空", "清空这个列表？") != QMessageBox.Yes:
            return
        self.op_list.clear()
        self._refresh_all()

    def test_run(self):
        self.core.save_ops(self.which, self.op_list.to_config())
        self.core.manual_test_ops(self.which)
        QMessageBox.information(self, "测试", "已按顺序执行一遍，详情看「日志」。")

    def sync_from_config(self):
        self.op_list = opsmodel.OpList(self.core.cfg.ops(self.which), label=self.which)
        self.reload()


class FeaturePage(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        tip = QLabel("状态确定后，按顺序执行对应框里的操作；改动立即生效。")
        tip.setWordWrap(True)
        root.addWidget(tip)

        row = QHBoxLayout()
        self.death_box = OpBox(core, "death", "死亡后（保持 0.7s 未复活才执行）")
        self.alive_box = OpBox(core, "alive", "复活后（立即执行）")
        row.addWidget(self.death_box, 1)
        row.addWidget(self.alive_box, 1)
        root.addLayout(row, 1)

        note = QLabel(NOTE_TEXT)
        note.setWordWrap(True)
        root.addWidget(note)

    def sync_from_config(self):
        self.death_box.sync_from_config()
        self.alive_box.sync_from_config()
