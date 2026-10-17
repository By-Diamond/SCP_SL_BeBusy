# -*- coding: utf-8 -*-
"""验证：操作的注册 / 执行 / 界面 / 配置往返（含 8 个后加的操作）。

跑法（源码目录下）：`python tests/verify_ops.py`
纯 Python + 桩，不需要装 PySide6 / pycaw —— 所以 Linux 上也能跑。
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

check("A1 操作总数 13", len(ops.all_specs()), 13)
check("A2 新增五条在最后", [s.type for s in ops.all_specs()][-5:],
      ["set_volume", "speak", "toast", "delay", "send_keys"])

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

_missing = []
for _spec in ops.all_specs():                                  # 每个操作的每个参数都得有控件
    _dlg = od.ParamsDialog(_spec, {})
    for _k, _l, _d, _h in _spec.params:
        if _k not in _dlg.getters:
            _missing.append("%s.%s" % (_spec.type, _k))
check("A6 每个操作的每个参数都有对应控件（一个窗口填完）", _missing, [])
ok("A6b 参数窗口能一口气收集出所有参数的值",
   sorted(od.ParamsDialog(ops.get_spec("speak"), {"text": "a", "file": "b"}).collect()) ==
   ["file", "file_volume", "text", "tts_volume"],
   str(od.ParamsDialog(ops.get_spec("speak"), {}).collect()))

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
                               QComboBox, QListWidgetItem)
from ui.page_features import OpBox                              # noqa: E402
from ui import op_dialog                                        # noqa: E402

qtstub.reset_all()
core = FakeCore(os.path.join(TMP, "settings.json"))
box = OpBox(core, "death", "死亡后")

dlg = op_dialog.AddOpDialog(box.op_list, None)
check("D1 添弹窗列出全部 13 个操作", dlg.list.count(), 13)
row_focus = None
for i in range(dlg.list.count()):
    if dlg.list.item(i).data(Qt.ItemDataRole.UserRole) == "focus_window":
        row_focus = dlg.list.item(i)
ok("D2 「切换到界面」可重复 → 有了一条也不置灰",
   bool(row_focus.flags() & Qt.ItemFlag.ItemIsEnabled), str(row_focus.flags()))
ok("D2b 灰项仍只给已存在且不允许重复的（媒体播放）",
   not (dlg.list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled))

# 参数窗口：一个操作 = 一个窗口（测试里把弹窗换成"直接给值"）
_called = []


def _fake_params(parent, spec, values=None, title="", which=""):
    _called.append((spec.type, dict(values or {})))
    return {"target": "chrome.exe"}, True


_real_params = op_dialog.ask_params
op_dialog.ask_params = _fake_params
try:
    QMessageBox.reset()
    ok_add = box._add_type("focus_window")
    ok("D3 添加「切换到界面」成功（参数窗口一次填完）", ok_add is True, str(core.logs[-1:]))
    check("D3b 窗口打开时带着预填/默认值（原值）", _called[-1],
          ("focus_window", {"target": ""}))
    check("D5 参数写进列表", box.op_list.items[-1],
          {"type": "focus_window", "params": {"target": "chrome.exe"}})
    check("D6 立即写进配置", core.cfg.ops("death")[-1]["params"]["target"], "chrome.exe")
    check("D7 列表文字带参数", box.list.item(box.list.count() - 1).text(), "切换到界面 — chrome.exe")
    check("D7b 底部提示仍是「共 N 条」", box.hint.text(), "共 2 条")

    # 取消窗口
    op_dialog.ask_params = lambda parent, spec, values=None, title="", which="": ({}, False)
    ok("D8 取消参数窗口 → 不加", box._add_type("focus_window") is False)
    check("D9 取消后列表没变", len(box.op_list), 2)

    # 必填留空：窗口里就地拦住（不关窗），改完还能继续确定
    _dlg = op_dialog.ParamsDialog(ops.get_spec("focus_window"), {"target": "   "}, None,
                                 title="添加操作")
    ok("D10 必填留空 → 点确定也不通过（就地提示）", _dlg.on_ok() is False)
    ok("D10b 提示写明哪个不能为空", "窗口」不能为空" in _dlg.err.text(), _dlg.err.text())
    check("D10c 窗口没被关掉（能接着改）", _dlg.result, None)
    check("D10d 空值没进列表", len(box.op_list), 2)
    _dlg.fields["target"].setEditText("chrome.exe")
    ok("D10e 改完再点确定 → 通过", _dlg.on_ok() is True)
    check("D10f 收集到的就是窗口里填的", _dlg.values(), {"target": "chrome.exe"})

    # 编辑
    box.list.setCurrentRow(1)
    op_dialog.ask_params = lambda parent, spec, values=None, title="", which="": (
        {"target": "discord.exe"}, True)
    box.edit()
    check("D12 编辑改了参数并落盘",
          (box.op_list.items[1]["params"]["target"], core.cfg.ops("death")[1]["params"]["target"]),
          ("discord.exe", "discord.exe"))
finally:
    op_dialog.ask_params = _real_params

# 窗口下拉（值 = 进程名，悬停看标题）
_wins = [
    (1, "SCP:SL BeBusy v0.2.0 — 存活", "python.exe"),         # 本程序自己 → 应被跳过
    (2, "新标签页 - Google Chrome", "chrome.exe"),
    (3, "report.txt - 记事本", "notepad.exe"),
    (3, "report2.txt - 记事本", "notepad.exe"),               # 同进程再来一个 → 去重
    (4, "", "ghost.exe"),                                     # 没标题 → 跳过
]
_real_lw = w32.list_windows
w32.list_windows = lambda: list(_wins)
try:
    _cb = QComboBox()
    op_dialog.fill_windows(_cb)
    check("D13 只列出别的程序的窗口（跳过自己 + 空标题 + 同进程去重）", _cb.count(), 2)
    check("D14 下拉里放的是进程名", [_cb.itemText(i) for i in range(_cb.count())],
          ["chrome.exe", "notepad.exe"])
    check("D15 悬停能看到窗口标题", _cb.itemData(0, op_dialog.TOOLTIP_ROLE),
          "新标签页 - Google Chrome")
    _cb.setEditText("chrome.exe")
    check("D16 选中的值就是进程名", _cb.currentText(), "chrome.exe")
    _cb.setEditText("记事本")
    check("D17 手打标题也认（可编辑）", _cb.currentText(), "记事本")
    w32.list_windows = lambda: []
    _cb2 = QComboBox()
    op_dialog.fill_windows(_cb2)
    ok("D19 一个窗口都没有时给出提示（不空白）",
       _cb2.count() == 0 and "没找到" in getattr(_cb2, "tooltip", ""),
       getattr(_cb2, "tooltip", ""))
finally:
    w32.list_windows = _real_lw

# 文件选择：窗口里的「浏览…」按钮
QFileDialog.reset()
QFileDialog.result = ("C:/Tools/run.bat", "所有文件 (*.*)")
_dlgf = op_dialog.ParamsDialog(ops.get_spec("run_file"), {"path": ""}, None, title="添加操作")
_dlgf.buttons["browse:path"].click()
check("D20 「浏览…」选中的文件填进框里", _dlgf.collect()["path"], "C:/Tools/run.bat")
QFileDialog.reset()
_dlgf.buttons["browse:path"].click()
check("D21 取消浏览 → 框里保持原样（不擦掉）", _dlgf.collect()["path"], "C:/Tools/run.bat")

check("D22 三个窗口 / 文件操作在添弹窗里都能被选中",
      [(dlg.list.item(i).data(Qt.ItemDataRole.UserRole),
        bool(dlg.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled))
       for i in range(dlg.list.count())][5:8],
      [("focus_window", True), ("minimize_window", True), ("run_file", True)])

_new_rows = {dlg.list.item(i).data(Qt.ItemDataRole.UserRole):
             bool(dlg.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled)
             for i in range(dlg.list.count())}
check("D22b 五个新操作都是「可重复」→ 不被置灰",
      [_new_rows[t] for t in ("set_volume", "speak", "toast", "delay", "send_keys")],
      [True] * 5)
check("D22c 新操作的显示名",
      [ops.get_spec(t).name for t in ("set_volume", "speak", "toast", "delay", "send_keys")],
      ["调节程序音量", "语音播报", "发送通知", "延迟执行", "模拟按键"])

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
check("G2 版本 0.2.0／作者与介绍没变",
      (cfgmod.VERSION, cfgmod.AUTHOR, cfgmod.DESCRIPTION),
      ("0.2.0", "By Diamond",
       "自动识别玩家存活/死亡 并执行相关操作，未修改游戏本体，不是作弊行为"))
_vinfo = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "tools", "version_info.txt"), encoding="utf-8").read()
ok("G2b exe 元数据的版本号跟源码一致（都是 0.2.0）",
   "u'0.2.0'" in _vinfo and "(0, 2, 0, 0)" in _vinfo and "0.1.0" not in _vinfo
   and cfgmod.VERSION == "0.2.0", _vinfo.strip().splitlines()[:3])
ok("G2c exe 元数据的作者/介绍没被顺手改掉",
   "u'By Diamond'" in _vinfo and "不是作弊行为" in _vinfo, "")
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

# ============================================================ [L] 新操作（注册 / 参数 / 弹窗）
p("[L] 新操作：注册表 / 参数 / 校验 / 一个窗口填完")

from PySide6.QtWidgets import QDialog, QInputDialog              # noqa: E402

check("L1 新增 5 个操作（总数 13）", len(ops.all_specs()), 13)
for _t, _name, _params in (("set_volume", "调节程序音量", ["proc", "level", "fade_ms"]),
                           ("speak", "语音播报", ["text", "file", "file_volume", "tts_volume"]),
                           ("toast", "发送通知", ["title", "body"]),
                           ("delay", "延迟执行", ["ms"]),
                           ("send_keys", "模拟按键", ["keys"])):
    _s = ops.get_spec(_t)
    check("L2 %s：名字 / 参数 / 可重复" % _name,
          (_s.name, [x[0] for x in _s.params], _s.allow_multiple), (_name, _params, True))
check("L3 五个新操作都带参数级校验",
      [bool(ops.get_spec(t).validate)
       for t in ("set_volume", "speak", "toast", "delay", "send_keys")], [True] * 5)
check("L4 语音播报的文本 / 文件都能留空（可选参数）", ops.get_spec("speak").optional,
      ("text", "file"))
check("L5 音量 / 渐变 / 延迟参数都出的是数字框（填不出范围外）",
      [type(op_dialog.ParamsDialog(ops.get_spec(t), {}).fields[k]).__name__ for t, k in
       (("set_volume", "level"), ("set_volume", "fade_ms"), ("delay", "ms"),
        ("speak", "file_volume"), ("speak", "tts_volume"))],
      ["QSpinBox"] * 5)
check("L5b 网址/文本/标题内容是单行框；提示音带「浏览…」；按键是**只读**框",
      (type(op_dialog.ParamsDialog(ops.get_spec("open_url"), {}).fields["url"]).__name__,
       sorted(op_dialog.ParamsDialog(ops.get_spec("speak"), {}).buttons),
       type(op_dialog.ParamsDialog(ops.get_spec("send_keys"), {}).fields["keys"]).__name__,
       op_dialog.ParamsDialog(ops.get_spec("send_keys"), {}).fields["keys"].isReadOnly()),
      ("QLineEdit", ["browse:file"], "KeyEdit", True))
check("L5c 窗口 / 进程名是「可编辑下拉 + 刷新」",
      sorted(op_dialog.ParamsDialog(ops.get_spec("focus_window"), {}).buttons) +
      sorted(op_dialog.ParamsDialog(ops.get_spec("set_volume"), {}).buttons),
      ["reload:target", "reload:proc"])
check("L6 音量 150 在「添加」时就被拦住",
      ops.validate_item({"type": "set_volume",
                         "params": {"proc": "SCPSL.exe", "level": "150", "fade_ms": "0"}})[0],
      False)
check("L7 延迟 20000ms 被拦", ops.validate_item({"type": "delay", "params": {"ms": "20000"}})[0],
      False)
check("L8 乱写的按键被拦", ops.validate_item({"type": "send_keys", "params": {"keys": "Ctrl+香蕉"}})[0],
      False)
check("L9 空播报（文本和文件都空）被拦",
      ops.validate_item({"type": "speak", "params": {"text": "", "file": "",
                                                     "file_volume": "100",
                                                     "tts_volume": "100"}}),
      (False, "「播报文本」和「提示音文件」至少填一个"))
check("L10 只选提示音文件也合法（文本留空）",
      ops.validate_item({"type": "speak", "params": {"text": "", "file": "C:/a.mp3",
                                                    "file_volume": "80",
                                                    "tts_volume": "60"}}),
      (True, ""))
check("L10b 语音音量越界也拦得住（两个音量分开校验）",
      ops.validate_item({"type": "speak", "params": {"text": "x", "file": "",
                                                     "file_volume": "100",
                                                     "tts_volume": "150"}})[0],
      False)
check("L11 标题和内容都空 → 拦",
      ops.validate_item({"type": "toast", "params": {"title": "", "body": ""}})[0],
      False)
check("L12 列表里显示参数", ops.describe_item({"type": "delay", "params": {"ms": "1500"}}),
      "延迟执行 — 1500")
check("L13 按框预填：死了静音 / 活了恢复",
      [ops.prefill_for("set_volume", "level", w) for w in ("death", "alive")], ["0", "100"])
check("L14 按框预填：播报文本 / 通知内容",
      [[ops.prefill_for(t, k, w) for w in ("death", "alive")]
       for t, k in (("speak", "text"), ("toast", "body"))],
      [["你已死亡", "你已复活"], ["检测到你已死亡", "检测到你已复活"]])
check("L15 没有预填规则的操作给空串", ops.prefill_for("delay", "ms", "death"), "")

# 数字框：范围外的值填不进去（夹住）
_dn = op_dialog.ParamsDialog(ops.get_spec("set_volume"),
                             {"proc": "a.exe", "level": "999", "fade_ms": "9999"})
check("L16 目标音量夹在 0-100", _dn.fields["level"].value(), 100)
check("L17 渐变时长夹在 0-3000", _dn.fields["fade_ms"].value(), 3000)
check("L17b 渐变框带毫秒后缀（看得懂填的是毫秒）", _dn.fields["fade_ms"].suffix, " 毫秒")
_dm = op_dialog.ParamsDialog(ops.get_spec("delay"), {"ms": "99999"})
check("L18 延迟夹在 0-10000", _dm.fields["ms"].value(), 10000)
QDialog.exec_queue = [QDialog.DialogCode.Rejected]
check("L19 取消参数窗口 → 未作答",
      op_dialog.ask_params(None, ops.get_spec("delay"), {}, "添加操作"), ({}, False))
QDialog.exec_queue = []
_dt = op_dialog.ParamsDialog(ops.get_spec("toast"), {"title": "T", "body": "B"}, None,
                            title="添加操作")
check("L20 通知窗口只有标题和内容两个框（「返回游戏」按钮已删掉）",
      sorted(_dt.fields), ["body", "title"])

QFileDialog.reset()
QFileDialog.result = ("C:/a.mp3", "音频文件 (*.wav *.mp3 …)")
_da = op_dialog.ParamsDialog(ops.get_spec("speak"), {"text": "x", "file": ""}, None,
                             title="添加操作")
_da.buttons["browse:file"].click()
check("L21 提示音可以留空、也可以「浏览…」选一个", _da.collect()["file"], "C:/a.mp3")
check("L21b 不留提示音也合法（可选）",
      ops.validate_item({"type": "speak", "params": {"text": "x", "file": "",
                                                     "file_volume": "100",
                                                     "tts_volume": "100"}})[0],
      True)
QFileDialog.reset()
_da.buttons["browse:file"].click()
check("L22 取消浏览 → 框里保持原样", _da.collect()["file"], "C:/a.mp3")
check("L23 两个音量各自独立地收上来",
      op_dialog.ParamsDialog(ops.get_spec("speak"),
                             {"text": "x", "file_volume": "30", "tts_volume": "70"}).collect(),
      {"text": "x", "file": "", "file_volume": "30", "tts_volume": "70"})
check("L24 老配置（只有一个 volume）自动迁移到两个音量",
      ops.normalize_item({"type": "speak",
                          "params": {"text": "x", "file": "", "volume": "55"}})["params"],
      {"text": "x", "file": "", "file_volume": "55", "tts_volume": "55"})

# ============================================================ [M] 延迟执行
p("[M] 延迟执行：0-10000ms；新的状态变化会把它打断")

check("M1 越界（10001）被拦", ops.parse_delay_ms("10001")[0], False)
check("M2 负数被拦", ops.parse_delay_ms("-100")[0], False)
check("M3 非数字被拦", ops.parse_delay_ms("一秒")[0], False)
check("M4 下界 0 合法", ops.parse_delay_ms("0"), (True, 0))
check("M5 上界 10000 合法", ops.parse_delay_ms("10000"), (True, 10000))
ok("M6 报错文案里写了合法范围", "0-10000" in ops.parse_delay_ms("99999")[1],
   ops.parse_delay_ms("99999")[1])


class NoWaitCtx(ops.OpContext):
    """把 sleep 换成记账（不真等）；可以在第 N 片之后模拟"新的状态变化"。"""

    def __init__(self, cancel_after=None):
        ops.OpContext.__init__(self, logger=lambda m: None, cancel=self._flag)
        self.slept = []
        self.n = 0
        self.cancel_after = cancel_after
        self.flag = False
        self.sleep = self._sleep

    def _flag(self):
        return self.flag

    def _sleep(self, s):
        self.n += 1
        self.slept.append(s)
        if self.cancel_after is not None and self.n >= self.cancel_after:
            self.flag = True


_c = NoWaitCtx()
check("M7 延迟 1500ms：不真等，走完就算成功",
      ops.run_item({"type": "delay", "params": {"ms": "1500"}}, _c), (True, "已延迟 1500ms"))
check("M8 总时长正好 1.5s", round(sum(_c.slept), 6), 1.5)
check("M9 每片不超过 50ms（能及时被打断）", max(_c.slept) <= 0.0500001, True)

_c = NoWaitCtx()
check("M10 0ms = 不睡也不延迟",
      (ops.run_item({"type": "delay", "params": {"ms": "0"}}, _c), _c.n),
      ((True, "延迟 0ms（等于不延迟）"), 0))

_c = NoWaitCtx(cancel_after=5)
_res = ops.run_item({"type": "delay", "params": {"ms": "3000"}}, _c)
check("M11 中途被打断 → 老实报被打断（不算成功）", _res[0], False)
ok("M12 说明里带了进度", _res[1].startswith("延迟被打断（已等"), _res[1])
check("M13 没睡满就退出（只睡了 5 片）", _c.n, 5)
check("M14 执行时参数非法也拦得住（不崩）",
      ops.run_item({"type": "delay", "params": {"ms": "一小时"}}, NoWaitCtx())[0], False)

# ============================================================ [N] 列表被打断
p("[N] 列表打断：新状态变化一来 → 剩下的操作一条都不跑")

_open_calls = []
_items3 = [{"type": "open_url", "params": {"url": "https://a"}},
           {"type": "open_url", "params": {"url": "https://b"}},
           {"type": "open_url", "params": {"url": "https://c"}}]


def _url_ctx(log_list, cancel_fn):
    cx = ops.OpContext(logger=log_list.append, cancel=cancel_fn)

    def _open(u):
        _open_calls.append(u)
        return True, "已打开 %s" % u

    cx.open_url = _open
    return cx


_lines = []
st = ops.run_list(_items3, _url_ctx(_lines, lambda: False), label="[死亡后]")
check("N1 没人打断 → 三条都跑", (st["ok"], st["fail"], st["total"], st["aborted"]),
      (3, 0, 3, 0))
check("N2 收尾说「执行完毕」", any("执行完毕" in l for l in _lines), True)

_hit = {"n": 0}
_lines2 = []


def _open_once(u):
    _hit["n"] += 1
    _open_calls.append(u)
    return True, "已打开 %s" % u


_cx2 = ops.OpContext(logger=_lines2.append, cancel=lambda: _hit["n"] >= 1)
_cx2.open_url = _open_once
st2 = ops.run_list(_items3, _cx2, label="[死亡后]")
check("N3 第 1 条跑完就发现被打断 → 只跑了 1 条", (_hit["n"], st2["ok"]), (1, 1))
check("N4 剩下 2 条标成「没执行」", st2["aborted"], 2)
ok("N5 日志明说第 2 条起不再执行", any("第 2 条起" in l for l in _lines2), str(_lines2[-2:]))
ok("N6 收尾日志写了「被中断」", any("被中断" in l for l in _lines2), str(_lines2[-1:]))
check("N7 没跑的绝不算成功（账要对得上）",
      st2["ok"] + st2["fail"] + st2["skip"] + st2["aborted"], st2["total"])

# ============================================================ [O] 语音播报
p("[O] 语音播报：一条队列（死亡 / 复活不重合）；打断立刻停 + 清空排队")

import speech_actions as spk                                     # noqa: E402
import time as _time                                             # noqa: E402

_pdir = os.path.join(TMP, "audio")
os.makedirs(_pdir, exist_ok=True)
A_WAV = os.path.join(_pdir, "a.wav")
B_WAV = os.path.join(_pdir, "b.wav")
C_WAV = os.path.join(_pdir, "c.wav")
NEW_WAV = os.path.join(_pdir, "new.wav")
for _p in (A_WAV, B_WAV, C_WAV, NEW_WAV):
    with open(_p, "wb") as _f:
        _f.write(b"RIFF0000WAVE")

_played = []
_live = {"n": 0, "max": 0}
_lock = threading.Lock()


def _fake_player(path, volume=100, cancel=None, logger=None):
    """假装"要放一会儿"（每条 100ms），期间查打断 —— 和真实现同一个契约。"""
    with _lock:
        _live["n"] += 1
        _live["max"] = max(_live["max"], _live["n"])
    name = os.path.basename(path)
    _played.append(("play", name, volume))
    try:
        for _i in range(50):
            if spk._cancelled(cancel):
                _played.append(("cut", name))
                return False, "播放被打断：%s" % name
            _time.sleep(0.002)
        _played.append(("done", name))
        return True, "已播放 %s" % name
    finally:
        with _lock:
            _live["n"] -= 1


def _fake_speaker(text, volume=100, cancel=None, logger=None):
    """假装朗读要一会儿（每条 100ms），期间查打断 —— 和真实现同一个契约。"""
    with _lock:
        _live["n"] += 1
        _live["max"] = max(_live["max"], _live["n"])
    _played.append(("say", text, volume))
    try:
        for _i in range(50):
            if spk._cancelled(cancel):
                _played.append(("say-cut", text))
                return False, "朗读被打断：%s" % text
            _time.sleep(0.002)
        _played.append(("say-done", text))
        return True, "已朗读：%s（音量 %d）" % (text, volume)
    finally:
        with _lock:
            _live["n"] -= 1


def _new_backend(**kw):
    kw.setdefault("logger", lambda m: None)
    kw.setdefault("player", _fake_player)
    kw.setdefault("speaker", _fake_speaker)
    return spk.SpeechBackend(**kw)


_b1 = _new_backend()
try:
    check("O1 入队成功（说的是「排进队列」，不是「已经播完」）",
          _b1.say("你已死亡", "", 100, 80), (True, "已排进播报队列（文本）"))
    _msg2 = _b1.say("你已复活", "", 100, 100)[1]
    ok("O2 第二条排在后面（不死磕、不叠音）",
       _msg2.startswith("已排进播报队列（文本"), _msg2)
    check("O3 队列跑完（等得到）", _b1.wait_idle(5), True)
    check("O4 文本走「朗读」这条路（两条都走了）",
          [p[1] for p in _played if p[0] == "say-done"], ["你已死亡", "你已复活"])
    check("O5 不再需要临时 wav（朗读直接出声音）", hasattr(spk, "TTS_TEMP_NAME"), False)
    check("O6 语音音量原样交给朗读（提示音音量管不着它）",
          [p[2] for p in _played if p[0] == "say"], [80, 100])
finally:
    _b1.stop()

_played.clear()
_b6 = _new_backend()
try:
    _b6.say("你已死亡", A_WAV, 90, 70)
    check("O6b 一条播报跑完", _b6.wait_idle(5), True)
    check("O6c 固定顺序：先放提示音、再朗读",
          [p[0] for p in _played], ["play", "done", "say", "say-done"])
    check("O6d 提示音用「提示音音量」、朗读用「语音音量」（各管各的）",
          (_played[0][2], _played[2][2]), (90, 70))
finally:
    _b6.stop()

_played.clear()
_b2 = _new_backend()
try:
    _b2.say("", A_WAV, 100, 100)
    _b2.say("", B_WAV, 100, 100)
    _b2.say("", C_WAV, 100, 100)
    check("O7 三条都播完", _b2.wait_idle(5), True)
    check("O8 先来先播（顺序不乱）",
          [p[1] for p in _played if p[0] == "done"], ["a.wav", "b.wav", "c.wav"])
    check("O9 任何时刻都只有一条在响（用户要的「不重合」）", _live["max"], 1)
finally:
    _b2.stop()

_played.clear()
_b3 = _new_backend()
try:
    _b3.say("", A_WAV, 100, 100)
    _b3.say("", B_WAV, 100, 100)
    _b3.say("", C_WAV, 100, 100)
    _deadline = _time.time() + 3
    while not any(p[0] == "play" for p in _played) and _time.time() < _deadline:
        _time.sleep(0.005)
    _dropped = _b3.purge("新的状态变化")
    _cut_deadline = _time.time() + 2
    while not any(p[0] == "cut" for p in _played) and _time.time() < _cut_deadline:
        _time.sleep(0.005)
    check("O10 打断：丢掉还没轮到播的 2 条", _dropped, 2)
    check("O11 正在播的那条被切掉", [p[0] for p in _played].count("cut"), 1)
    check("O12 收手后队列是空的", _b3.pending(), 0)
    check("O13 被切掉的没被算成播完（不谎报）", [p for p in _played if p[0] == "done"], [])
finally:
    _b3.stop()

_b4 = _new_backend()
check("O14 文本和文件都空 → 不入队",
      _b4.say("", "", 100, 100), (False, "既没填播报文本，也没选提示音文件"))
check("O15 语音音量越界 → 不入队", _b4.say("x", "", 100, 150)[0], False)
check("O15b 提示音音量越界 → 不入队", _b4.say("", A_WAV, 150, 100)[0], False)
check("O15c 用不上的那个音量不管（只播文本时提示音音量写错也不拦）",
      _b4.say("x", "", 150, 100)[0], True)
check("O16 文件不存在 → 不入队",
      _b4.say("", os.path.join(_pdir, "nope.mp3"), 100, 100),
      (False, "提示音文件不存在：%s" % os.path.join(_pdir, "nope.mp3")))
_b4.stop()

check("O17 非 Windows 上放音老实报失败（不谎报）", spk.play_file(A_WAV, 100, None)[0], False)
_cmd, _env = spk._play_cmd(A_WAV, 50)
ok("O17b 播放交给系统播放器，音量按 0-1 换算过去",
   (os.path.basename(_cmd[0]).lower().startswith(("powershell", "pwsh")),
    _env["OPB_VOL"]), (True, "0.5000"))
ok("O17c 播放脚本用系统播放器（所以不看扩展名、看内容）",
   "MediaPlayer" in spk.PLAY_PS and "$env:OPB_VOL" in spk.PLAY_PS, spk.PLAY_PS[:40])
check("O18 非 Windows 上朗读老实报失败", spk.speak_text("你好", 100, None)[0], False)
check("O18b 朗读文本为空 → 老实报失败", spk.speak_text("  ", 100, None),
      (False, "没有要播报的文字"))

_said = []


class _SayBackend(object):
    def say(self, text, file="", file_volume=100, tts_volume=100):
        _said.append((text, file, file_volume, tts_volume))
        return True, "已排进播报队列"


_cxs = ops.OpContext(logger=lambda m: None, speech=_SayBackend())
check("O19 播报操作：文本 + 两个音量原样交给队列",
      (ops.run_item({"type": "speak",
                     "params": {"text": "你已死亡", "file": "C:/a.mp3",
                                "file_volume": "80", "tts_volume": "60"}}, _cxs),
       _said),
      ((True, "已排进播报队列"), [("你已死亡", "C:/a.mp3", "80", "60")]))
_cxs2 = ops.OpContext(logger=lambda m: None, speech=None)
check("O20 没接队列时老实报错（不崩）",
      ops.run_item({"type": "speak",
                    "params": {"text": "x", "file": "", "file_volume": "100",
                               "tts_volume": "50"}}, _cxs2),
      (False, "语音后端未就绪"))

# ============================================================ [P] 模拟按键
p("[P] 模拟按键：写法解析 / 组合键 / 收不下就报失败")

import key_input as ki                                           # noqa: E402

check("P1 Ctrl+D", ki.parse("Ctrl+D"), (True, {"mods": ["Ctrl"], "key": "D", "vk": 0x44}))
check("P2 小写随便写", ki.parse("ctrl+d"), ki.parse("Ctrl+D"))
check("P3 F12", ki.parse("F12"), (True, {"mods": [], "key": "F12", "vk": 0x7B}))
check("P4 Insert", ki.parse("Insert")[1]["vk"], 0x2D)
check("P5 Shift+Alt+→", ki.parse("Shift+Alt+→"),
      (True, {"mods": ["Shift", "Alt"], "key": "→", "vk": 0x27}))
check("P6 修饰键顺序无所谓 + 规范化", ki.describe("shift+ctrl+d"), "Ctrl+Shift+D")
check("P7 箭头：英文和符号等价", ki.describe("shift+alt+right"), ki.describe("Shift+Alt+→"))
check("P8 下方向键", ki.describe("Shift+Alt+↓"), "Shift+Alt+↓")
check("P9 空格键", ki.describe("Ctrl+Space"), "Ctrl+Space")
check("P10 数字键", ki.describe("1"), "1")
check("P11 空 → 拦", ki.parse("")[0], False)
check("P12 乱写 → 拦", ki.parse("Ctrl+香蕉")[0], False)
check("P13 只写了修饰键 → 拦（还没按主键）", ki.parse("Ctrl+Shift")[0], False)
check("P14 加号键本身（Ctrl++）", ki.parse("Ctrl++")[1]["vk"], 0xBB)
check("P14b 加号键写法能原样来回（Ctrl++）",
      (ki.describe("Ctrl++"), ki.parse("Ctrl++")[1]["key"]), ("Ctrl++", "+"))

_real_available = ki.available
_real_send = ki._send
try:
    ki.available = lambda: True                       # 假装在 Windows 上
    _captured = []
    ki._send = lambda events: (_captured.append(list(events)), len(events))[1]
    check("P15 全收下 → 才算成功（说明只讲「我们按下去了」）",
          ki.press("Ctrl+Shift+D"), (True, "已按下 Ctrl+Shift+D（发给当时最前面的窗口）"))
    check("P16 事件顺序：修饰键按下 → 主键按下 → 主键松开 → 修饰键松开",
          _captured[0],
          [(0x11, 0), (0x10, 0), (0x44, 0), (0x44, ki.KEYEVENTF_KEYUP),
           (0x10, ki.KEYEVENTF_KEYUP), (0x11, ki.KEYEVENTF_KEYUP)])
    _captured.clear()
    check("P16b 单独按 Win：就是 Win 按下 + 松开（不夹带别的键）",
          (ki.press("Win"), _captured[0]),
          ((True, "已按下 Win（发给当时最前面的窗口）"),
           [(0x5B, 0), (0x5B, ki.KEYEVENTF_KEYUP)]))
    _captured.clear()
    check("P16c 单独按 Ctrl：同样只是 Ctrl 按下 + 松开",
          (ki.press("Ctrl"), _captured[0][-1]),
          ((True, "已按下 Ctrl（发给当时最前面的窗口）"), (0x11, ki.KEYEVENTF_KEYUP)))
    ki._send = lambda events: len(events) - 1
    _pf = ki.press("F12")
    check("P17 少收下一条 → 报失败（不谎报）", _pf[0], False)
    ok("P18 失败说明里写了实际收下的条数", "1/2" in _pf[1], _pf[1])
    ki._send = lambda events: 0
    check("P19 一条都没收下 → 报失败", ki.press("Insert")[0], False)
finally:
    ki.available = _real_available
    ki._send = _real_send
check("P20 非 Windows 上按下去老实报失败",
      ki.press("Ctrl+D", logger=lambda m: None), (False, "非 Windows 环境，按键没发出去"))

check("P21 Qt 按键 → 写法：Ctrl+Shift+D",
      op_dialog.describe_keypress(0x44, "d", op_dialog.MOD_CTRL | op_dialog.MOD_SHIFT),
      "Ctrl+Shift+D")
check("P22 方向键用箭头符号", op_dialog.describe_keypress(0x01000014, "", 0), "→")
check("P23 F5", op_dialog.describe_keypress(0x01000034, "", 0), "F5")
check("P24 Esc 本身能识别", op_dialog.describe_keypress(0x01000000, "", 0), "Esc")
check("P25 只按了修饰键 → 空串（继续等主键）",
      op_dialog.describe_keypress(0x01000021, "", op_dialog.MOD_CTRL), "")
_kd = op_dialog.KeyEdit("")
check("P26 只读框里按一下就记下来",
      (_kd._press(0x44, "d", op_dialog.MOD_CTRL), _kd.chosen()), ("Ctrl+D", "Ctrl+D"))
check("P27 打开时把原写法规范化（大小写 / 顺序都统一）",
      op_dialog.KeyEdit("ctrl+f12").chosen(), "Ctrl+F12")
check("P30 方向键能录（不会被拿去移动焦点）",
      op_dialog.KeyEdit("")._press(0x01000014, "", 0), "→")
_kd2 = op_dialog.KeyEdit("")
check("P31 回车能录（不再等于「点了确定」）", _kd2._press(0x01000004, "\r", 0), "Enter")
check("P32 Esc = 清空框里内容（不是关窗口）",
      (_kd2._press(op_dialog.KEY_ESC, "", 0), _kd2.chosen()), ("", ""))
# 用户报的：Ctrl/Shift/Alt/锁键/小键盘都录不进（真实 GUI 里每次按键都抛
# TypeError: int() ... not 'KeyboardModifier'）。这里连同「按下就记」的新写法一起测。
_kd3 = op_dialog.KeyEdit("")
check("P33 单独按一下 Ctrl → 按下就录成 Ctrl",
      (_kd3._press(op_dialog.KEY_CTRL, "", op_dialog.MOD_CTRL), _kd3.chosen()), ("Ctrl", "Ctrl"))
check("P33b 按住 Ctrl 再按 D → 覆盖成组合键",
      (_kd3._press(0x44, "d", op_dialog.MOD_CTRL), _kd3.chosen()), ("Ctrl+D", "Ctrl+D"))
check("P33c 单独按一下 Shift / Alt 也能录",
      (op_dialog.KeyEdit("")._press(op_dialog.KEY_SHIFT, "", op_dialog.MOD_SHIFT),
       op_dialog.KeyEdit("")._press(op_dialog.KEY_ALT, "", op_dialog.MOD_ALT)),
      ("Shift", "Alt"))
check("P34 CapsLock 能录", op_dialog.KeyEdit("")._press(op_dialog.KEY_CAPSLOCK, "", 0), "CapsLock")
check("P34b NumLock 能录", op_dialog.KeyEdit("")._press(op_dialog.KEY_NUMLOCK, "", 0), "NumLock")
check("P34c ScrollLock 能录",
      op_dialog.KeyEdit("")._press(op_dialog.KEY_SCROLLLOCK, "", 0), "ScrollLock")
check("P34d PrintScreen / Pause / Menu 能录",
      (op_dialog.KeyEdit("")._press(0x01000009, "", 0),
       op_dialog.KeyEdit("")._press(0x01000008, "", 0),
       op_dialog.KeyEdit("")._press(0x01000055, "", 0)),
      ("PrintScreen", "Pause", "Menu"))
check("P34e 小键盘 1 和主键盘 1 分开录（游戏里是两个键）",
      (op_dialog.KeyEdit("")._press(0x31, "1", op_dialog.MOD_KEYPAD),
       op_dialog.KeyEdit("")._press(0x31, "1", 0)),
      ("NumPad1", "1"))
check("P34f 小键盘 + / . / * 也能录",
      (op_dialog.KeyEdit("")._press(0x2B, "+", op_dialog.MOD_KEYPAD),
       op_dialog.KeyEdit("")._press(0x2E, ".", op_dialog.MOD_KEYPAD),
       op_dialog.KeyEdit("")._press(0x2A, "*", op_dialog.MOD_KEYPAD)),
      ("NumPad+", "NumPad.", "NumPad*"))
check("P34g 小键盘 +/-/*/. 写法能原样来回（存得进去也读得出来）",
      (ki.describe("NumPad+"), ki.describe("NumPad."), ki.describe("NumPad*"),
       ki.parse("Ctrl+NumPad+")[1]["vk"]),
      ("NumPad+", "NumPad.", "NumPad*", 0x6B))
check("P34h 小键盘数字写法能原样来回", ki.describe("numpad7"), "NumPad7")
check("P34i 小键盘键的 VK 和主键盘不同",
      (ki.parse("NumPad7")[1]["vk"], ki.parse("7")[1]["vk"]), (0x67, 0x37))
check("P34j 按下就记：Win 键**不收录**（系统保留），只提示一句", op_dialog.KeyEdit("")._press(
    op_dialog.KEY_META, "", op_dialog.MOD_META), "")
_wd = op_dialog.KeyEdit("F5")
_wn = []
_wd.note = _wn.append
check("P34k 按 Win 组合键也不收录（还是原样、给一句提示）",
      (_wd._press(0x44, "d", op_dialog.MOD_META), _wd.chosen(), _wn and "Win" in _wn[-1]),
      ("", "F5", True))
check("P35 想单独按 Ctrl 也行（解析得出来）", ki.parse("Ctrl")[1]["vk"], 0x11)
check("P35b 但「Ctrl+Shift」仍然是没写完（拦）", ki.parse("Ctrl+Shift")[0], False)
check("P36 只读框里没按键 → 值是空串（必填校验会拦住）", op_dialog.KeyEdit("").chosen(), "")
# 用户报的崩溃本身：qint 必须能把 Qt 枚举换成数字（真 GUI 里 int(枚举) 会 TypeError）
_like_enum = type("KeyboardModifier", (), {"value": 0x04000000})()
check("P37 Qt 枚举也能安全换成数字（就是它崩的每次按键）",
      (op_dialog.qint(_like_enum), op_dialog.qint(None), op_dialog.qint(32)),
      (op_dialog.MOD_CTRL, 0, 32))
_cxk = ops.OpContext(logger=lambda m: None)
_cxk.send_keys = lambda combo, logger=None: (True, "已按下 %s" % combo)
check("P28 按键操作把写法交给发送器",
      ops.run_item({"type": "send_keys", "params": {"keys": "Ctrl+D"}}, _cxk),
      (True, "已按下 Ctrl+D"))
check("P29 空按键 → 拦（不静默什么都不做）",
      ops.run_item({"type": "send_keys", "params": {"keys": ""}}, _cxk)[0], False)

# ============================================================ [Q] 发送通知
p("[Q] 发送通知：XML 拼装 / 转义 / 失败不谎报")

import toast_actions as ta                                       # noqa: E402

_ps_want = os.path.join(r"C:\Win", "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _ps_with(isfile, which=None):
    """假造一个 Windows 目录树 / 一个 PATH，问 `_powershell_exe()` 去哪儿找。"""
    real_env, real_isfile, real_which = ta.os.environ, ta.os.path.isfile, ta.shutil.which
    try:
        ta.os.environ = dict(real_env, SystemRoot=r"C:\Win")
        ta.os.path.isfile = isfile
        ta.shutil.which = which or (lambda name: None)
        return ta._powershell_exe()
    finally:
        ta.os.environ, ta.os.path.isfile, ta.shutil.which = real_env, real_isfile, real_which


def _ps_hit():
    """只存在 `...\\v1.0\\powershell.exe`（真实位置带 v1.0 这一层）→ 得去那儿找。"""
    return _ps_with(lambda p: p == _ps_want) == _ps_want


def _ps_fallback():
    """一个都找不到 → 退回按 PATH 找的名字（不崩、不谎报）。"""
    return _ps_with(lambda p: False, lambda name: "powershell.exe" if name == "powershell.exe" else None)


_xml = ta.build_xml("标题", "内容")
ok("Q1 标题 + 内容都在", "<text>标题</text>" in _xml and "<text>内容</text>" in _xml, _xml)
ok("Q2 没有按钮、也没有点击动作（点了只是被系统从通知中心收走）",
   ("<actions>" not in _xml and "activationType" not in _xml and "launch=" not in _xml), _xml)
ok("Q3 特殊字符转义（不会把 XML 拼坏）",
   "&amp;" in ta.build_xml("A&B") and "&lt;x&gt;" in ta.build_xml("A", "<x>"),
   ta.build_xml("A&B", "<x>"))
check("Q4 内容留空 → 只留标题那一行", ta.build_xml("T", "").count("<text>"), 1)
ok("Q4b 显示久一点（duration=long，别一闪就没）",
   'duration="long"' in _xml, _xml)
ok("Q4c 带系统提示音（声音 + 横幅一起提醒）",
   "<audio" in _xml and "ms-winsoundevent" in _xml, _xml)
check("Q5 通知里显示的程序名", ta.AUMID, "SCP_SL_BeBusy")
check("Q5b 通知里显示的名字是给人看的", ta.DISPLAY_NAME, "SCP:SL BeBusy")
ok("Q5c PowerShell 去找的是真实位置（`v1.0` 那一层不能漏）", _ps_hit(), True)
ok("Q5d 拿不到就老实退回按 PATH 找（不写死一个不存在的路径）",
   _ps_fallback() == "powershell.exe", _ps_fallback())
check("Q6 非 Windows 上 send() 老实报失败（不谎报「已发送」）",
      ta.send("T", "B", logger=lambda m: None)[0], False)


class _PopenResult(object):
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


_real_run = ta.subprocess.run
try:
    ta.subprocess.run = lambda *a, **k: _PopenResult(1, "", "拒绝访问")
    _pr = ta._run_ps("<toast/>", ta.AUMID)
    check("Q10 PowerShell 返回非 0 → 报失败", _pr[0], False)
    ok("Q11 失败说明里带上了系统给的原因", "拒绝访问" in _pr[1], _pr[1])
    ta.subprocess.run = lambda *a, **k: _PopenResult(0, "OPB_OK")
    check("Q12 拿到成功标记 → 才算成功", ta._run_ps("<toast/>", ta.AUMID)[0], True)
    check("Q12b 没读到条数就老实说不知道（-1）",
          ta._run_ps("<toast/>", ta.AUMID)[2], (-1, -1))
    ta.subprocess.run = lambda *a, **k: _PopenResult(0, "OPB_OK\nOPB_COUNT=2/3")
    check("Q12c 读回通知中心的条数（发前 / 发后）",
          ta._run_ps("<toast/>", ta.AUMID)[2], (2, 3))
    ta.subprocess.run = lambda *a, **k: _PopenResult(0, "")
    check("Q13 退出码 0 但没有成功标记 → 仍然报失败（不谎报）",
          ta._run_ps("<toast/>", ta.AUMID)[0], False)
finally:
    ta.subprocess.run = _real_run

# 送达核对：条数涨了才说「已进通知中心」；没涨就老实报 ⚠（专注助手 / 全屏会屏蔽）
_real_os = ta.os
_real_ps = ta._run_ps
try:
    ta.os = types.SimpleNamespace(name="nt", name_="nt", environ=os.environ, path=os.path,
                                  getpid=os.getpid, makedirs=os.makedirs,
                                  listdir=os.listdir, remove=os.remove, sep=os.sep)
    ta.ensure_aumid = lambda logger=None: (False, "（自检里不写注册表）")
    _seen_xml = {}

    def _fake_ps(xml, aumid, timeout=15):
        _seen_xml.update(xml=xml, aumid=aumid)
        return True, "", (1, 2)
    ta._run_ps = _fake_ps
    _got = ta.send("T", "B", logger=lambda m: None)
    check("Q16 条数涨了 → 才说「已进通知中心」", _got,
          (True, "已发送系统通知「T」（已进通知中心）"))
    ok("Q16b 发出去的 XML 就是拼好的那条（标题 + 内容都在）",
       ("<text>T</text>" in _seen_xml.get("xml", "")
        and "<text>B</text>" in _seen_xml.get("xml", "")), _seen_xml.get("xml", ""))
    _seen_xml.clear()
    ta.send("", "B", logger=lambda m: None)
    ok("Q16c 标题留空 → 用默认标题「%s」（不发出没标题的通知）" % ta.DEFAULT_TITLE,
       "<text>%s</text>" % ta.DEFAULT_TITLE in _seen_xml.get("xml", ""), _seen_xml.get("xml", ""))
    ta._run_ps = lambda *a, **k: (True, "", (2, 2))
    _got2 = ta.send("T", "B", logger=lambda m: None)
    check("Q17 没进通知中心 → 老实报失败（不谎报成功）", _got2[0], False)
    ok("Q17b 说明里点出可能被系统屏蔽（全屏 / 专注助手）",
       ("通知中心" in _got2[1] and "屏蔽" in _got2[1]), _got2[1])
    ta._run_ps = lambda *a, **k: (True, "", (-1, -1))
    check("Q18 读不到条数时按「已发送」说（只说交出去了，不吹进没进）",
          ta.send("T", "B", logger=lambda m: None)[1], "已发送系统通知「T」")

    # （「返回游戏」按钮：整条链路已删 —— 通知平台只认注册过的协议，
    #   要在 HKCU 写注册表才点得动，用户不要这个功能。）
finally:
    ta.os = _real_os
    ta._run_ps = _real_ps

_cxn = ops.OpContext(logger=lambda m: None)
_cxn.notify = lambda title, body, logger=None: (True, "已发送系统通知「%s」" % title)
check("Q14 通知操作：标题 + 内容原样交给发送器（没有按钮可传了）",
      ops.run_item({"type": "toast", "params": {"title": "T", "body": "B"}}, _cxn),
      (True, "已发送系统通知「T」"))
check("Q15 内容照传（不吞用户的字）",
      ops.run_item({"type": "toast", "params": {"title": "T", "body": "你已死亡"}}, _cxn),
      (True, "已发送系统通知「T」"))

# ============================================================ [R] 调节程序音量
p("[R] 调节程序音量：目标=当前就跳过；渐弱 / 渐强；缺会话、缺后端老实报")

import volume_actions as va                                      # noqa: E402


class FakeVol(object):
    """假后端：按进程名找（pid 查询只认 own）。"""

    name = "fake"

    def __init__(self, vols=None, own=None):
        self.vols = dict(vols or {})
        self.own = own
        self.set_calls = []

    def find(self, pid=None, proc=None):
        if pid is not None:
            return ("own", self.own) if self.own is not None else None
        key = (proc or "").lower()
        if key in self.vols:
            return ("h:" + key, self.vols[key])
        return None

    def set(self, handle, v):
        self.set_calls.append((handle, v))
        if handle.startswith("h:"):
            self.vols[handle[2:]] = v
        return True


_real_backend = va.backend
try:
    _b = FakeVol({"scpsl.exe": 0.8})
    va.backend = lambda: _b
    check("R1 目标 == 当前（80%）→ 跳过，而且不算失败",
          va.set_process_volume("SCPSL.exe", "80", 0, logger=lambda m: None),
          (True, "SCPSL.exe 音量本来就是 80%，跳过"))
    check("R2 跳过时一次都没改（真·无效）", _b.set_calls, [])

    check("R3 直接切（渐变 0）成功",
          va.set_process_volume("SCPSL.exe", "30", 0, logger=lambda m: None)[0], True)
    check("R4 一次就设到 0.3", _b.set_calls[-1], ("h:scpsl.exe", 0.3))

    _b2 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _b2
    _slept = []
    _r5 = va.set_process_volume("SCPSL.exe", "0", 1000, sleep=_slept.append,
                                logger=lambda m: None)
    check("R5 渐弱到 0：说明里写了「渐弱」", (_r5[0], "渐弱" in _r5[1]), (True, True))
    check("R6 1000ms / 40ms 一片 = 25 次写入", len(_b2.set_calls), 25)
    check("R7 最后一步精确落在目标 0", _b2.set_calls[-1][1], 0.0)
    check("R8 音量单调下降（不会来回抖）",
          all(_b2.set_calls[i][1] >= _b2.set_calls[i + 1][1]
              for i in range(len(_b2.set_calls) - 1)), True)
    check("R9 每片真的等了（合计 1s）", round(sum(_slept), 6), 1.0)

    _b3 = FakeVol({"scpsl.exe": 0.2})
    va.backend = lambda: _b3
    check("R10 渐强：目标 100 > 当前 20",
          "渐强" in va.set_process_volume("SCPSL.exe", "100", 80, sleep=lambda s: None,
                                         logger=lambda m: None)[1], True)

    _b4 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _b4
    _n = {"i": 0}

    def _tick(_s):
        _n["i"] += 1

    _r11 = va.set_process_volume("SCPSL.exe", "0", 1000, cancel=lambda: _n["i"] >= 3,
                                 sleep=_tick, logger=lambda m: None)
    check("R11 被打断 → 报失败 + 说明停在哪儿", (_r11[0], "被打断" in _r11[1]), (False, True))
    check("R12 打断后不再往下写", len(_b4.set_calls), 3)

    _b5 = FakeVol({})
    va.backend = lambda: _b5
    check("R13 找不到这个程序的音频会话 → 老实报失败",
          va.set_process_volume("SCPSL.exe", "50", 0, logger=lambda m: None),
          (False, "没找到 SCPSL.exe 的音频会话（程序没开，或它现在没在出声）"))
    va.backend = lambda: None
    check("R14 没有 pycaw / 不是 Windows → 老实报失败（不崩）",
          va.set_process_volume("SCPSL.exe", "50", 0, logger=lambda m: None)[0], False)
    _b6 = FakeVol({"scpsl.exe": 0.5})
    va.backend = lambda: _b6
    check("R15 音量越界被拦",
          va.set_process_volume("SCPSL.exe", "101", 0, logger=lambda m: None)[0], False)
    check("R16 渐变超过 3000ms 被拦",
          va.set_process_volume("SCPSL.exe", "10", "4000", logger=lambda m: None)[0], False)
    check("R17 进程名空 → 报错（不瞎猜）",
          va.set_process_volume("", "10", 0, logger=lambda m: None)[0], False)

    # ---- 后台渐变（用户要求：渐变不算延迟执行，自己在后台跑完） ----
    _bg = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _bg
    _blog = []
    _r21 = va.start_fade("SCPSL.exe", "0", 400, logger=_blog.append)
    check("R21 后台渐变：立刻返回「已开始…后台执行」",
          (_r21[0], "已开始" in _r21[1], "后台" in _r21[1]), (True, True, True))
    check("R22 返回时还没跑完（没堵住后面的操作）", len(_bg.set_calls) < 5, True)
    check("R23 它自己在后台跑到目标（最后正好落在 0）",
          (va.wait_fades(5), _bg.set_calls[-1][1]), (True, 0.0))
    check("R24 状态记成「已完成」", va.fade_state("SCPSL.exe")[0], "已完成")
    ok("R25 日志写了开始 + 完毕（能对账）",
       any("开始" in l for l in _blog) and any("完毕" in l for l in _blog), str(_blog))

    _bg2 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _bg2
    _blog2 = []
    va.start_fade("SCPSL.exe", "0", 1500, logger=_blog2.append)
    _time.sleep(0.2)                                   # 让它先跑几片
    va.start_fade("SCPSL.exe", "100", 200, logger=_blog2.append)   # 新的（渐强回来）
    check("R26 新渐变跑完", va.wait_fades(5), True)
    check("R27 最后停在新目标（新的说了算）",
          int(round(_bg2.set_calls[-1][1] * 100)), 100)
    ok("R28 日志写明旧渐变「让位」（不是偷偷还在跑）",
       any("让位" in l for l in _blog2), str(_blog2))

    _bg3 = FakeVol({"scpsl.exe": 0.5})
    va.backend = lambda: _bg3
    check("R29 目标就是当前 → 跳过（后台也不开）",
          va.start_fade("SCPSL.exe", "50", 1000, logger=lambda m: None),
          (True, "SCPSL.exe 音量本来就是 50%，跳过"))
    _bg4 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _bg4
    check("R30 渐变 0 = 直接切过去（不排后台线程）",
          (va.start_fade("SCPSL.exe", "20", 0, logger=lambda m: None)[1],
           _bg4.set_calls[-1][1]),
          ("已把 SCPSL.exe 音量设成 20%", 0.2))

    _bg5 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _bg5
    va.start_fade("SCPSL.exe", "0", 3000, logger=lambda m: None)
    _wrote_before = len(_bg5.set_calls)
    check("R31 程序退出时把还在跑的渐变停掉（不留后台偷偷改音量）",
          (va.stop_fades("程序退出", wait=2) >= 1, va.fade_state("SCPSL.exe")[0]),
          (True, "被打断"))
    _time.sleep(0.15)
    check("R32 停掉之后一片都不再写", len(_bg5.set_calls), _wrote_before)

    va.backend = lambda: None
    check("R33 没有 pycaw / 不是 Windows：后台渐变也老实报失败",
          va.start_fade("SCPSL.exe", "0", 100, logger=lambda m: None)[0], False)

    _bg6 = FakeVol({"scpsl.exe": 1.0})
    va.backend = lambda: _bg6
    check("R34 后端不会列进程 → 给空表（不崩）", va.list_processes(), [])
    _bg7 = FakeVol({"scpsl.exe": 1.0})
    _bg7.list_processes = lambda: [("bodian_pc.exe", 0), ("QQ.exe", 80)]
    va.backend = lambda: _bg7
    check("R35 「选进程」列的就是现在有声音的程序",
          va.list_processes(), [("bodian_pc.exe", 0), ("QQ.exe", 80)])
finally:
    va.backend = _real_backend

_cxv = ops.OpContext(logger=lambda m: None)
_vcalls = []
_cxv.set_proc_volume = lambda proc, level, fade, cancel=None, logger=None, sleep=None: (
    _vcalls.append((proc, level, fade)), (True, "OK"))[1]
check("R19 音量操作走 ctx.set_proc_volume（参数原样传下去）",
      (ops.run_item({"type": "set_volume",
                     "params": {"proc": "SCPSL.exe", "level": "20", "fade_ms": "0"}}, _cxv),
       _vcalls),
      ((True, "OK"), [("SCPSL.exe", "20", "0")]))
check("R20 进程名留空 → 添加时就拦住（不瞎猜目标）",
      ops.validate_item({"type": "set_volume",
                         "params": {"proc": "", "level": "20", "fade_ms": "0"}})[0], False)

# ============================================================ [S] 死亡判定时间
p("[S] 死亡判定时间：闭区间 [500,10000]；非法不落盘")

check("S1 下界 500 合法", triggermod.coerce_settle_ms(500), (True, 500))
check("S1b 499 低于下限 → 拦", triggermod.coerce_settle_ms(499)[0], False)
check("S2 上界 10000 合法", triggermod.coerce_settle_ms("10000"), (True, 10000))
check("S3 默认 700 合法", triggermod.coerce_settle_ms("700"), (True, 700))
check("S4 写「700ms」也认", triggermod.coerce_settle_ms("700ms"), (True, 700))
check("S5 10001 越界 → 拦", triggermod.coerce_settle_ms(10001)[0], False)
check("S6 -1 越界 → 拦", triggermod.coerce_settle_ms(-1)[0], False)
check("S7 非数字 → 拦", triggermod.coerce_settle_ms("半秒")[0], False)
ok("S8 报错文案里写了合法范围", "500-10000" in triggermod.coerce_settle_ms(99999)[1],
   triggermod.coerce_settle_ms(99999)[1])
check("S9 默认还是 700ms（0.7s）",
      (triggermod.DEATH_SETTLE_S, cfgmod.DEFAULTS["death_settle_ms"]), (0.7, 700))

_tr = triggermod.Trigger(is_dead=lambda: True, run_death=lambda r, d: None,
                 run_alive=lambda r, d: None, logger=lambda m: None)
check("S10 触发器默认 700ms", (_tr.settle_ms, _tr.settle_s), (700, 0.7))
_tr.set_settle_ms(1200)
check("S11 改完立即生效（下一张死亡门就用新值）", (_tr.settle_ms, _tr.settle_s), (1200, 1.2))

_core = appcore.AppCore.__new__(appcore.AppCore)
_core.cfg = cfgmod.Config(os.path.join(TMP, "settle.json"))
_core.death_settle_ms = 700
_core.trigger = triggermod.Trigger(is_dead=lambda: True, run_death=lambda r, d: None,
                           run_alive=lambda r, d: None, logger=lambda m: None)
_core.logs2 = []
_core.log = types.SimpleNamespace(log=_core.logs2.append, path=os.path.join(TMP, "s.log"))
check("S12 合法值：写进配置 + 触发器跟着走",
      (appcore.AppCore.set_death_settle_ms(_core, 1200),
       _core.cfg.get("death_settle_ms"), _core.trigger.settle_ms, _core.death_settle_ms),
      ((True, "死亡判定时间已改成 1200ms（这个时间内复活就当作没死）"), 1200, 1200, 1200))
check("S13 配置里存的是数字", _core.cfg.get("death_settle_ms"), 1200)
check("S14 非法值：配置和触发器都不动",
      (appcore.AppCore.set_death_settle_ms(_core, 99999)[0],
       _core.cfg.get("death_settle_ms"), _core.trigger.settle_ms),
      (False, 1200, 1200))
ok("S15 非法值留了 ⚠ 日志（不静默吞掉）",
   any("死亡判定时间没改" in l for l in _core.logs2), str(_core.logs2[-1:]))

# ============================================================ [T] 打断联动
p("[T] 打断联动：新列表开始 → 旧令牌置上 + 语音队列收手")


class _FakeSpeech(object):
    def __init__(self):
        self.purged = []

    def purge(self, why=""):
        self.purged.append(why)
        return 0

    def pending(self):
        return 0


_core2 = appcore.AppCore.__new__(appcore.AppCore)
_core2.speech = _FakeSpeech()
_core2.log = types.SimpleNamespace(log=lambda m: None)
_core2._run_token = threading.Event()
_core2._run_which = ""
_old = _core2._run_token
_new = appcore.AppCore._begin_run(_core2, "death")
check("T1 换了新令牌（新列表用新的）", _new is _core2._run_token, True)
check("T2 旧令牌被置上 → 上一条列表会自己收手", _old.is_set(), True)
check("T3 新令牌是干净的（不会一开跑就自杀）", _new.is_set(), False)
check("T4 语音队列同时被打断 + 清空", _core2.speech.purged, ["新的状态变化"])
check("T5 记下这次跑的是哪个列表", _core2._run_which, "death")
appcore.AppCore._begin_run(_core2, "alive")
check("T6 死亡列表没跑完就复活 → 死亡那条一样被打断",
      (_core2.speech.purged[-1], _core2._run_which), ("新的状态变化", "alive"))

# 端到端：死亡列表里的「延迟」被复活打断 → 后面的操作一条都不跑
_opened = []
_core3 = appcore.AppCore.__new__(appcore.AppCore)
_core3.cfg = cfgmod.Config(os.path.join(TMP, "e2e.json"))
_core3.cfg.set_ops("death", [{"type": "delay", "params": {"ms": "5000"}},
                             {"type": "open_url", "params": {"url": "https://x"}}])
_core3.cfg.save()
_core3.speech = _FakeSpeech()
_core3.logs3 = []
_core3.log = types.SimpleNamespace(log=_core3.logs3.append, path=os.path.join(TMP, "e2e.log"))
_core3.audio = _StatusAudio()
_core3.death_settle_ms = 700
_core3._run_token = threading.Event()
_core3._run_which = ""
_core3.trigger = triggermod.Trigger(is_dead=lambda: True, run_death=lambda r, d: None,
                            run_alive=lambda r, d: None, logger=lambda m: None)
_e2e = ops.OpContext(logger=_core3.logs3.append,
                     cancel=lambda: _core3._run_token.is_set())
_e2e.open_url = lambda u: (_opened.append(u), (True, "已打开"))[1]
_slices = {"n": 0}


def _e2e_sleep(_s):
    _slices["n"] += 1
    if _slices["n"] >= 2:                        # 第 2 片（≈100ms）时"复活了"
        _core3._run_token.set()


_e2e.sleep = _e2e_sleep
_core3.op_context = lambda: _e2e
appcore.AppCore._on_death_fired(_core3, "You died.", "")
check("T7 死亡列表被打断 → 后面的「打开网页」一条都没跑", _opened, [])
ok("T8 日志明说被打断 + 剩余不再执行",
   any("被新的状态变化打断" in l for l in _core3.logs3)
   and any("不再执行" in l for l in _core3.logs3), str(_core3.logs3[-3:]))
ok("T9 被打断的那条没被算成成功（记 ⏹）",
   any("⏹" in l for l in _core3.logs3), str(_core3.logs3[-3:]))
check("T10 收尾日志写了「被中断」", any("被中断" in l for l in _core3.logs3), True)

# ============================================================ [U] 托盘手动对齐媒体状态
p("[U] 手动对齐媒体状态（只改程序内状态，一个媒体键都不发）")


class _MarkAudio(object):
    def __init__(self):
        self.marked = []

    def mark(self, v):
        self.marked.append(v)
        return v


_core4 = appcore.AppCore.__new__(appcore.AppCore)
_core4.audio = _MarkAudio()
_core4.logs4 = []
_core4.log = types.SimpleNamespace(log=_core4.logs4.append, path=os.path.join(TMP, "u.log"))
check("U1 托盘「当前媒体处于播放状态」→ 只把状态记成播放中",
      appcore.AppCore.manual_play(_core4), "播放中")
check("U2 状态真的记进去了", _core4.audio.marked, [True])
ok("U3 一个媒体键都没发（日志里明说）",
   any("没发媒体键" in l for l in _core4.logs4), str(_core4.logs4[-1:]))
check("U4 「暂停中」同理", appcore.AppCore.manual_pause(_core4), "暂停中")
check("U5 记成 False", _core4.audio.marked, [True, False])
_core5 = appcore.AppCore.__new__(appcore.AppCore)
_core5.log = types.SimpleNamespace(log=lambda m: None)
check("U6 没有音频后端 → 老实报失败（不崩）", appcore.AppCore.manual_play(_core5), False)

# （U7~U13 原来测的是通知里那个「返回游戏」小进程：功能已删，一起删掉。


# ============================================================ 结果
shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 64)
print("PASS %d / FAIL %d" % (len(PASS), len(FAILS)))
if FAILS:
    print("❌ 失败：%s" % FAILS)
    sys.exit(1)
print("✅ 全部通过")
