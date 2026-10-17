# -*- coding: utf-8 -*-
"""设置页：死亡判定时间 / 开机自启动 / Player.log / 日志文件 / 配置文件位置 / 默认网址。

**改了立即生效**（不用点保存）：
* 死亡判定时间（500-10000ms）→ 下一张死亡门就用新值；
* Player.log 路径 → 立刻重挂监听；
* 日志文件路径与大小 → 立刻切换；
* 开机自启动 → 立刻写/删注册表；
* 配置文件位置 → 立刻迁移并以后都用新位置；
* 「打开网页」默认网址 → 立刻用于下一次添加。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

import autostart
import config as cfgmod
import trigger
from ui import util


class SettingsPage(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core
        self._loading = True

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        root.addWidget(self._build_settle())
        root.addWidget(self._build_autostart())
        root.addWidget(self._build_player_log())
        root.addWidget(self._build_log_file())
        root.addWidget(self._build_config_location())
        root.addWidget(self._build_misc())
        root.addStretch(1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self._loading = False
        self.refresh()

    # ---------------- 死亡判定时间 ----------------

    def _build_settle(self):
        """死亡判定时间（毫秒）：闭区间 [500, 10000]，改完立即生效。"""
        box = QGroupBox("判定（死亡确认时间）")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.sp_settle = QSpinBox()
        self.sp_settle.setRange(trigger.SETTLE_MIN_MS, trigger.SETTLE_MAX_MS)
        self.sp_settle.setSuffix(" ms")
        self.sp_settle.valueChanged.connect(self.on_settle)
        row.addWidget(QLabel("死亡后保持："))
        row.addWidget(self.sp_settle)
        b = QPushButton("应用")
        b.clicked.connect(lambda: self.on_settle(self.sp_settle.value()))
        row.addWidget(b)
        row.addStretch(1)
        form.addRow("判定：", row)

        self.lbl_settle = QLabel("")
        self.lbl_settle.setWordWrap(True)
        form.addRow("状态：", self.lbl_settle)
        return box

    def on_settle(self, value=None):
        if self._loading:
            return
        v = self.sp_settle.value() if value is None else value
        ok, msg = self.core.set_death_settle_ms(v)
        if not ok:
            # 非法值不写配置：把输入框改回现在生效的值，让用户重新输入
            self._loading = True
            try:
                self.sp_settle.setValue(int(self.core.death_settle_ms))
            finally:
                self._loading = False
            QMessageBox.warning(self, "死亡判定时间", msg)
            self.set_status("⚠ %s" % msg)
            return
        self.lbl_settle.setText("当前生效：%dms（这个时间内复活就当作没死）"
                                % self.core.death_settle_ms)
        self.set_status("✔ %s" % msg)

    # ---------------- 开机自启动 ----------------

    def _build_autostart(self):
        box = QGroupBox("开机自启动")
        lay = QVBoxLayout(box)
        self.cb_autostart = QCheckBox("开机时自动运行本程序")
        self.cb_autostart.toggled.connect(self.on_autostart)
        lay.addWidget(self.cb_autostart)
        self.lbl_autostart = QLabel("")
        self.lbl_autostart.setWordWrap(True)
        lay.addWidget(self.lbl_autostart)
        return box

    def on_autostart(self, checked):
        if self._loading:
            return
        ok, msg = self.core.set_autostart(bool(checked))
        self.lbl_autostart.setText(("✔ " if ok else "⚠ ") + msg)
        if not ok:
            self._loading = True
            self.cb_autostart.setChecked(not checked)
            self._loading = False
            QMessageBox.warning(self, "开机自启动", msg)
        self.refresh_autostart_label()

    def refresh_autostart_label(self):
        st = autostart.status()
        if not st["supported"]:
            self.lbl_autostart.setText("（当前系统不是 Windows，此功能不可用）")
            self.cb_autostart.setEnabled(False)
            return
        self.lbl_autostart.setText("注册表当前值：%s"
                                   % (st["registered"] or "（未设置）"))

    # ---------------- Player.log ----------------

    def _build_player_log(self):
        box = QGroupBox("游戏日志位置（Player.log）")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.ed_player_log = QLineEdit()
        self.ed_player_log.setPlaceholderText("留空 = 自动识别")
        self.ed_player_log.editingFinished.connect(self.on_player_log)
        row.addWidget(self.ed_player_log, 1)
        b_browse = QPushButton("浏览…")
        b_browse.clicked.connect(self.browse_player_log)
        row.addWidget(b_browse)
        b_auto = QPushButton("自动识别")
        b_auto.clicked.connect(self.autodetect_player_log)
        row.addWidget(b_auto)
        b_open = QPushButton("打开文件夹")
        b_open.clicked.connect(self.open_player_log_folder)
        row.addWidget(b_open)
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self.on_player_log)
        row.addWidget(b_apply)
        form.addRow("路径：", row)

        self.lbl_player_log = QLabel("")
        self.lbl_player_log.setWordWrap(True)
        form.addRow("状态：", self.lbl_player_log)
        return box

    def open_player_log_folder(self):
        path = self.core.player_log_now()[0]
        if not path:
            self.set_status("⚠ 还没确定 Player.log 路径")
            return
        ok, msg = util.open_folder_of(path)
        if not ok:
            self.set_status("⚠ %s" % msg)

    def browse_player_log(self):
        path, _f = QFileDialog.getOpenFileName(
            self, "选择 Player.log", os.path.dirname(self.ed_player_log.text() or
                                              cfgmod.default_player_log()),
            "日志文件 (*.log);;所有文件 (*)")
        if path:
            self.ed_player_log.setText(path)
            self.on_player_log()

    def autodetect_player_log(self):
        path, exists, how = self.core.autodetect_player_log()
        self.ed_player_log.setText(path or "")
        self.refresh()
        self.set_status("%s → %s" % (how, path or "（没找到，请手动指定）"))
        if not exists:
            QMessageBox.information(
                self, "自动识别",
                "没找到 Player.log。默认位置：\n%s" % cfgmod.default_player_log())

    def on_player_log(self):
        if self._loading:
            return
        text = self.ed_player_log.text().strip()
        cur = (self.core.cfg.get("player_log") or "").strip()
        if text == cur:
            self.refresh()
            return
        ok, msg = self.core.set_player_log_path(text)
        self.set_status(("✔ " if ok else "⚠ ") + msg)
        self.refresh()

    # ---------------- 日志文件 ----------------

    def _build_log_file(self):
        box = QGroupBox("运行日志文件")
        form = QFormLayout(box)

        row = QHBoxLayout()
        self.ed_log_file = QLineEdit()
        self.ed_log_file.setPlaceholderText("留空 = 与配置文件同目录")
        self.ed_log_file.editingFinished.connect(self.on_log_file)
        row.addWidget(self.ed_log_file, 1)
        b = QPushButton("另存到…")
        b.clicked.connect(self.browse_log_file)
        row.addWidget(b)
        b2 = QPushButton("应用")
        b2.clicked.connect(self.on_log_file)
        row.addWidget(b2)
        b3 = QPushButton("打开文件夹")
        b3.clicked.connect(lambda: util.open_folder_of(self.core.log.path))
        row.addWidget(b3)
        form.addRow("路径：", row)

        row2 = QHBoxLayout()
        self.sp_max = QSpinBox()
        self.sp_max.setRange(1, 500)
        self.sp_max.setSuffix(" MB")
        self.sp_max.valueChanged.connect(self.on_log_size)
        row2.addWidget(QLabel("单文件上限："))
        row2.addWidget(self.sp_max)
        self.sp_backups = QSpinBox()
        self.sp_backups.setRange(0, 9)
        self.sp_backups.setSuffix(" 份")
        self.sp_backups.valueChanged.connect(self.on_log_size)
        row2.addWidget(QLabel("保留备份："))
        row2.addWidget(self.sp_backups)
        row2.addStretch(1)
        form.addRow("轮转：", row2)

        self.lbl_log_file = QLabel("")
        self.lbl_log_file.setWordWrap(True)
        form.addRow("当前：", self.lbl_log_file)
        return box

    def browse_log_file(self):
        path, _f = QFileDialog.getSaveFileName(
            self, "选择日志文件", self.ed_log_file.text() or self.core.log.path,
            "日志文件 (*.log);;所有文件 (*)")
        if path:
            self.ed_log_file.setText(path)
            self.on_log_file()

    def on_log_file(self):
        if self._loading:
            return
        text = self.ed_log_file.text().strip()
        if text == (self.core.cfg.get("log_file") or "").strip():
            self.refresh()
            return
        target = self.core.set_log_file(text or None)
        self.set_status("✔ 日志文件已切换：%s" % target)
        self.refresh()

    def on_log_size(self, _v=None):
        if self._loading:
            return
        self.core.set_log_file(self.ed_log_file.text().strip() or None,
                               self.sp_max.value(), self.sp_backups.value())
        self.refresh()

    # ---------------- 配置文件位置 ----------------

    def _build_config_location(self):
        box = QGroupBox("配置文件位置（settings.json）")
        lay = QVBoxLayout(box)
        note = QLabel("默认放程序目录；目录只读时用 %APPDATA%\\SCP_SL_BeBusy。")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QHBoxLayout()
        self.ed_cfg_path = QLineEdit()
        row.addWidget(self.ed_cfg_path, 1)
        b = QPushButton("另存到…")
        b.clicked.connect(self.browse_config_path)
        row.addWidget(b)
        b2 = QPushButton("迁移到此位置")
        b2.clicked.connect(self.on_move_config)
        row.addWidget(b2)
        b3 = QPushButton("恢复默认位置")
        b3.clicked.connect(self.on_reset_config)
        row.addWidget(b3)
        b4 = QPushButton("打开文件夹")
        b4.clicked.connect(lambda: util.open_folder_of(self.core.cfg.path))
        row.addWidget(b4)
        lay.addLayout(row)

        self.lbl_cfg_path = QLabel("")
        self.lbl_cfg_path.setWordWrap(True)
        lay.addWidget(self.lbl_cfg_path)
        return box

    def browse_config_path(self):
        path, _f = QFileDialog.getSaveFileName(
            self, "配置文件的存放位置", self.ed_cfg_path.text() or self.core.cfg.path,
            "配置文件 (*.json);;所有文件 (*)")
        if path:
            self.ed_cfg_path.setText(path)

    def on_move_config(self):
        path = self.ed_cfg_path.text().strip()
        if not path:
            QMessageBox.information(self, "配置文件位置", "先选一个位置。")
            return
        if QMessageBox.question(self, "迁移配置文件",
                                "迁移到：\n%s（旧文件保留）" % path
                                ) != QMessageBox.Yes:
            return
        ok, msg = self.core.set_config_location(path)
        self.set_status(("✔ " if ok else "⚠ ") + msg)
        self.refresh()

    def on_reset_config(self):
        if QMessageBox.question(self, "恢复默认位置",
                                "配置写回默认位置（%s）？"
                                % cfgmod.default_settings_path()) != QMessageBox.Yes:
            return
        _p, msg = self.core.reset_config_location()
        self.set_status("✔ " + msg)
        self.refresh()

    # ---------------- 其它 ----------------

    def _build_misc(self):
        box = QGroupBox("其它")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("添加「打开网页」时预填的网址")
        self.ed_url.editingFinished.connect(self.on_url)
        row.addWidget(self.ed_url, 1)
        b = QPushButton("应用")
        b.clicked.connect(self.on_url)
        row.addWidget(b)
        form.addRow("默认网址：", row)

        row2 = QHBoxLayout()
        b2 = QPushButton("打开程序所在文件夹")
        b2.clicked.connect(lambda: util.open_path(cfgmod.app_dir()))
        row2.addWidget(b2)
        b3 = QPushButton("打开配置文件（用记事本）")
        b3.clicked.connect(lambda: util.open_path(self.core.cfg.path))
        row2.addWidget(b3)
        row2.addStretch(1)
        form.addRow("快捷：", row2)
        return box

    def on_url(self):
        if self._loading:
            return
        text = self.ed_url.text().strip()
        if text == (self.core.cfg.get("open_url_default") or "").strip():
            return
        self.core.set_open_url_default(text)
        self.set_status("✔ 默认网址已保存：%s" % (text or "（空）"))

    # ---------------- 刷新 ----------------

    def set_status(self, text):
        self.status.setText(text)

    def refresh(self):
        self._loading = True
        try:
            ms = int(getattr(self.core, "death_settle_ms",
                             int(round(trigger.DEATH_SETTLE_S * 1000))))
            self.sp_settle.setValue(ms)
            self.lbl_settle.setText("当前生效：%dms（这个时间内复活就当作没死）" % ms)
            self.cb_autostart.setChecked(bool(self.core.cfg.get("autostart")))
            self.refresh_autostart_label()

            self.ed_player_log.setText(self.core.cfg.get("player_log") or "")
            path, exists = self.core.player_log_now()
            self.lbl_player_log.setText(("存在 ✔：%s" if exists else "当前不存在（游戏没跑或路径不对）：%s") % path)

            self.ed_log_file.setText(self.core.cfg.get("log_file") or "")
            self.sp_max.setValue(int(float(self.core.cfg.get("log_max_mb") or 5)))
            self.sp_backups.setValue(int(self.core.cfg.get("log_backups") or 0))
            size = ""
            try:
                if os.path.isfile(self.core.log.path):
                    size = "（%s）" % util.human_size(os.path.getsize(self.core.log.path))
            except Exception:
                pass
            self.lbl_log_file.setText("%s%s" % (self.core.log.path, size))

            self.ed_cfg_path.setText(self.core.cfg.path)
            self.lbl_cfg_path.setText("当前生效：%s（%s）"
                                      % (self.core.cfg.path,
                                         "文件已存在" if os.path.isfile(self.core.cfg.path)
                                         else "还没写过"))
            self.ed_url.setText(self.core.cfg.get("open_url_default") or "")
        finally:
            self._loading = False
