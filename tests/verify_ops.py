# -*- coding: utf-8 -*-
"""验证：操作的注册 / 执行 / 界面 / 配置往返（含 3 个新操作）。

跑法（源码目录下）：`python tests/verify_ops.py`
纯 Python + 桩，不需要装 PySide6 —— 所以 Linux 上也能跑。
"""

import os
import shutil
import sys
import threading
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)                                    # tests/ 的上一级 = 项目根
sys.path.insert(0, HERE)
sys.path.insert(0, PROJ)

import qtstub                                                   # noqa: E402
qtstub.install()

import config as cfgmod                                        # noqa: E402
import operations as ops                                       # noqa: E402
import opsmodel                                                # noqa: E402
import win32_window as w32                                     # noqa: E402

_REAL_LIST_WINDOWS = w32.list_windows                          # [B] 会把它换成假窗口表，先留真身

TMP = os.path.join(HERE, "_newops_tmp")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP, exist_ok=True)

PASS, FAILS = [], []


def ok(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("    PASS %s%s" % (name, (" | %s" % detail) if detail and not cond else ""))
    else:
        FAILS.append(name)
        print("    FAIL %s | %s" % (name, detail))


def check(name, got, want):
    ok(name, got == want, "得到 %r 期望 %r" % (got, want))


def p(t):
    print("\n" + t)


class _StatusAudio(object):
    """只给状态栏用的媒体状态桩（state_text 想改就改）。"""

    def __init__(self):
        self.text = "未知"

    def state_text(self):
        return self.text


class FakeCore(object):
    """够 OpBox / AboutPage / 状态栏 用就行。"""

    def __init__(self, path):
        self.cfg = cfgmod.Config(path)
        self.logs = []
        self.log = types.SimpleNamespace(log=self.logs.append,
                                         path=os.path.join(TMP, "run.log"))
        self.saved = []
        self.audio = _StatusAudio()

    def save_ops(self, which, items):
        self.saved.append((which, items))
        self.cfg.set_ops(which, items)
        self.cfg.save()

    def manual_test_ops(self, which):
        self.tested = which

    def player_log_now(self):
        return os.path.join(TMP, "Player.log"), False

    def diagnostics(self):
        return "诊断信息（测试）"


class FakeCtx(ops.OpContext):
    """真 OpContext + 假的外部动作。"""

    def __init__(self, hwnd=0, found=None, is_game=None, game_found=None):
        ops.OpContext.__init__(self, audio=None, hwnd=hwnd, logger=self._line)
        self.lines = []
        self.calls = []
        self.hwnd_found = hwnd if found is None else found
        self.lookup_window = self._lookup
        # 游戏窗口：默认"缓存句柄有效、现查也返回它"；传参可模拟游戏重启 / 句柄失效
        self.is_game = (lambda h: bool(h)) if is_game is None else is_game
        self.game_found = hwnd if game_found is None else game_found
        self.find_game = self._find_game
        self.focus = lambda h: (self.calls.append(("focus", h)), True)[1]
        self.minimize = lambda h: (self.calls.append(("minimize", h)), True)[1]
        self.open_file = lambda p: (self.calls.append(("open_file", p)), (True, "已打开"))[1]

    def _line(self, msg):
        self.lines.append(msg)

    def _lookup(self, target):
        self.calls.append(("lookup", target))
        return self.hwnd_found

    def _find_game(self):
        self.calls.append(("find_game",))
        return self.game_found


# ============================================================ [A] 注册表
p("[A] 操作注册表")

check("A1 操作总数 8", len(ops.all_specs()), 8)
check("A2 新增三条在最后", [s.type for s in ops.all_specs()][-3:],
      ["focus_window", "minimize_window", "run_file"])

_s = ops.get_spec("focus_window")
check("A3 切换到界面：名字/参数/可重复", (_s.name, [x[0] for x in _s.params], _s.allow_multiple),
      ("切换到界面", ["target"], True))
_s = ops.get_spec("minimize_window")
check("A4 最小化界面：名字/参数/可重复", (_s.name, [x[0] for x in _s.params], _s.allow_multiple),
      ("最小化界面", ["target"], True))
_s = ops.get_spec("run_file")
check("A5 执行文件：名字/参数/可重复", (_s.name, [x[0] for x in _s.params], _s.allow_multiple),
      ("执行文件", ["path"], True))

import ui.op_dialog as od                                       # noqa: E402
_missing = [k for spec in ops.all_specs() for k, _l, _d, _h in spec.params
            if k not in od.ASKERS]
check("A6 每个参数键都有专用弹窗（不会漏配）", _missing, [])

check("A7 列表文字含参数",
      ops.describe_item({"type": "focus_window", "params": {"target": "chrome.exe"}}),
      "切换到界面 — chrome.exe")
check("A8 空参数被拦住（不可执行）",
      ops.validate_item({"type": "focus_window", "params": {"target": ""}}),
      (False, "切换到界面 缺少窗口"))
check("A9 空文件被拦住", ops.validate_item({"type": "run_file", "params": {"path": ""}}),
      (False, "执行文件 缺少文件"))

# ============================================================ [B] win32_window
p("[B] 窗口查找（Linux 侧的安全退化 + 匹配规则）")

ok("B1 非 Windows 上 available()=False", w32.available() is False)
check("B2 非 Windows 上 list_windows() 返回空表（不崩）", w32.list_windows(), [])
check("B3 非 Windows 上 find_window 返回 0", w32.find_window("chrome.exe"), 0)
ok("B4 非 Windows 上 focus/minimize 返回 False（不崩）",
   w32.focus_window(1234) is False and w32.minimize_window(1234) is False)

FAKE_WINS = [
    (11, "chrome 相关的东西 - 记事本", "notepad.exe"),        # 标题里有 chrome，但进程不是
    (22, "新标签页 - Google Chrome", "chrome.exe"),
    (33, "report.txt - 记事本", "notepad.exe"),
    (44, "Visual Studio Code", "Code.exe"),
]
w32.list_windows = lambda: list(FAKE_WINS)

check("B5 进程名全等优先（不被标题干扰）", w32.find_window("chrome.exe"), 22)
check("B6 只写 chrome 也能命中 chrome.exe", w32.find_window("chrome"), 22)
check("B7 大小写不敏感", w32.find_window("CHROME.EXE"), 22)
check("B8 标题包含命中", w32.find_window("report.txt"), 33)
check("B9 进程名包含命中", w32.find_window("code"), 44)
check("B10 找不到 → 0", w32.find_window("根本不存在的窗口"), 0)
check("B11 空串 → 0", w32.find_window("   "), 0)

# ============================================================ [C] 执行
p("[C] 执行")

ctx = FakeCtx(hwnd=2222)
check("C1 切换到界面：查窗口 → 置前",
      (ops.run_item({"type": "focus_window", "params": {"target": "chrome.exe"}}, ctx),
       ctx.calls),
      ((True, "已切到「chrome.exe」"), [("lookup", "chrome.exe"), ("focus", 2222)]))

ctx = FakeCtx(hwnd=0)
r = ops.run_item({"type": "minimize_window", "params": {"target": "discord.exe"}}, ctx)
check("C2 没找到窗口 → 明确报错（不静默）", r, (False, "没找到窗口：discord.exe"))
ok("C3 没找到时不会去动窗口", ("minimize", 0) not in ctx.calls, str(ctx.calls))

ctx = FakeCtx(hwnd=3333)
check("C4 最小化界面：查窗口 → 最小化",
      (ops.run_item({"type": "minimize_window", "params": {"target": "chrome"}}, ctx),
       ctx.calls),
      ((True, "已最小化「chrome」"), [("lookup", "chrome"), ("minimize", 3333)]))

ctx = FakeCtx()
check("C5 执行文件：交给 ctx.open_file",
      (ops.run_item({"type": "run_file", "params": {"path": "C:/Tools/a.exe"}}, ctx),
       ctx.calls),
      ((True, "已打开"), [("open_file", "C:/Tools/a.exe")]))
check("C6 执行文件：空路径被参数校验拦住",
      ops.run_item({"type": "run_file", "params": {}}, FakeCtx())[0], False)

_f = os.path.join(TMP, "a file.txt")
open(_f, "w").write("x")
check("C7 真·打开文件：不存在的路径报错",
      ops.open_file_default(os.path.join(TMP, "没有这个.exe")),
      (False, "文件不存在：%s" % os.path.join(TMP, "没有这个.exe")))
_spawn = []
_real_popen = ops.subprocess.Popen
ops.subprocess.Popen = lambda argv, *a, **k: _spawn.append(argv)
try:
    r = ops.open_file_default(_f)
finally:
    ops.subprocess.Popen = _real_popen
ok("C8 真·打开文件：存在的文件交给系统打开", r[0] and _spawn and _spawn[0][-1] == _f,
   "%s | %s" % (r, _spawn))
ok("C9 路径支持 ~ 展开", ops._expand_path("~").startswith(os.path.expanduser("~")))

ctx = FakeCtx(hwnd=4444)
stat = ops.run_list([{"type": "focus_window", "params": {"target": "chrome"}},
                     {"type": "minimize_window", "params": {"target": ""}},      # 参数缺失 → 失败
                     {"type": "run_file", "params": {"path": "C:/x.exe"}}], ctx)
check("C10 列表里单条失败不中断后面的", (stat["ok"], stat["fail"], stat["total"]), (2, 1, 3))

# ============================================================ [D] 界面
p("[D] 界面（Qt 桩）")

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtWidgets import (QMessageBox, QFileDialog,        # noqa: E402
                               QListWidgetItem)
from ui.page_features import OpBox                              # noqa: E402
from ui import op_dialog                                        # noqa: E402

qtstub.reset_all()
core = FakeCore(os.path.join(TMP, "settings.json"))
box = OpBox(core, "death", "死亡后")

dlg = op_dialog.AddOpDialog(box.op_list, None)
check("D1 添弹窗列出全部 8 个操作", dlg.list.count(), 8)
row_focus = None
for i in range(dlg.list.count()):
    if dlg.list.item(i).data(Qt.ItemDataRole.UserRole) == "focus_window":
        row_focus = dlg.list.item(i)
ok("D2 「切换到界面」可重复 → 有了一条也不置灰",
   bool(row_focus.flags() & Qt.ItemFlag.ItemIsEnabled), str(row_focus.flags()))
ok("D2b 灰项仍只给已存在且不允许重复的（媒体播放）",
   not (dlg.list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled))

# 参数弹窗分派：target → ask_window
_called = []


def _fake_asker(parent, default=""):
    _called.append(default)
    return "chrome.exe", True


_real_target_asker = op_dialog.ASKERS["target"]
op_dialog.ASKERS["target"] = _fake_asker
try:
    check("D3 ask_param 把 target 交给窗口选择弹窗",
          op_dialog.ask_param(None, "target", "窗口", "旧值"), ("chrome.exe", True))
    check("D3b 并把当前值作为默认值传进去", _called, ["旧值"])

    QMessageBox.reset()
    ok_add = box._add_type("focus_window")
    ok("D4 添加「切换到界面」成功（带参数）", ok_add is True, str(core.logs[-1:]))
    check("D5 参数写进列表", box.op_list.items[-1],
          {"type": "focus_window", "params": {"target": "chrome.exe"}})
    check("D6 立即写进配置", core.cfg.ops("death")[-1]["params"]["target"], "chrome.exe")
    check("D7 列表文字带参数", box.list.item(box.list.count() - 1).text(), "切换到界面 — chrome.exe")
    check("D7b 底部提示仍是「共 N 条」", box.hint.text(), "共 2 条")

    # 取消
    op_dialog.ASKERS["target"] = lambda parent, default="": ("", False)
    ok("D8 取消参数弹窗 → 不加", box._add_type("focus_window") is False)
    check("D9 取消后列表没变", len(box.op_list), 2)

    # 空值
    op_dialog.ASKERS["target"] = lambda parent, default="": ("   ", True)
    QMessageBox.reset()
    ok("D10 空值 → 弹警告 + 不加", box._add_type("focus_window") is False)
    ok("D10b 警告文案说明哪个不能为空",
       any("窗口」不能为空" in c[2] for c in QMessageBox.calls), str(QMessageBox.calls[-1:]))
    check("D11 空值后列表没变", len(box.op_list), 2)

    # 编辑
    box.list.setCurrentRow(1)
    op_dialog.ASKERS["target"] = lambda parent, default="": ("discord.exe", True)
    box.edit()
    check("D12 编辑改了参数并落盘",
          (box.op_list.items[1]["params"]["target"], core.cfg.ops("death")[1]["params"]["target"]),
          ("discord.exe", "discord.exe"))
finally:
    op_dialog.ASKERS["target"] = _real_target_asker

# 窗口选择弹窗本体
_wins = [
    (1, "SCP:SL BeBusy v0.1.0 — 存活", "python.exe"),         # 本程序自己 → 应被跳过
    (2, "新标签页 - Google Chrome", "chrome.exe"),
    (3, "report.txt - 记事本", "notepad.exe"),
    (4, "", "ghost.exe"),                                     # 没标题 → 跳过
]
_real_lw = w32.list_windows
w32.list_windows = lambda: list(_wins)
try:
    w = op_dialog.WindowPickerDialog(None, "")
    check("D13 只列出别的程序的窗口（跳过自己 + 空标题）", w.list.count(), 2)
    check("D14 行文字 = 标题 — 进程名", w.list.item(0).text(), "新标签页 - Google Chrome    — chrome.exe")
    check("D15 空表之外的计数提示", w.count.text(), "共 2 个窗口")
    w.list.doubleClickRow(0)
    check("D16 双击 = 填入进程名（标题会变，进程名更稳）", w.chosen(), "chrome.exe")
    check("D17 手打标题也认", (w.ed.setText("记事本"), w.chosen())[1], "记事本")
    w2 = op_dialog.WindowPickerDialog(None, "旧值")
    check("D18 打开时带上原值", w2.chosen(), "旧值")
    w32.list_windows = lambda: []
    w3 = op_dialog.WindowPickerDialog(None, "")
    ok("D19 一个窗口都没有时给出提示（不空白）", "没找到窗口" in w3.count.text(), w3.count.text())
finally:
    w32.list_windows = _real_lw

# 文件选择弹窗
QFileDialog.reset()
QFileDialog.result = ("C:/Tools/run.bat", "所有文件 (*.*)")
check("D20 ask_file 选中 → 返回路径", op_dialog.ask_file(None, ""), ("C:/Tools/run.bat", True))
QFileDialog.reset()
check("D21 ask_file 取消 → 未作答", op_dialog.ask_file(None, "C:/x.exe"), ("", False))

check("D22 三个新操作在添弹窗里都能被选中",
      [(dlg.list.item(i).data(Qt.ItemDataRole.UserRole),
        bool(dlg.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled))
       for i in range(dlg.list.count())][-3:],
      [("focus_window", True), ("minimize_window", True), ("run_file", True)])

from ui.page_features import NOTE_TEXT                           # noqa: E402
check("D23 框下的提示改成了中性说法",
      NOTE_TEXT, "同一个操作可出现在两个框里；同一个框里部分操作不能重复选。")
check("D24 提示里不再点名只有「打开网页」能多条",
      "打开网页" in NOTE_TEXT, False)

# ============================================================ [E] 配置往返
p("[E] 配置往返（重启后还在）")

check("E1 新操作已落盘", len(cfgmod.Config(core.cfg.path).ops("death")), 2)
cfg2 = cfgmod.Config(core.cfg.path)
check("E2 参数完整保留（第 0 条是默认的媒体播放）",
      cfg2.ops("death"),
      [{"type": "media_play", "params": {}},
       {"type": "focus_window", "params": {"target": "discord.exe"}}])
check("E3 老配置（缺参数）也能被补齐",
      ops.normalize_item({"type": "run_file"}), {"type": "run_file", "params": {"path": ""}})
check("E4 列表规则：可重复的操作能加多条",
      opsmodel.OpList([{"type": "run_file", "params": {"path": "a"}}])
      .can_add("run_file"), (True, ""))

# ============================================================ [F] 老操作没被改坏
p("[F] 回归：原有 5 个操作照旧")


class FakeAudio(object):
    def __init__(self):
        self.sent = []

    def play(self, why=""):
        self.sent.append("play")
        return True

    def pause(self, why=""):
        self.sent.append("pause")
        return True


ctx = FakeCtx(hwnd=999)
ctx.audio = FakeAudio()
ctx.open_url = lambda u: (ctx.calls.append(("open_url", u)), (True, "已打开 %s" % u))[1]

check("F1 媒体播放照旧", ops.run_item({"type": "media_play", "params": {}}, ctx),
      (True, "已发送播放键"))
check("F2 媒体暂停照旧", ops.run_item({"type": "media_pause", "params": {}}, ctx),
      (True, "已发送暂停键"))
check("F3 切换到游戏界面照旧（用锁定到的 hwnd）",
      (ops.run_item({"type": "focus_game", "params": {}}, ctx), ctx.calls[-1]),
      ((True, "已切到游戏界面"), ("focus", 999)))
check("F4 游戏最小化照旧", ops.run_item({"type": "minimize_game", "params": {}}, ctx),
      (True, "已把游戏最小化"))
check("F5 打开网页照旧（协议头自动补）",
      ops.run_item({"type": "open_url", "params": {"url": "www.bilibili.com"}}, ctx)[0], True)
check("F6 网址没写协议头也能用", ops.normalize_url("b23.tv/x"), "https://b23.tv/x")
check("F7 老操作的名字/顺序没变",
      [s.name for s in ops.all_specs()][:5],
      ["媒体播放", "媒体暂停", "打开网页", "切换到游戏界面", "游戏最小化"])
check("F8 未知操作类型老实报错",
      ops.run_item({"type": "nope", "params": {}}, ctx)[0], False)
check("F9 游戏没开时切换有明确提示",
      ops.run_item({"type": "focus_game", "params": {}}, FakeCtx(hwnd=0))[1],
      "没找到游戏窗口（游戏没开？）")

# ============================================================ [G] 冒烟
p("[G] 冒烟：所有模块还能导入、关键常量没变")

import win32stub                                                # noqa: E402
win32stub.install()                                            # 给 Linux 补上 ctypes.WinDLL
import audio_actions                                            # noqa: E402
import autostart                                                # noqa: E402
import logbus                                                   # noqa: E402
import scpsl_state                                              # noqa: E402
import trigger as triggermod                                    # noqa: E402
import appcore                                                  # noqa: E402

check("G1 死亡门仍是 0.7s", triggermod.DEATH_SETTLE_S, 0.7)
check("G2 版本/作者/介绍没变",
      (cfgmod.VERSION, cfgmod.AUTHOR, cfgmod.DESCRIPTION),
      ("0.1.0", "By Diamond",
       "自动识别玩家存活/死亡 并执行相关操作，未修改游戏本体，不是作弊行为"))
ok("G3 判定核心还在（类 + 关键方法 + 两个路径常量）",
   hasattr(scpsl_state, "Detector") and hasattr(scpsl_state.Detector, "stop_all")
   and hasattr(scpsl_state.Detector, "start")
   and bool(scpsl_state.PLAYER_LOG) and bool(scpsl_state.STATE_LOG))
ok("G4 窗口模块的 4 个入口齐全",
   all(callable(getattr(w32, n)) for n in
       ("list_windows", "find_window", "focus_window", "minimize_window")))
ok("G5 操作上下文带上了新钩子",
   all(hasattr(ops.OpContext(), n) for n in ("lookup_window", "open_file", "focus", "minimize")))
ok("G6 托盘/日志/自启模块导入无恙",
   hasattr(logbus, "LogBus") and hasattr(autostart, "VALUE_NAME")
   and hasattr(audio_actions, "AudioBackend"))
ok("G7 应用内核还能装配（配置 + 日志总线）", hasattr(appcore, "AppCore"))

# ============================================================ [H] 关于页
p("[H] 关于页：项目链接说明")

import inspect                                                  # noqa: E402
from ui.page_about import (AboutPage, BILI_URL, GH_URL,         # noqa: E402
                           REPO_URL)

about = AboutPage(core)
ok("H1 GitHub 仓库链接", REPO_URL in about.links.text(), about.links.text())
ok("H2 GitHub 作者主页链接", GH_URL in about.links.text())
ok("H3 Bilibili 主页链接", BILI_URL in about.links.text())
check("H4 三个链接的文案", [t for t in ("GitHub 仓库", "作者主页", "Bilibili")
                        if t in about.links.text()],
      ["GitHub 仓库", "作者主页", "Bilibili"])
ok("H5 反馈 bug 提示", "反馈 bug：请到 GitHub 提交" in about.links.text())
ok("H6 链接可点（富文本 + 放行外链）",
   about.links.text_format == Qt.RichText and about.links.open_external is True)
check("H7 链接用的是 https", sum(1 for u in (REPO_URL, GH_URL, BILI_URL)
                              if u.startswith("https://")), 3)
ok("H8 用法说明还在", "怎么用" in about.usage.html)
ok("H9 关于页不再有日志框", "log_box" not in inspect.getsource(AboutPage))
ok("H10 底部路径信息还在", core.cfg.path in about.info.text(), about.info.text()[:60])

# ============================================================ [I] 状态栏
p("[I] 状态栏：竖线只留中间、最后不封口；媒体状态会自己刷新")

from PySide6.QtWidgets import QLabel                             # noqa: E402
from ui import util as uimod                                     # noqa: E402
import ui.main_window as mwmod                                   # noqa: E402
from ui.main_window import MainWindow                            # noqa: E402

check("I1 死亡·观察者那段（竖线前留空、末尾不封口）",
      uimod.status_texts(False, False, "未知"),
      {"state": "状态：死亡·观察者  |", "media": "媒体：未知 |",
       "plog": "Player.log：未找到"})
check("I2 存活 / 已找到 / 播放中",
      uimod.status_texts(True, True, "播放中"),
      {"state": "状态：存活  |", "media": "媒体：播放中 |",
       "plog": "Player.log：已找到"})
check("I3 整条只留两处竖线，最后一段不封口",
      [t.count("|") for t in uimod.status_texts(False, True, "暂停中").values()],
      [1, 1, 0])
ok("I4 竖线不贴着文字（前面留了空）",
   "者  |" in uimod.status_texts(False, True, "未知")["state"])

# 真主窗口的刷新逻辑（不跑 __init__：不需要整棵页面树）
mwin = MainWindow.__new__(MainWindow)
mwin.core = core
mwin.log_page = types.SimpleNamespace(append_line=lambda line, level="info": None)
mwin.lbl_state, mwin.lbl_media, mwin.lbl_plog = QLabel(), QLabel(), QLabel()
mwin._alive = False
mwin._plog_found = False
mwin._plog_path = None
mwin.refresh_status()
check("I5 三栏文字（死亡·观察者 / 未知 / 未找到）",
      [mwin.lbl_state.text(), mwin.lbl_media.text(), mwin.lbl_plog.text()],
      ["状态：死亡·观察者  |", "媒体：未知 |", "Player.log：未找到"])
mwin._alive = True
core.audio.text = "播放中"
mwin.refresh_status()
check("I6 状态和媒体都跟着变",
      [mwin.lbl_state.text(), mwin.lbl_media.text()],
      ["状态：存活  |", "媒体：播放中 |"])
ok("I7 Player.log 完整路径挂在提示里（不再挤在状态栏上）",
   mwin.lbl_plog.tooltip.endswith("Player.log"), mwin.lbl_plog.tooltip)
core.audio.text = "暂停中"
mwin.append_log("[media] 已发媒体播放/暂停键（播放）")
check("I8 一发媒体键，媒体那栏立刻变（不等下一次状态变化）",
      mwin.lbl_media.text(), "媒体：暂停中 |")
core.audio.text = "未知"
mwin.append_log("普通日志不会去刷状态栏")
check("I9 普通日志不触发刷新（省着点）", mwin.lbl_media.text(), "媒体：暂停中 |")
_src = inspect.getsource(mwmod)
ok("I10 状态栏每秒自己刷一次（QTimer → refresh_status）",
   "setInterval(1000)" in _src
   and "status_timer.timeout.connect(self.refresh_status)" in _src)
ok("I11 去掉了 Qt 自带那道竖线（改用我们自己的间距）",
   "QStatusBar::item { border: none; }" in _src and "padding-left" in _src)

# ============================================================ [J] 媒体状态
p("[J] 媒体状态：键真发出去了才认，发失败退回「未知」")

_real_send = audio_actions.send_media_play_pause


def _audio(send_ok, sent=None):
    def fake():
        if sent is not None:
            sent.append(1)
        return send_ok
    audio_actions.send_media_play_pause = fake
    return audio_actions.AudioBackend(logger=lambda m: None)


_sent = []
a = _audio(True, _sent)
check("J1 键发成功 → 状态变「播放中」", (a.play("测试"), a.wait_idle(), a.state_text()),
      (True, True, "播放中"))
check("J2 已在播放就不再按键（播放不能播两次）",
      (a.play("测试"), len(_sent)), (False, 1))
check("J3 暂停：发成功 → 「暂停中」", (a.pause("测试"), a.wait_idle(), a.state_text()),
      (True, True, "暂停中"))
check("J4 已在暂停就不再按键", (a.pause("测试"), len(_sent)), (False, 2))

a2 = _audio(False)
check("J5 键没发成功 → 退回「未知」（不谎报成播放中）",
      (a2.play("测试"), a2.wait_idle(), a2.state_text()), (True, True, "未知"))
check("J6 暂停键同样不谎报",
      (a2.pause("测试"), a2.wait_idle(), a2.state_text()), (True, True, "未知"))
a3 = _audio(False)
check("J7 未知时 toggle 后仍是未知（不瞎猜）",
      (a3.toggle("测试"), a3.wait_idle(), a3.state_text()), (True, True, "未知"))
check("J8 新开一个后端 = 未知（启动时不瞎猜）",
      audio_actions.AudioBackend(logger=lambda m: None).state_text(), "未知")
_a9 = audio_actions.AudioBackend(logger=lambda m: None)
check("J9 mark 手动对齐能用（托盘「手动」走这条路）",
      [(_a9.mark(v), _a9.state_text())[1] for v in (True, False, None)],
      ["播放中", "暂停中", "未知"])
audio_actions.send_media_play_pause = _real_send

# ============================================================ [K] 游戏窗口实时查找
p("[K] 游戏窗口：执行时现查现验（游戏重启换句柄也照样生效）")

_real_w32 = (w32.available, w32.is_window, w32.proc_name_of, w32.list_windows,
             w32.window_area, w32.is_minimized)
try:
    w32.available = lambda: True                     # 假装在 Windows 上
    w32.is_window = lambda h: bool(h)
    w32.proc_name_of = lambda h: {11: "notepad.exe", 55: "scpsl.exe",
                                  77: "scpsl.exe"}.get(h, "")
    w32.list_windows = lambda: [
        (11, "chrome 相关的东西 - 记事本", "notepad.exe"),
        (77, "SCP: Secret Laboratory", "scpsl.exe"),
    ]
    check("K1 现查能认出游戏窗口（进程名含 scpsl）", w32.find_game_window(), 77)
    check("K2 进程不是游戏 → 验不过（不会误伤别人的窗口）", w32.is_game_window(11), False)
    check("K3 是游戏窗口 → 验得过", w32.is_game_window(77), True)
    check("K4 句柄 0 一律不是游戏窗口", w32.is_game_window(0), False)
    w32.list_windows = lambda: [(11, "x", "SCPSL.EXE")]      # 大写进程名也要认得出
    check("K4b 大小写不敏感", w32.find_game_window(), 11)

    w32.list_windows = lambda: [
        (55, "SCPSL 启动器", "scpsl.exe"),
        (77, "SCP: Secret Laboratory", "scpsl.exe"),
    ]
    w32.window_area = lambda h: {55: 100, 77: 1920 * 1080}.get(h, 0)
    w32.is_minimized = lambda h: False
    check("K5 多个游戏窗口 → 挑面积最大的主窗口", w32.find_game_window(), 77)
    w32.is_minimized = lambda h: h == 77
    check("K6 主窗口被最小化 → 挑没被最小化的那个", w32.find_game_window(), 55)

    w32.list_windows = lambda: [(11, "chrome 相关的东西 - 记事本", "notepad.exe")]
    check("K7 游戏没开 → 0（绝不返回旧句柄凑数）", w32.find_game_window(), 0)
finally:
    (w32.available, w32.is_window, w32.proc_name_of, w32.list_windows,
     w32.window_area, w32.is_minimized) = _real_w32

# —— 执行层：模拟「游戏重启换了句柄」等场景 ——
_restart = FakeCtx(hwnd=1111, is_game=lambda h: False, game_found=2222)
check("K8 游戏重启：旧句柄验不过 → 现查新句柄，打在**新**句柄上",
      (ops.run_item({"type": "minimize_game", "params": {}}, _restart), _restart.calls[-1]),
      ((True, "已把游戏最小化（窗口换了，已重找）"), ("minimize", 2222)))
ok("K9 绝不拿过期句柄凑数", ("minimize", 1111) not in _restart.calls, str(_restart.calls))

_recyc = FakeCtx(hwnd=1111, is_game=lambda h: False, game_found=2222)
ops.run_item({"type": "focus_game", "params": {}}, _recyc)
check("K10 切换到游戏界面同样现查（复活后那一步也一起修好）",
      _recyc.calls[-1], ("focus", 2222))

_cached = FakeCtx(hwnd=3333)
check("K11 缓存句柄仍有效 → 直接用，不白枚举",
      (ops.run_item({"type": "minimize_game", "params": {}}, _cached), _cached.calls),
      ((True, "已把游戏最小化"), [("minimize", 3333)]))

_nogame = FakeCtx(hwnd=0, is_game=lambda h: False, game_found=0)
check("K12 游戏没开 → 老实报失败",
      ops.run_item({"type": "minimize_game", "params": {}}, _nogame),
      (False, "没找到游戏窗口（游戏没开？）"))
ok("K13 找不着就什么都不动",
   [c for c in _nogame.calls if c[0] != "find_game"] == [], str(_nogame.calls))

_dead = FakeCtx(hwnd=4444)
_dead.minimize = lambda h: (_dead.calls.append(("minimize", h)), False)[1]
check("K14 最小化没生效 → 报 ⚠（不再谎报「已把游戏最小化」）",
      ops.run_item({"type": "minimize_game", "params": {}}, _dead),
      (False, "游戏最小化没生效（窗口可能已变）"))


def _bare_det(hwnd):
    """不跑 __init__ 的 Detector（不碰真文件），只给自愈逻辑要用的字段。"""
    d = scpsl_state.Detector.__new__(scpsl_state.Detector)
    d.lock = threading.Lock()
    d.counts = {"death": 0, "alive": 0, "redraw": 0}
    d.state = scpsl_state.STATE_ALIVE
    d.t_death = 0.0
    d.last_redraw_t = None
    d.pre_log_jump_t = None
    d.tail_pending = False
    d.scpsl_hwnd = hwnd
    d._f_log = d._csv = None
    d.on_note = d.on_change = d.on_death_seen = None
    return d


_real_self = (scpsl_state.is_game_window, scpsl_state.find_scpsl_windows)
try:
    scpsl_state.is_game_window = lambda h: h in (777, 888)   # 假造：只有这俩是游戏窗口
    d = _bare_det(1111)
    d.on_redraw(888)
    check("K15 红跳来自新的游戏窗口 → 自动重锁到新句柄", d.scpsl_hwnd, 888)

    d2 = _bare_det(1111)
    d2.on_redraw(999)                                        # 别的进程的窗口
    check("K16 别的窗口的红跳 → 不动锁定", d2.scpsl_hwnd, 1111)

    d3 = _bare_det(0)
    scpsl_state.find_scpsl_windows = lambda: [{"hwnd": 777}]
    check("K17 循环重查找到游戏 → 记下句柄", (d3._find_scpsl(), d3.scpsl_hwnd), (True, 777))
    scpsl_state.find_scpsl_windows = lambda: []
    check("K18 重查找不到 → 句柄清零（不留过期值）",
          (d3._find_scpsl(), d3.scpsl_hwnd), (True, 0))
finally:
    scpsl_state.is_game_window, scpsl_state.find_scpsl_windows = _real_self


# —— 端到端：**真** win32_window 函数 + 假 Win32 世界（模拟游戏重启 / 句柄被回收） ——
class _FakeKernel(object):
    """只够 win32_window._proc_name 用。"""

    def __init__(self, world):
        self.world = world

    def OpenProcess(self, access, inherit, pid):
        self.world._pid = int(pid or 0)
        return 1 if self.world._pid in self.world.procs else 0

    def QueryFullProcessImageNameW(self, h, flags, buf, size):
        buf.value = self.world.procs.get(self.world._pid, "")
        return 1

    def CloseHandle(self, h):
        return 1


def _hwnd(x):
    """把 c_void_p / int 都转成 int（假 Win32 收参数用；真 API 直接收指针）。"""
    try:
        return int(getattr(x, "value", x) or 0)
    except Exception:
        return 0


class _FakeWin(object):
    """假 Win32：一个窗口世界 + 最小化/前台状态。够 win32_window 用。"""

    def __init__(self, wins, areas=None):
        self.wins = {int(h): v for h, v in wins.items()}     # hwnd -> (标题, 进程名, pid)
        self.areas = areas or {}
        self.procs = {v[2]: "/x/" + v[1] for v in self.wins.values()}
        self.iconic = set()
        self.fg = 0
        self.deny_fg = False                                 # True = 假装系统不给前台
        self.fg_becomes = 0                                  # 非 0 = 系统把别的窗口推到前台
        self.fg_old = 0                                      # 异步：切完之前前台还是旧的
        self.fg_delay = 0                                    # 前 N 次查询仍返回旧前台
        self.iconic_delay = 0                                # 前 N 次查询还没最小化完
        self._pid = 0

    def _title(self, hwnd):
        return self.wins.get(_hwnd(hwnd), ("", "", 0))[0]

    # --- user32 ---
    def IsWindow(self, hwnd):
        return 1 if _hwnd(hwnd) in self.wins else 0

    def IsWindowVisible(self, hwnd):
        return 1 if _hwnd(hwnd) in self.wins else 0

    def IsIconic(self, hwnd):
        if self.iconic_delay > 0:                            # 最小化是异步的
            self.iconic_delay -= 1
            return 0
        return 1 if _hwnd(hwnd) in self.iconic else 0

    def GetWindowTextLengthW(self, hwnd):
        return len(self._title(hwnd))

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = self._title(hwnd)
        return len(buf.value)

    def GetWindowThreadProcessId(self, hwnd, out):
        out._obj.value = self.wins.get(_hwnd(hwnd), ("", "", 0))[2]
        return 1

    def GetWindowRect(self, hwnd, out):
        w, h = self.areas.get(_hwnd(hwnd), (100, 100))
        out._obj.left, out._obj.top, out._obj.right, out._obj.bottom = 0, 0, w, h
        return 1

    def EnumWindows(self, cb, lparam):
        for hwnd in list(self.wins):
            cb(hwnd, 0)
        return 1

    def ShowWindow(self, hwnd, cmd):
        if _hwnd(hwnd) not in self.wins:                     # 窗口没了 → 什么也不会发生
            return 0
        if cmd == w32.SW_MINIMIZE:
            self.iconic.add(_hwnd(hwnd))
        elif cmd == w32.SW_RESTORE:
            self.iconic.discard(_hwnd(hwnd))
        return 1

    def SetForegroundWindow(self, hwnd):
        if self.deny_fg:
            return 0
        self.fg = _hwnd(self.fg_becomes or hwnd)
        return 1

    def GetForegroundWindow(self):
        if self.fg_delay > 0:                                # 切前台是异步的：还没换完
            self.fg_delay -= 1
            return self.fg_old
        return self.fg

    def SetWindowPos(self, *a, **k):
        return 1


def _fake_world(wins, areas=None):
    w = _FakeWin(wins, areas)
    w32.user32, w32.kernel32 = w, _FakeKernel(w)
    return w


_real_dlls = (w32.user32, w32.kernel32, w32.list_windows)
try:
    w32.list_windows = _REAL_LIST_WINDOWS                     # [B] 换过它，这里要真函数
    BIG = 1920 * 1080
    world = _fake_world({11: ("chrome - 记事本", "notepad.exe", 101),
                         77: ("SCP: Secret Laboratory", "scpsl.exe", 202)},
                        {11: (800, 600), 77: (BIG, BIG)})
    ctx = ops.OpContext(hwnd=0, logger=lambda m: None)        # 没有任何缓存 → 必须现查
    check("K19 端到端：现查到游戏窗口并真最小化",
          (ops.run_item({"type": "minimize_game", "params": {}}, ctx), sorted(world.iconic)),
          ((True, "已把游戏最小化"), [77]))

    # 游戏重启：旧句柄 77 已不存在，新窗口是 88
    world = _fake_world({11: ("chrome - 记事本", "notepad.exe", 101),
                         88: ("SCP: Secret Laboratory", "scpsl.exe", 303)},
                        {11: (800, 600), 88: (BIG, BIG)})
    ctx = ops.OpContext(hwnd=77, logger=lambda m: None)       # 缓存还是重启前的旧句柄
    check("K20 端到端·游戏重启：旧句柄失效 → 打到新句柄 88",
          (ops.run_item({"type": "minimize_game", "params": {}}, ctx), sorted(world.iconic)),
          ((True, "已把游戏最小化（窗口换了，已重找）"), [88]))

    # 句柄被系统回收给了别的程序（77 现在是 notepad）
    world = _fake_world({11: ("chrome - 记事本", "notepad.exe", 101),
                         77: ("另一个记事本", "notepad.exe", 404),
                         88: ("SCP: Secret Laboratory", "scpsl.exe", 303)},
                        {11: (800, 600), 77: (300, 300), 88: (BIG, BIG)})
    ctx = ops.OpContext(hwnd=77, logger=lambda m: None)
    check("K21 端到端·句柄被回收：只动真游戏窗口，绝不碰别人的 77",
          (ops.run_item({"type": "minimize_game", "params": {}}, ctx), sorted(world.iconic)),
          ((True, "已把游戏最小化（窗口换了，已重找）"), [88]))

    world = _fake_world({11: ("chrome - 记事本", "notepad.exe", 101)})
    ctx = ops.OpContext(hwnd=0, logger=lambda m: None)
    check("K22 端到端·游戏没开：老实报失败，一个窗口都不动",
          (ops.run_item({"type": "minimize_game", "params": {}}, ctx), sorted(world.iconic)),
          ((False, "没找到游戏窗口（游戏没开？）"), []))
    check("K23 端到端：死句柄直接判 False（复核生效）", w32.minimize_window(77), False)

    world = _fake_world({88: ("SCP: Secret Laboratory", "scpsl.exe", 303)}, {88: (BIG, BIG)})
    world.iconic.add(88)
    check("K24 端到端·切前台：还原 + 真到前台才算成功",
          (w32.focus_window(88), sorted(world.iconic), world.fg), (True, [], 88))
    world.deny_fg = True
    world.fg = 11                                             # 前台被别的程序占着
    ok("K25 端到端·系统不给你前台 → 报失败（不谎报成功）",
       w32.focus_window(88) is False)
    # 用户实测踩到的两类误报：异步 + 到前台的不是我们操作的那个句柄
    world = _fake_world({88: ("SCP: Secret Laboratory", "scpsl.exe", 303),
                         89: ("SCP: Secret Laboratory", "scpsl.exe", 303)},
                        {88: (BIG, BIG), 89: (400, 300)})
    world.fg_becomes = 89                                     # 系统把同进程的另一个窗口推到前台
    ok("K26 端到端·前台是同进程的另一个窗口 → 算成功（不误报）",
       w32.focus_window(88) is True)

    world = _fake_world({88: ("SCP: Secret Laboratory", "scpsl.exe", 303)}, {88: (BIG, BIG)})
    world.fg_old, world.fg_delay = 11, 2                      # 头两次查到的还是旧前台
    ok("K27 端到端·切前台是异步的 → 等它一下再判（不误报）",
       w32.focus_window(88) is True)

    world = _fake_world({88: ("SCP: Secret Laboratory", "scpsl.exe", 303)}, {88: (BIG, BIG)})
    world.iconic_delay = 2                                    # 头两次查还没最小化完
    ok("K28 端到端·最小化延迟生效 → 仍算成功（不误报）",
       w32.minimize_window(88) is True)
finally:
    w32.user32, w32.kernel32, w32.list_windows = _real_dlls

ok("K29 非 Windows 上 pid_of / foreground_is 安全退化",
   w32.pid_of(1234) == 0 and w32.foreground_is(1234) is False)

# ============================================================ 结果
shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 64)
print("PASS %d / FAIL %d" % (len(PASS), len(FAILS)))
if FAILS:
    print("❌ 失败：%s" % FAILS)
    sys.exit(1)
print("✅ 全部通过")
