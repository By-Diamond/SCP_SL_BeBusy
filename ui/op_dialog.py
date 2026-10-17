# -*- coding: utf-8 -*-
"""「添加操作」弹窗 + **一个操作一个窗口**的参数窗口。

* `AddOpDialog`：选一个操作类型（已在框里、且不允许重复的置灰）。
* `ParamsDialog`：把一个操作的**全部参数放在同一个窗口**里填完（用户要求），
  按参数类型自动出控件：
  | 参数 | 控件 |
  |---|---|
  | 网址 / 文本 / 标题 / 内容 | 单行输入框 |
  | 文件 / 提示音 | 单行输入框 + 「浏览…」 |
  | 窗口 | 可编辑下拉（现列表 + 「刷新」） |
  | 进程名 | 可编辑下拉（**只列现在有声音的程序** + 「刷新」） |
  | 音量 / 渐变 / 延迟 | 数字框（范围写死，越界填不进去） |
  | 按键 | **只读框，按下即识别**（回车 / Esc / 方向键 / 小键盘 / 锁键 都能录） |
* 点「确定」时统一校验（必填 + `OpSpec.validate`）：不合格**就地提示、不关窗**，改完再确定。
* 按键框里：**回车不再是「按确定」**（真的把回车录进去），**Esc = 清空框里内容**（要关窗口用「取消」）。
* **全键盘**都能录（含小键盘 `NumPad1`/`NumPad+`、`CapsLock`/`NumLock`/`ScrollLock`、
  `PrintScreen`/`Pause`/`Menu`）；**Win 键不收录**（Windows 系统保留，按了会提示）。
"""

import os

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QSpinBox, QVBoxLayout)
from PySide6.QtCore import Qt

import config as cfgmod
import key_input
import operations
import volume_actions
import win32_window

TOOLTIP_ROLE = 32                     # Qt.ItemDataRole.ToolTipRole（固定值，不依赖枚举）

AUDIO_FILTER = "音频文件 (*.wav *.mp3 *.m4a *.wma *.flac *.ogg);;所有文件 (*.*)"
ANY_FILTER = "所有文件 (*.*)"

# 数字参数的范围（(下限, 上限, 后缀)）
INT_RANGES = {
    "level": (0, 100, ""),
    "fade_ms": (0, volume_actions.FADE_MAX_MS, " 毫秒"),
    "ms": (0, operations.DELAY_MAX_MS, " 毫秒"),
}
DEFAULT_INT_RANGE = (0, 100, "")


def _red(w):
    """让出错提示显眼一点（画不了好看样式就算了，不影响功能）。"""
    try:
        w.setStyleSheet("color:#c00000;")
    except Exception:
        pass


def qint(v):
    """Qt 的枚举 → int。

    PySide6 6.x 里 `event.key()` / `event.modifiers()` 返回的是**枚举对象**，
    直接 `int(枚举)` 会 TypeError（实测 6.12：
    `int() argument must be ... not 'KeyboardModifier'`）—— 按键框里的每一次
    按键都走这里取值，别再直接 int()。
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(getattr(v, "value", 0) or 0)
        except (TypeError, ValueError):
            return 0


# ----------------------------- 按键框（只读 + 按下即识别） -----------------------------

# Qt 的修饰键掩码 / 特殊键值（固定值，不依赖枚举）
MOD_CTRL = 0x04000000
MOD_SHIFT = 0x02000000
MOD_ALT = 0x08000000
MOD_META = 0x10000000
MOD_KEYPAD = 0x20000000

KEY_ESC = 0x01000000
KEY_TAB = 0x01000001
KEY_BACKSPACE = 0x01000003
KEY_RETURN = 0x01000004
KEY_ENTER = 0x01000005
KEY_CTRL = 0x01000021
KEY_SHIFT = 0x01000020
KEY_ALT = 0x01000023
KEY_META = 0x01000022
KEY_CAPSLOCK = 0x01000024
KEY_NUMLOCK = 0x01000025
KEY_SCROLLLOCK = 0x01000026

MODIFIER_KEYS = {KEY_CTRL: "Ctrl", KEY_SHIFT: "Shift", KEY_ALT: "Alt", KEY_META: "Win"}

QT_SPECIAL = {
    KEY_ESC: "Esc", KEY_TAB: "Tab", 0x01000002: "Tab", KEY_BACKSPACE: "Backspace",
    KEY_RETURN: "Enter", KEY_ENTER: "Enter", 0x01000006: "Insert",
    0x01000007: "Delete", 0x01000010: "Home", 0x01000011: "End",
    0x01000012: "←", 0x01000013: "↑", 0x01000014: "→", 0x01000015: "↓",
    0x01000016: "PageUp", 0x01000017: "PageDown", 0x20: "Space",
    0x01000008: "Pause", 0x01000009: "PrintScreen", 0x0100000A: "PrintScreen",
    0x0100000B: "Clear", KEY_CAPSLOCK: "CapsLock", KEY_NUMLOCK: "NumLock",
    KEY_SCROLLLOCK: "ScrollLock", 0x01000055: "Menu",
    # 媒体键 / 音量键
    0x01000070: "VolumeDown", 0x01000071: "VolumeMute", 0x01000072: "VolumeUp",
    0x01000073: "MediaPlay", 0x01000074: "MediaStop", 0x01000075: "MediaPrev",
    0x01000076: "MediaNext", 0x01000079: "MediaPlay",
}

# 小键盘（数字区）：靠 KeypadModifier 认出来，录成 NumPad1 这种（和主键盘分开）
NUMPAD_QT = {0x2A: "NumPad*", 0x2B: "NumPad+", 0x2D: "NumPad-",
             0x2E: "NumPad.", 0x2F: "NumPad/"}
for _d in range(10):
    NUMPAD_QT[0x30 + _d] = "NumPad%d" % _d


def describe_keypress(key, text, mods):
    """把一次按键变成我们的写法（例如 `Ctrl+Shift+D`）；只按了修饰键 → 返回空串。"""
    mods = qint(mods)
    names = []
    if mods & MOD_CTRL:
        names.append("Ctrl")
    if mods & MOD_SHIFT:
        names.append("Shift")
    if mods & MOD_ALT:
        names.append("Alt")
    if mods & MOD_META:
        names.append("Win")
    key = qint(key)
    if key in MODIFIER_KEYS:                                  # 只按了修饰键（等主键）
        return ""
    name = NUMPAD_QT.get(key) if (mods & MOD_KEYPAD) else None   # 小键盘先认
    if name is None:
        name = QT_SPECIAL.get(key)
    if name is None:
        if 0x30 <= key <= 0x39 or 0x41 <= key <= 0x5A:        # 数字 / 字母
            name = chr(key)
        elif key >= 0x01000030 and key <= 0x01000047:         # F1…F24
            name = "F%d" % (key - 0x01000030 + 1)
        else:
            ch = str(text or "")
            if ch.strip():
                name = ch.strip().upper()
    if not name:
        return ""
    return key_input.format_combo(names, name)


class KeyEdit(QLineEdit):
    """只读输入框：直接在框里按键就识别（回车 / Esc / 方向键 / 小键盘 / 锁键 都行）。

    * 修饰键（Ctrl/Shift/Alt）**按下就记**（例如只想按一下 Ctrl）；
      按住修饰键再按别的键 = 组合键（Ctrl+D），会自动覆盖成组合键。
    * **Win 键不收录**：Windows 系统保留（按下去先弹开始菜单），按了提示一句。
    * Esc = **清空**（用户要求；不是关窗口）。
    """

    HINT_EMPTY = "在这里按一下你要的键…"
    WIN_TEXT = "Win 是系统保留键，不支持（换个键试试）"

    def __init__(self, combo="", note=None):
        super().__init__(key_input.describe(combo) if combo else "")
        self.setReadOnly(True)
        self.setPlaceholderText(self.HINT_EMPTY)
        self.note = note or (lambda _msg: None)   # 给弹窗递一句话（例如 Win 不支持）

    # ---------------- Qt 事件 ----------------

    def keyPressEvent(self, event):                           # noqa: N802 (Qt 命名)
        self._press(qint(event.key()), str(event.text() or ""), qint(event.modifiers()))

    def keyReleaseEvent(self, event):                          # noqa: N802 (Qt 命名)
        self._release(qint(event.key()))

    # ---------------- 真正干活（独立出来便于自检） ----------------

    def _press(self, key, text="", mods=0):
        key = qint(key)
        mods = qint(mods)
        if key == KEY_ESC:                                    # Esc = 清空（不关窗口）
            self.clear()
            self.note("")
            return ""
        if key == KEY_META or (mods & MOD_META):              # Win 系统保留，不收录
            self.note(self.WIN_TEXT)
            return ""
        if key in MODIFIER_KEYS:                              # 修饰键本身也能当主键
            combo = key_input.format_combo([], MODIFIER_KEYS[key])
            self._set(combo)
            self.note("")
            return combo
        combo = describe_keypress(key, text, mods)
        if combo:
            self._set(combo)
            self.note("")
        return combo

    def _release(self, key):
        """松开不用做事：键在**按下**时就记下了（这样单独按 Ctrl 也能录）。"""
        return ""

    def _set(self, combo):
        self.setText(combo)

    def chosen(self):
        return (self.text() or "").strip()


# ----------------------------- 列表填充（窗口 / 进程） -----------------------------


def fill_windows(combo):
    """下拉里放「现在开着的窗口」（值是**进程名**，鼠标悬停看标题）。"""
    try:
        wins = list(win32_window.list_windows())
    except Exception:
        wins = []
    seen = set()
    n = 0
    for _hwnd, title, proc in wins:
        title = (title or "").strip()
        proc = (proc or "").strip()
        if not title or cfgmod.APP_TITLE in title:            # 跳过没标题的 / 本程序自己
            continue
        name = proc or title
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        combo.addItem(name)
        combo.setItemData(combo.count() - 1, title, TOOLTIP_ROLE)
        n += 1
    if not n:
        combo.setToolTip("没找到别的窗口，直接在这里输入标题或进程名")


def fill_procs(combo):
    """下拉里只放「**现在有声音的程序**」（有音频会话的，选完就能直接调音量）。"""
    try:
        procs = list(volume_actions.list_processes())
    except Exception:
        procs = []
    for name, pct in procs:
        combo.addItem(name)
        combo.setItemData(combo.count() - 1, "当前音量 %s%%" % pct, TOOLTIP_ROLE)
    if not procs:
        combo.setToolTip("现在没有程序在出声（有声音的程序才会出现在这里）")


# ----------------------------- 参数窗口 -----------------------------


class ParamsDialog(QDialog):
    """一个操作 = 一个窗口，所有参数一起填。"""

    def __init__(self, spec, values=None, parent=None, title="", which=""):
        super().__init__(parent)
        self.spec = spec
        self.which = which
        self.values_ = {}
        self.key_edit = None
        self.getters = {}
        self.fields = {}                  # key -> 主要控件（自检用）
        self.buttons = {}                 # "browse:文件键" / "reload:列表键" -> 按钮（自检用）
        values = dict(values or {})

        self.setWindowTitle(title or spec.name)
        self.resize(600, 120 + 34 * max(1, len(spec.params)))

        root = QVBoxLayout(self)
        head = QLabel(spec.desc or spec.name)
        head.setWordWrap(True)
        root.addWidget(head)

        form = QFormLayout()
        for key, label, _default, hint in spec.params:
            text = label + ("（可不填）" if key in spec.optional else "")
            form.addRow(QLabel(text), self._make_field(key, hint, values.get(key) or ""))
        root.addLayout(form)

        if self.key_edit is not None:
            tip = QLabel("直接按一下你要的键（组合键也行）；回车 / Esc / 方向键 / 小键盘都能录，"
                         "Win 键不收录。Esc = 清空这里；要关窗口请点「取消」。")
            tip.setWordWrap(True)
            root.addWidget(tip)

        self.err = QLabel("")
        _red(self.err)
        self.err.setWordWrap(True)
        root.addWidget(self.err)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.box.accepted.connect(self.on_ok)
        self.box.rejected.connect(self.reject)
        root.addWidget(self.box)

        first = self.fields.get(spec.params[0][0]) if spec.params else None
        if first is not None:
            try:
                first.setFocus()
            except Exception:
                pass

    # ---------------- 造控件 ----------------

    def _make_field(self, key, hint, cur):
        if key == "keys":
            return self._add_text(key, hint, cur, keyedit=True)
        if key in ("file", "path"):
            return self._add_text(key, hint, cur, browse="audio" if key == "file" else "any")
        if key in ("target", "proc"):
            return self._add_list(key, hint, cur, fill_windows if key == "target" else fill_procs)
        if key in INT_RANGES or key.endswith("_volume") or key == "volume":
            return self._add_int(key, hint, cur)
        return self._add_text(key, hint, cur)

    def _add_text(self, key, hint, cur, browse="", keyedit=False):
        ed = KeyEdit(cur, note=self._note_key) if keyedit else QLineEdit(str(cur or ""))
        if hint:
            ed.setToolTip(hint)
            try:
                ed.setPlaceholderText(hint)
            except Exception:
                pass
        if keyedit:
            self.key_edit = ed
        if not browse:
            self.fields[key] = ed
            self.getters[key] = lambda: ed.text().strip()
            return ed
        row = QHBoxLayout()
        row.addWidget(ed, 1)
        btn = QPushButton("浏览…")
        btn.clicked.connect(lambda *_a: self._browse(ed, browse))
        row.addWidget(btn)
        self.buttons["browse:" + key] = btn
        self.fields[key] = ed
        self.getters[key] = lambda: ed.text().strip()
        return row

    def _browse(self, ed, mode):
        start = ed.text().strip()
        start = start if os.path.isdir(start) else (os.path.dirname(start) or "")
        path, _flt = QFileDialog.getOpenFileName(
            self, "选提示音" if mode == "audio" else "选择文件", start,
            AUDIO_FILTER if mode == "audio" else ANY_FILTER)
        if path:
            ed.setText(path)

    def _add_list(self, key, hint, cur, filler):
        cb = QComboBox()
        cb.setEditable(True)
        if hint:
            cb.setToolTip(hint)
        filler(cb)
        cb.setEditText(str(cur or ""))
        btn = QPushButton("刷新")
        btn.clicked.connect(lambda *_a: self._reload(cb, filler))
        row = QHBoxLayout()
        row.addWidget(cb, 1)
        row.addWidget(btn)
        self.buttons["reload:" + key] = btn
        self.fields[key] = cb
        self.getters[key] = lambda: cb.currentText().strip()
        return row

    def _reload(self, cb, filler):
        keep = cb.currentText()
        cb.clear()
        filler(cb)
        cb.setEditText(keep)

    def _add_int(self, key, hint, cur):
        low, high, suffix = INT_RANGES.get(key, DEFAULT_INT_RANGE)
        sp = QSpinBox()
        sp.setRange(low, high)
        if suffix:
            sp.setSuffix(suffix)
        try:
            v = int(round(float(str(cur).strip() or low)))
        except Exception:
            v = low
        sp.setValue(max(low, min(high, v)))
        if hint:
            sp.setToolTip(hint)
        self.fields[key] = sp
        self.getters[key] = lambda: str(int(sp.value()))
        return sp

    # ---------------- 确定 / 取消 ----------------

    def collect(self):
        """把窗口里的值收集成 dict（键和 `OpSpec.params` 一致）。"""
        return {k: fn() for k, fn in self.getters.items()}

    def check(self, values):
        """必填 + 参数级校验。返回 "" 表示没问题，否则是**给人看的原因**。"""
        for key, label, default, _hint in self.spec.params:
            if key in self.spec.optional:
                continue
            v = values.get(key)
            if (v is None or str(v).strip() == "") and str(default).strip() == "":
                return "「%s」不能为空。" % label
        if self.spec.validate is not None:
            try:
                ok, why = self.spec.validate(values)
            except Exception as e:
                return "%s 参数校验出错：%r" % (self.spec.name, e)
            if not ok:
                return why
        return ""

    def on_ok(self):
        values = self.collect()
        why = self.check(values)
        if why:
            self.err.setText("⚠ " + why)                       # 就地报错，不关窗口
            return False
        self.err.setText("")
        self.values_ = values
        self.accept()
        return True

    def keyPressEvent(self, event):                            # noqa: N802 (Qt 命名)
        """有按键框时，Esc = 清空按键（按用户要求），不当成「关窗口」。"""
        if self.key_edit is not None and qint(event.key()) == KEY_ESC:
            self.key_edit.clear()
            return
        super().keyPressEvent(event)

    def _note_key(self, msg):
        """按键框递出来的一句话（例如「Win 不支持」）：就地显示，不关窗口。"""
        try:
            self.err.setText(("⚠ " + msg) if msg else "")
        except Exception:
            pass

    def values(self):
        return dict(self.values_)


def ask_params(parent, spec, values=None, title="", which=""):
    """弹**一个**窗口把这个操作的所有参数问完。

    返回 (params, 是否已作答)；取消 → ({}, False)。
    """
    if spec is None:
        return {}, False
    dlg = ParamsDialog(spec, values, parent, title=title, which=which)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return {}, False
    return dlg.values(), True


# ----------------------------- 选操作类型 -----------------------------


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
