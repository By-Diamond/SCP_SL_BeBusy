# -*- coding: utf-8 -*-
"""关于页：版本 / 作者 / 程序介绍 / 项目链接 / 用法说明。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

import config as cfgmod
import operations
from ui import icons, util

REPO_URL = "https://github.com/By-Diamond/SCP_SL_BeBusy"
GH_URL = "https://github.com/By-Diamond/"
BILI_URL = "https://space.bilibili.com/602152864"

LINKS_HTML = (
    "链接：<a href='%s'>GitHub 仓库</a>　·　<a href='%s'>作者主页</a>"
    "　·　<a href='%s'>Bilibili</a>　|　反馈 bug：请到 GitHub 提交"
    % (REPO_URL, GH_URL, BILI_URL)
)

USAGE_HTML = """
<h3>怎么用</h3>
<ul>
  <li>托盘常驻：左键图标 = 显示界面，右键 = 菜单。点 ✕ 只是隐藏。</li>
  <li>「功能配置」里给死亡后 / 复活后各加要执行的操作，改动立即生效。</li>
  <li>「设置」里配开机自启动、Player.log、日志文件、配置文件位置。</li>
</ul>
<h3>判定</h3>
<ul>
  <li>死亡：Player.log 出现 <code>You died.</code>（不区分大小写）。</li>
  <li>复活：SCPSL 窗口收到 <code>HSHELL_REDRAW</code>。</li>
  <li>死亡后 0.7s 内复活 → 不动作；复活方向立即执行。</li>
</ul>
<h3>安全</h3>
<ul>
  <li>只读日志 + 监听自己注册的 Shell 钩子；不注入、不挂钩、不读内存。</li>
  <li>不改游戏本体与音量，只发系统媒体键 / 开关窗口，不是作弊行为。</li>
</ul>
<h3>已知取舍</h3>
<ul>
  <li>媒体键是盲发的（系统没给普通查询接口）：程序只记得自己最后改成了什么。</li>
  <li>你自己按过播放/暂停后，可用托盘「手动」项对齐。</li>
</ul>
"""


class AboutPage(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        self.core = core

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icons.state_pixmap("alive", 56))
        head.addWidget(logo)
        title_box = QVBoxLayout()
        title = QLabel("<b style='font-size:18px'>%s</b>" % cfgmod.APP_TITLE)
        title.setTextFormat(Qt.RichText)
        title_box.addWidget(title)
        sub = QLabel("版本 %s　|　作者 %s" % (cfgmod.VERSION, cfgmod.AUTHOR))
        title_box.addWidget(sub)
        desc = QLabel(cfgmod.DESCRIPTION)
        desc.setWordWrap(True)
        title_box.addWidget(desc)
        head.addLayout(title_box, 1)
        root.addLayout(head)

        self.links = QLabel(LINKS_HTML)
        self.links.setTextFormat(Qt.RichText)
        self.links.setOpenExternalLinks(True)              # 点链接直接用默认浏览器打开
        self.links.setWordWrap(True)
        root.addWidget(self.links)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(USAGE_HTML)
        self.usage = browser
        root.addWidget(browser, 1)

        row = QHBoxLayout()
        self.btn_log_folder = QPushButton("打开日志文件夹")
        self.btn_log_folder.clicked.connect(lambda: util.open_folder_of(self.core.log.path))
        row.addWidget(self.btn_log_folder)
        self.btn_cfg_folder = QPushButton("打开配置文件夹")
        self.btn_cfg_folder.clicked.connect(lambda: util.open_folder_of(self.core.cfg.path))
        row.addWidget(self.btn_cfg_folder)
        self.btn_diag = QPushButton("复制诊断信息")
        self.btn_diag.clicked.connect(self.copy_diagnostics)
        row.addWidget(self.btn_diag)
        self.btn_ops = QPushButton("当前功能配置")
        self.btn_ops.clicked.connect(self.show_ops)
        row.addWidget(self.btn_ops)
        row.addStretch(1)
        root.addLayout(row)

        info = QLabel("")
        info.setWordWrap(True)
        self.info = info
        root.addWidget(info)

        self.refresh()

    def refresh(self):
        plog, exists = self.core.player_log_now()
        self.info.setText(
            "配置文件：%s\nPlayer.log：%s（%s）\n日志文件：%s\n运行方式：%s"
            % (self.core.cfg.path, plog, "存在" if exists else "不存在", self.core.log.path,
               "打包 exe" if cfgmod.is_frozen() else "源码运行"))

    def show_ops(self):
        death = " → ".join(operations.describe_item(i) for i in self.core.cfg.ops("death")) or "（空）"
        alive = " → ".join(operations.describe_item(i) for i in self.core.cfg.ops("alive")) or "（空）"
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "当前功能配置",
                               "死亡后：\n%s\n\n复活后：\n%s" % (death, alive))

    def copy_diagnostics(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.core.diagnostics())
        self.core.log.log("[ui] 已复制诊断信息")
