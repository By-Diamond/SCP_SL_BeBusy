# -*- coding: utf-8 -*-
"""图标：用 QPainter **现画**（不依赖外部图片文件，打包更省事）。

* 托盘/窗口图标：绿点 = 存活，红点 = 死亡·观察者，灰点 = 未知
* exe 图标（build.bat 里生成 .ico）用同一套配色
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

ALIVE_COLOR = "#2ecc71"
DEAD_COLOR = "#e74c3c"
UNKNOWN_COLOR = "#95a5a6"
BG_COLOR = "#2b2f36"


def state_pixmap(state, size=64):
    """画一个圆点。`state`：'alive' / 'dead' / 其它（未知）。"""
    color = {"alive": ALIVE_COLOR, "dead": DEAD_COLOR}.get(state, UNKNOWN_COLOR)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QBrush(QColor(BG_COLOR)))
    p.setPen(QPen(QColor("#11141a"), max(1, size // 32)))
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    m = size * 0.22
    p.drawEllipse(QRectF(m, m, size - 2 * m, size - 2 * m))
    p.end()
    return pm


def state_icon(state, size=64):
    return QIcon(state_pixmap(state, size))


def app_icon(size=256):
    return QIcon(state_pixmap("alive", size))
