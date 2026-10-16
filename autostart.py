# -*- coding: utf-8 -*-
"""
开机自启动（Windows 注册表 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`）
====================================================================================

* 只写**当前用户**的 Run 键 → **不需要管理员权限**；任务管理器「启动」里能看到、能关。
* 源码运行 → 注册 `"<pythonw.exe>" "<项目>\\scpsl_auto_player.py"`；
  exe 运行 → 注册 `"<exe 路径>"`（不带参数）。
* 所有函数在非 Windows 上返回「不支持」，不抛异常（方便在 Linux 侧验证）。
"""

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SCP_SL_BeBusy"
LEGACY_VALUE_NAMES = ("SCPSL_AutoAudio",)         # 改名前的自启项名字


def is_supported():
    return os.name == "nt"


def _winreg():
    import winreg                                   # 仅 Windows 有
    return winreg


def script_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "scpsl_auto_player.py")


def startup_command():
    """注册表里该写的完整命令行。"""
    if getattr(sys, "frozen", False):
        return '"%s"' % os.path.abspath(sys.executable)
    exe = sys.executable or "python"
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw                                    # 无控制台窗口
    return '"%s" "%s"' % (os.path.abspath(exe), script_path())


def current_command():
    """注册表里当前的命令（没有则空串）。"""
    if not is_supported():
        return ""
    try:
        with _winreg().OpenKey(_winreg().HKEY_CURRENT_USER, RUN_KEY, 0,
                               _winreg().KEY_READ) as k:
            value, _t = _winreg().QueryValueEx(k, VALUE_NAME)
            return value or ""
    except FileNotFoundError:
        return ""
    except OSError:
        return ""
    except Exception:
        return ""


def is_enabled():
    return bool(current_command()) if is_supported() else False


def enable(cmd=None):
    """写注册表。返回 (ok, 说明)。"""
    if not is_supported():
        return False, "当前系统不是 Windows，无法设置开机自启动"
    cmd = cmd or startup_command()
    try:
        with _winreg().CreateKeyEx(_winreg().HKEY_CURRENT_USER, RUN_KEY, 0,
                                   _winreg().KEY_SET_VALUE) as k:
            _winreg().SetValueEx(k, VALUE_NAME, 0, _winreg().REG_SZ, cmd)
        return True, "已设置开机自启动：%s" % cmd
    except Exception as e:
        return False, "设置开机自启动失败：%r" % (e,)


def disable():
    """删注册表项。返回 (ok, 说明)。"""
    if not is_supported():
        return False, "当前系统不是 Windows，无需关闭开机自启动"
    try:
        with _winreg().OpenKey(_winreg().HKEY_CURRENT_USER, RUN_KEY, 0,
                               _winreg().KEY_SET_VALUE) as k:
            _winreg().DeleteValue(k, VALUE_NAME)
        return True, "已关闭开机自启动"
    except FileNotFoundError:
        return True, "开机自启动本来就是关闭的"
    except OSError:
        return True, "开机自启动本来就是关闭的"
    except Exception as e:
        return False, "关闭开机自启动失败：%r" % (e,)


def apply(enabled):
    """按需要的状态写好（幂等）。返回 (ok, 说明)。"""
    if enabled:
        if is_enabled():
            return True, "开机自启动已开启（无需改动）"
        return enable()
    if not is_enabled():
        return True, "开机自启动已关闭（无需改动）"
    return disable()


def migrate_from_legacy():
    """改名迁移：旧的 Run 值还在、新的没有 → 换成新名字（指向当前程序）。

    返回说明（没做事则空串）。失败不抛异常（自启是附加功能）。
    """
    if not is_supported():
        return ""
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            for old in LEGACY_VALUE_NAMES:
                try:
                    old_cmd, _t = winreg.QueryValueEx(k, old)
                except OSError:
                    continue
                if not old_cmd:
                    continue
                ok, msg = enable()
                if not ok:
                    return "旧自启项迁移失败：%s" % msg
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as kw:
                        winreg.DeleteValue(kw, old)      # 只删旧的这一项
                except Exception:
                    pass
                return "开机自启动已从旧项「%s」迁移" % old
    except Exception:
        return ""
    return ""


def status():
    return {
        "supported": is_supported(),
        "enabled": is_enabled(),
        "registered": current_command(),
        "wanted": startup_command(),
    }
