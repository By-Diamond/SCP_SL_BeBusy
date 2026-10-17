# -*- coding: utf-8 -*-
"""
SCP:SL BeBusy（PySide6 托盘 + 界面版）—— 程序入口
====================================================

干什么
------
* 用 v7 算法判定 **存活** / **死亡·观察者**（`scpsl_state.py`，未改动）。
* **死亡**（保持设定时间未复活，默认 700ms，设置页可改 500-10000ms）→ 按顺序执行「死亡后」动作列表；
  **复活** → 立即执行「复活后」动作列表。
* 动作 = 媒体播放/暂停 / 打开网页 / 切换窗口 / 最小化窗口 / 执行文件 / 调节程序音量 / 语音播报 /
  发送通知 / 延迟执行 / 模拟按键（都在 `operations.py` 里注册，可扩展）。
* **列表互不重叠**：新的死亡/复活一来，正在跑的那条列表立刻被打断（语音队列也一起收手）。
* 界面：左侧导航（日志 / 功能配置 / 设置 / 关于），改动**立即生效**。
* 托盘：左键=显示界面，右键=菜单（含手动对齐媒体状态、退出）；点 ✕ = 隐藏到托盘。

形态
----
* 启动后**不弹窗**，只在托盘出现图标（绿=存活 / 红=死亡·观察者），并弹一条提示。
* 无控制台运行：`pythonw scpsl_auto_player.py`；打包后双击 exe 即可。

安全性
------
* 只读游戏日志 + 监听**自己注册**的 Shell 钩子；**不注入、不挂钩游戏、不读内存、不装键盘钩子**。
* 不修改游戏本体。会动到的东西都在界面上写着：**某个程序自己**的音量（不动系统总音量）、
  系统通知、**真实按键事件**（发给当时最前面的窗口）、开关窗口。
"""

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import autostart as autostartmod                              # noqa: E402
import config as cfgmod                                      # noqa: E402
import logbus as logmod                                      # noqa: E402
from appcore import AppCore                                  # noqa: E402

_MUTEX_HANDLE = None


def message_box(title, text):
    """不依赖 Qt 的提示框（依赖缺失时也能提示）。"""
    try:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x40)
        else:
            print("%s: %s" % (title, text))
    except Exception:
        print("%s: %s" % (title, text))


def single_instance(name="SCP_SL_BeBusy_SingleInstance_v1"):
    """已有一个实例在跑就返回 False（用命名互斥体，无需管理员）。"""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _MUTEX_HANDLE = kernel32.CreateMutexW(None, False, name)
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
        return True
    except Exception:
        return True


def install_error_hook(log_fn=None):
    """把「没人接住的异常」变成：写日志 + 弹窗。

    打包成 exe 是 `--windowed`（没有控制台），Qt 里一个槽函数抛异常默认只会被打印到
    不存在的地方 —— 用户看到的就是"点了没反应"。这个钩子保证不再有静默失败。
    """
    import threading
    import traceback

    def handle(exc_type, exc, tb, where=""):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            if log_fn:
                log_fn("⚠ 未处理异常%s：\n%s" % (where, text))
        except Exception:
            pass
        try:
            tail = text.strip().splitlines()[-1]
            message_box("程序出错", "出错了，详见日志：\n%s" % tail)
        except Exception:
            pass

    def hook(exc_type, exc, tb):
        handle(exc_type, exc, tb)

    sys.excepthook = hook

    def thook(args):
        handle(args.exc_type, args.exc_value, args.exc_traceback, "（后台线程）")

    try:
        threading.excepthook = thook
    except Exception:
        pass
    return hook


def main(argv=None):
    argv = list(argv or sys.argv)

    if not single_instance():
        message_box("%s 已在运行" % cfgmod.APP_TITLE,
                    "程序已在托盘里运行（左键托盘图标可打开界面）")
        return 2

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:
        message_box("缺少依赖", "没装 PySide6，无法显示界面。\n"
                              "请执行：pip install -r requirements.txt\n"
                              "（%r）" % (e,))
        return 3

    from ui.bridge import Bridge
    from ui.icons import app_icon
    from ui.main_window import MainWindow
    from ui.tray import Tray

    app = QApplication(argv)
    app.setApplicationName(cfgmod.APP_NAME)
    # 注意：**不要**给 setApplicationDisplayName 设程序名 —— Windows 会把它追加到窗口标题末尾
    # （标题会变成 "… — 存活 - SCP:SL BeBusy"）。设成空串，标题就只由我们显式设定。
    app.setApplicationDisplayName("")
    app.setApplicationVersion(cfgmod.VERSION)
    app.setQuitOnLastWindowClosed(False)          # 关窗口只是隐藏，不退出
    app.setWindowIcon(app_icon())

    bus = logmod.LogBus()
    legacy_note = cfgmod.migrate_from_legacy()    # 旧名字（SCPSL_AutoAudio）目录 → 新目录
    cfg = cfgmod.Config()
    core = AppCore(cfg, bus)
    install_error_hook(core.log.log)             # 未处理异常 → 日志 + 弹窗（不再静默）
    auto_note = autostartmod.migrate_from_legacy()   # 旧自启项名字 → 新名字
    for _note in (legacy_note, auto_note):
        if _note:
            core.log.log("[cfg] %s" % _note)
    bridge = Bridge()
    win = MainWindow(core)
    tray = Tray(core)

    # ---- 日志：后台线程 → 界面（Qt 自动排队，跨线程安全） ----
    core.log.subscribe(lambda line, level: bridge.log_line.emit(line, level))
    bridge.log_line.connect(win.append_log)

    # ---- 状态：判定线程 → 界面/托盘 ----
    core.on_state = lambda s, r, d: bridge.state_changed.emit(s, r, d)
    bridge.state_changed.connect(win.set_state)
    bridge.state_changed.connect(lambda s, r, d: tray.set_state(s, r))

    # ---- 托盘菜单 ----
    tray.show_requested.connect(win.show_and_raise)
    tray.hide_requested.connect(win.hide)
    tray.manual_play.connect(core.manual_play)
    tray.manual_pause.connect(core.manual_pause)

    # ---- 退出 ----
    quitting = {"done": False}

    def quit_all():
        if quitting["done"]:
            return
        quitting["done"] = True
        core.log.log("[ui] 用户从托盘退出")
        win.force_close()
        tray.icon.hide()
        core.stop()
        app.quit()

    tray.quit_requested.connect(quit_all)
    app.aboutToQuit.connect(core.stop)

    win.hidden_to_tray.connect(
        lambda: tray.notify(cfgmod.APP_TITLE, "已最小化到托盘，双击托盘图标可以再打开界面"))

    # ---- 起 ----
    core.start()
    tray.show()
    tray.set_state(core.state, "已启动，等待状态变化")
    win.set_state(core.state, "启动")
    tray.notify("%s v%s" % (cfgmod.APP_TITLE, cfgmod.VERSION),
                "已在托盘运行：左键点图标 = 打开界面，右键 = 菜单。")
    core.log.log("[ui] 界面已就绪（当前为隐藏状态，左键托盘图标可打开）")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
