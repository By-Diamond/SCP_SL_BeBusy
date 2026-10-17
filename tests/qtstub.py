# -*- coding: utf-8 -*-
"""PySide6 桩 —— 只实现被测代码真正调用到的那些方法。

设计原则（吃过亏）：
* **不搞 Catch-all `__getattr__`**：没建模的方法就 AttributeError，别把 bug 藏起来。
* `exec()` 的结果**可配置**（`exec_queue`），默认 Rejected —— 但测试必须显式设过一次，
  否则"永远 Rejected"会让「弹窗之后的分支」永远不被测到。
"""

import enum
import sys
import types


class _Signal(object):
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for fn in list(self.slots):
            fn(*a)


class Qt(object):
    class ItemDataRole(enum.IntEnum):
        DisplayRole = 0
        ToolTipRole = 32
        UserRole = 256

    class ItemFlag(enum.IntFlag):
        NoItemFlags = 0
        ItemIsSelectable = 1
        ItemIsEnabled = 2

    class AlignmentFlag(enum.IntFlag):
        AlignLeft = 1

    # 几个被真实断言/设置用到的枚举值，给真值
    RichText = 1
    PlainText = 0
    transparent = 0
    NoPen = 0


class _Base(object):
    def __init__(self, *a, **k):
        self._signals = {}

    def _sig(self, name):
        return self._signals.setdefault(name, _Signal())

    # 布局/窗口通用
    def setWindowTitle(self, t):
        self.windowTitle_text = t

    def windowTitle(self):
        return getattr(self, "windowTitle_text", "")

    def resize(self, w, h):
        self.size = (w, h)

    def setEnabled(self, on):
        self.enabled = bool(on)

    def isEnabled(self):
        return getattr(self, "enabled", True)

    def setToolTip(self, t):
        self.tooltip = t

    def setObjectName(self, n):
        self.objectName_text = n

    def setStyleSheet(self, css):
        self.style = css

    def setFocus(self):
        self.focused = True


class _Widget(_Base):
    def __init__(self, parent=None, *a, **k):
        _Base.__init__(self)
        self.parent = parent


class QWidget(_Widget):
    pass


class QLabel(_Widget):
    def __init__(self, text="", parent=None):
        _Widget.__init__(self, parent)
        self._text = text
        self.text_format = Qt.PlainText

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setWordWrap(self, on):
        self.wordwrap = bool(on)

    def setTextFormat(self, fmt):
        self.text_format = fmt

    def setOpenExternalLinks(self, on):
        self.open_external = bool(on)

    def setPixmap(self, pm):
        self.pixmap = pm


class QLineEdit(_Widget):
    def __init__(self, text="", parent=None):
        _Widget.__init__(self, parent)
        self._text = text
        self.placeholder = ""

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setPlaceholderText(self, t):
        self.placeholder = t

    def clear(self):
        self._text = ""

    def setReadOnly(self, on):
        self.readonly = bool(on)

    def isReadOnly(self):
        return getattr(self, "readonly", False)


class QPushButton(_Widget):
    def __init__(self, text="", parent=None):
        _Widget.__init__(self, parent)
        self._text = text
        self.clicked = self._sig("clicked")
        self.default = False

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setDefault(self, on):
        self.default = bool(on)

    def click(self):
        self.clicked.emit(False)


class QGroupBox(_Widget):
    def __init__(self, title="", parent=None):
        _Widget.__init__(self, parent)
        self.title = title


class QListWidgetItem(object):
    def __init__(self, text=""):
        self._text = text
        self._data = {}
        self._flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

    def text(self):
        return self._text

    def setText(self, t):
        self._text = t

    def data(self, role):
        return self._data.get(int(role))

    def setData(self, role, value):
        self._data[int(role)] = value

    def flags(self):
        return self._flags

    def setFlags(self, f):
        self._flags = Qt.ItemFlag(f)


class QListWidget(_Widget):
    class SelectionMode(enum.IntEnum):
        SingleSelection = 1
        MultiSelection = 2

    def __init__(self, parent=None):
        _Widget.__init__(self, parent)
        self._items = []
        self._row = -1
        self.itemDoubleClicked = self._sig("itemDoubleClicked")
        self.currentItemChanged = self._sig("currentItemChanged")
        self.currentRowChanged = self._sig("currentRowChanged")

    def addItem(self, item):
        if not isinstance(item, QListWidgetItem):
            item = QListWidgetItem(str(item))
        self._items.append(item)
        if self._row < 0:
            self.setCurrentRow(0)

    def count(self):
        return len(self._items)

    def item(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def clear(self):
        self._items = []
        self._row = -1

    def setSelectionMode(self, mode):
        self.selection_mode = mode

    def setFocus(self):
        self.focused = True

    def currentRow(self):
        return self._row

    def currentItem(self):
        return self.item(self._row)

    def setCurrentRow(self, i):
        old = self.currentItem()
        self._row = i if 0 <= i < len(self._items) else -1
        self.currentItemChanged.emit(self.currentItem(), old)
        self.currentRowChanged.emit(self._row)

    def doubleClickRow(self, i):
        it = self.item(i)
        if it is not None:
            self.itemDoubleClicked.emit(it)


class QDialog(_Widget):
    class DialogCode(enum.IntEnum):
        Rejected = 0
        Accepted = 1

    Accepted = DialogCode.Accepted
    Rejected = DialogCode.Rejected

    # exec() 的结果队列（测试显式设置，避免"永远 Rejected"）
    exec_queue = []

    def __init__(self, parent=None):
        _Widget.__init__(self, parent)
        self.accepted = self._sig("accepted")
        self.rejected = self._sig("rejected")
        self.result = None

    def exec(self):
        if QDialog.exec_queue:
            r = QDialog.exec_queue.pop(0)
        else:
            r = QDialog.DialogCode.Rejected
        self.result = r
        if r == QDialog.DialogCode.Accepted:
            self.accepted.emit()
        else:
            self.rejected.emit()
        return r

    def accept(self):
        self.result = QDialog.DialogCode.Accepted
        self.accepted.emit()

    def reject(self):
        self.result = QDialog.DialogCode.Rejected
        self.rejected.emit()


class QDialogButtonBox(_Widget):
    class StandardButton(enum.IntFlag):
        NoButton = 0
        Ok = 1
        Cancel = 2
        Yes = 4
        No = 8

    def __init__(self, buttons=0, parent=None):
        _Widget.__init__(self, parent)
        self.buttons = QDialogButtonBox.StandardButton(buttons)
        self.accepted = self._sig("accepted")
        self.rejected = self._sig("rejected")
        self._btns = {}
        if self.buttons & QDialogButtonBox.StandardButton.Ok:
            self._btns[int(QDialogButtonBox.StandardButton.Ok)] = QPushButton("OK")
        if self.buttons & QDialogButtonBox.StandardButton.Cancel:
            self._btns[int(QDialogButtonBox.StandardButton.Cancel)] = QPushButton("Cancel")

    def button(self, std):
        return self._btns.get(int(std))


class QMessageBox(_Widget):
    class Icon(enum.IntEnum):
        Information = 1
        Warning = 2
        Critical = 3
        Question = 4

    StandardButton = QDialogButtonBox.StandardButton
    Yes = QDialogButtonBox.StandardButton.Yes
    No = QDialogButtonBox.StandardButton.No
    calls = []                      # [(kind, title, text)]
    question_result = QDialogButtonBox.StandardButton.Yes
    question_calls = []

    @classmethod
    def information(cls, parent, title, text, *a, **k):
        cls.calls.append(("information", title, text))
        return cls.StandardButton.Ok

    @classmethod
    def warning(cls, parent, title, text, *a, **k):
        cls.calls.append(("warning", title, text))
        return cls.StandardButton.Ok

    @classmethod
    def critical(cls, parent, title, text, *a, **k):
        cls.calls.append(("critical", title, text))
        return cls.StandardButton.Ok

    @classmethod
    def question(cls, parent, title, text, *a, **k):
        cls.question_calls.append((title, text))
        return cls.question_result

    @classmethod
    def reset(cls):
        cls.calls = []
        cls.question_calls = []


class QInputDialog(_Widget):
    NEXT_TEXT = "NEXT_TEXT"          # 哨兵：表示"用户取消"
    result = None                    # (text, answered)
    calls = []
    int_result = None                # (value, answered)
    int_calls = []
    item_result = None               # (text, answered)
    item_calls = []

    @classmethod
    def getText(cls, parent, title, label, text="", *a, **k):
        cls.calls.append((title, label, text))
        if cls.result is None:
            return "", False
        return cls.result

    @classmethod
    def getInt(cls, parent, title, label, value=0, minimum=0, maximum=100,
               step=1, *a, **k):
        cls.int_calls.append((title, label, value, minimum, maximum))
        if cls.int_result is None:
            return value, False
        return cls.int_result

    @classmethod
    def getItem(cls, parent, title, label, items, current=0, editable=True, *a, **k):
        cls.item_calls.append((title, label, list(items or []), current))
        if cls.item_result is None:
            return (items or [""])[0], False
        return cls.item_result

    @classmethod
    def reset(cls):
        cls.result = None
        cls.calls = []
        cls.int_result = None
        cls.int_calls = []
        cls.item_result = None
        cls.item_calls = []


class QFileDialog(_Widget):
    result = None                    # (path, filter)
    calls = []

    @classmethod
    def getOpenFileName(cls, parent, title, start="", filt="", *a, **k):
        cls.calls.append((title, start, filt))
        if cls.result is None:
            return "", ""
        return cls.result

    @classmethod
    def reset(cls):
        cls.result = None
        cls.calls = []


class QTextBrowser(_Widget):
    def __init__(self, parent=None):
        _Widget.__init__(self, parent)
        self.html = ""
        self.open_external = False

    def setHtml(self, html):
        self.html = html

    def setOpenExternalLinks(self, on):
        self.open_external = bool(on)

    def toPlainText(self):
        return self.html


class QTimer(_Base):
    """真计时器语义的最小桩：start / stop / isActive + timeout 信号（测试可手动 emit）。"""

    def __init__(self, parent=None):
        _Base.__init__(self, parent)
        self.interval = 0
        self.active = False
        self.timeout = self._sig("timeout")

    def setInterval(self, ms):
        self.interval = int(ms)

    def start(self, ms=None):
        if ms is not None:
            self.interval = int(ms)
        self.active = True

    def stop(self):
        self.active = False

    def isActive(self):
        return self.active


# 本套测试不构造这几个页面，只为 `import ui.main_window` 能过（名字存在即可）
for _n in ("QMainWindow", "QStackedWidget", "QStatusBar", "QPlainTextEdit"):
    globals()[_n] = type(_n, (_Widget,), {})


class QSpinBox(_Widget):
    """数字框：范围外的值真的填不进去（和 Qt 一样会夹住）。"""

    def __init__(self, parent=None):
        _Widget.__init__(self, parent)
        self._lo, self._hi, self._v = 0, 100, 0
        self.suffix = ""

    def setRange(self, lo, hi):
        self._lo, self._hi = int(lo), int(hi)

    def setValue(self, v):
        self._v = max(self._lo, min(self._hi, int(v)))

    def value(self):
        return self._v

    def setSuffix(self, s):
        self.suffix = s


class QComboBox(_Widget):
    """可编辑下拉：`currentText()` = 框里真正的那串字。"""

    def __init__(self, parent=None):
        _Widget.__init__(self, parent)
        self.items = []
        self._data = {}
        self._text = ""
        self.editable = False
        self.currentIndexChanged = self._sig("currentIndexChanged")

    def setEditable(self, on):
        self.editable = bool(on)

    def addItem(self, text):
        self.items.append(text)

    def clear(self):
        self.items = []
        self._data = {}

    def count(self):
        return len(self.items)

    def itemText(self, i):
        return self.items[i]

    def setItemData(self, i, value, role=0):
        self._data[(int(i), int(role))] = value

    def itemData(self, i, role=0):
        return self._data.get((int(i), int(role)))

    def setEditText(self, t):
        self._text = str(t)

    def currentText(self):
        return self._text

    def setCurrentIndex(self, i):
        if 0 <= i < len(self.items):
            self._text = self.items[i]


class QCheckBox(_Widget):
    def __init__(self, text="", parent=None):
        _Widget.__init__(self, parent)
        self._text = text
        self._checked = False
        self.stateChanged = self._sig("stateChanged")

    def setText(self, t):
        self._text = t

    def text(self):
        return self._text

    def setChecked(self, on):
        self._checked = bool(on)

    def isChecked(self):
        return self._checked


class _Layout(object):
    def __init__(self, *a, **k):
        self.widgets = []
        self.layouts = []
        self.stretches = 0

    def addWidget(self, w, *a, **k):
        self.widgets.append(w)

    def addLayout(self, l, *a, **k):
        self.layouts.append(l)

    def addStretch(self, n=0):
        self.stretches += 1

    def addSpacing(self, n):
        pass

    def setContentsMargins(self, *a):
        pass

    def setSpacing(self, n):
        self.spacing = n


class QVBoxLayout(_Layout):
    pass


class QHBoxLayout(_Layout):
    pass


class QFormLayout(_Layout):
    """一行 = (标签, 控件或子布局)。"""

    def __init__(self, parent=None):
        _Layout.__init__(self)
        self.rows = []

    def addRow(self, label, field):
        self.rows.append((label, field))
        self.widgets.append(field)


class _DummyMeta(type):
    def __getattr__(cls, name):
        return _Dummy()


class _Dummy(object, metaclass=_DummyMeta):
    """只为 QtGui 的画图类准备（测试不看像素）。**被断言的对象一律别用它**。"""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Dummy()

    def __call__(self, *a, **k):
        return _Dummy()


def install():
    """把桩塞进 sys.modules（必须在 import ui.* 之前调用）。"""
    core = types.ModuleType("PySide6.QtCore")
    core.Qt = Qt
    core.QRectF = _Dummy
    core.Signal = lambda *a, **k: _Signal()
    core.QObject = object
    core.QTimer = QTimer
    widgets = types.ModuleType("PySide6.QtWidgets")
    for name in ("QWidget", "QLabel", "QLineEdit", "QPushButton", "QGroupBox",
                 "QListWidget", "QListWidgetItem", "QDialog", "QDialogButtonBox",
                 "QMessageBox", "QInputDialog", "QFileDialog", "QTextBrowser",
                 "QVBoxLayout", "QHBoxLayout", "QFormLayout", "QMainWindow",
                 "QStackedWidget", "QStatusBar", "QCheckBox", "QComboBox",
                 "QPlainTextEdit", "QSpinBox"):
        setattr(widgets, name, globals()[name])
    gui = types.ModuleType("PySide6.QtGui")
    for name in ("QAction", "QBrush", "QColor", "QFont", "QFontDatabase", "QIcon",
                 "QPainter", "QPen", "QPixmap", "QTextCursor"):
        setattr(gui, name, _Dummy)
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = core
    pyside.QtWidgets = widgets
    pyside.QtGui = gui
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = core
    sys.modules["PySide6.QtWidgets"] = widgets
    sys.modules["PySide6.QtGui"] = gui


def reset_all():
    QMessageBox.reset()
    QInputDialog.reset()
    QFileDialog.reset()
    QDialog.exec_queue = []
