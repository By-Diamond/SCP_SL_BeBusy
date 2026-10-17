# -*- coding: utf-8 -*-
"""
发送通知（无界面）：Windows 通知中心的一条 toast
================================================

* 走系统自带的通知接口（`Windows.UI.Notifications`），**不装任何第三方库**：
  用一个后台 PowerShell 进程把拼好的 XML 交给系统，然后把结果如实带回来。
* 标题 / 内容自己填；**没有按钮、点它不做任何事**（点了只是被系统从通知中心收走）。
  （以前有个「返回游戏」按钮：通知平台只认"注册过的协议"，要靠写 HKCU 注册表
  才点得动 —— 用户不要这个功能，整条链路已删。）
* 通知**显示久一点 + 带系统提示音**（更容易被注意到）；并注册一条 HKCU 的
  `AppUserModelId`，让通知里显示成「SCP:SL BeBusy」+ 程序图标。
* **送达要核对**：发完读回通知中心的条数，条数涨了才说「已进通知中心」；
  没涨就老实报 ⚠（专注助手 / **全屏游戏**时 Windows 会屏蔽横幅，这是系统行为）。
* **成功才报成功**：PowerShell 返回非 0 / 没拿到成功标记 → 报 ⚠（不谎报"已发送"）。
* 非 Windows / 找不到 PowerShell → 老实报失败，不崩。
"""

import base64
import os
import shutil
import subprocess
import sys

AUMID = "SCP_SL_BeBusy"                # 通知里显示的"程序名"（不需要事先注册）
DISPLAY_NAME = "SCP:SL BeBusy"         # 通知里显示的名字（注册到 HKCU 后生效）
DEFAULT_TITLE = "SCP:SL BeBusy"
TIMEOUT_S = 15
CREATE_NO_WINDOW = 0x08000000
SOUND = "ms-winsoundevent:Notification.Default"

_logger = print
_aumid_state = {}                      # 只注册/记录一次


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


# ----------------------------- XML -----------------------------


def _esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def build_xml(title, body="", sound=True):
    """拼 toast XML：标题 + 内容（可选）+ 系统提示音（可选）。

    **没有按钮、没有点击动作** —— 通知就是「看一眼」用的。
    """
    lines = ['<toast duration="long">', "  <visual>",
             '    <binding template="ToastGeneric">',
             "      <text>%s</text>" % _esc(title)]
    if str(body or "").strip():
        lines.append("      <text>%s</text>" % _esc(body))
    lines += ["    </binding>", "  </visual>"]
    if sound:
        lines.append('  <audio src="%s" loop="false"/>' % SOUND)
    lines.append("</toast>")
    return "\n".join(lines)


# ----------------------------- 通知里显示的程序名 / 图标 -----------------------------

AUMID_KEY = r"Software\Classes\AppUserModelId\%s" % AUMID


def _icon_path():
    """程序图标（打包成 exe 用自己的 exe；源码运行有 assets/app.ico 就用它）。"""
    if getattr(sys, "frozen", False):
        return sys.executable or ""
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "assets", "app.ico")
    return p if os.path.isfile(p) else ""


def ensure_aumid(logger=None):
    """让通知显示成「SCP:SL BeBusy」+ 图标：写一条**当前用户**的 HKCU 注册表。

    只写 `HKCU\\Software\\Classes\\AppUserModelId\\SCP_SL_BeBusy` 里的显示名和图标；
    写不了也不影响发通知（照样发，只是通知里没名字/图标）。返回 (ok, 说明)。
    """
    if _aumid_state.get("done"):
        return _aumid_state.get("ok", False), _aumid_state.get("msg", "")
    _aumid_state["done"] = True
    say = logger or log
    if os.name != "nt":
        _aumid_state.update(ok=False, msg="非 Windows 环境")
        return False, "非 Windows 环境"
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUMID_KEY) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, DISPLAY_NAME)
            icon = _icon_path()
            if icon:
                winreg.SetValueEx(k, "IconUri", 0, winreg.REG_SZ, icon)
        msg = "通知显示名已注册：%s%s" % (DISPLAY_NAME, "（带图标）" if icon else "（没找到图标，只有名字）")
        _aumid_state.update(ok=True, msg=msg)
        say("[toast] %s" % msg)
        return True, msg
    except Exception as e:
        msg = "注册通知显示名失败（不影响发通知）：%r" % (e,)
        _aumid_state.update(ok=False, msg=msg)
        say("⚠ [toast] %s" % msg)
        return False, msg


# ----------------------------- 发给系统 -----------------------------

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$history = [Windows.UI.Notifications.ToastNotificationManager]::History
$before = 0
try { $before = @($history.GetHistory($env:OPB_AUMID)).Count } catch { $before = -1 }
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:OPB_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:OPB_AUMID)
$notifier.Show($toast)
Write-Output 'OPB_OK'
Start-Sleep -Milliseconds 900
$after = 0
try { $after = @($history.GetHistory($env:OPB_AUMID)).Count } catch { $after = -1 }
Write-Output ('OPB_COUNT=' + $before + '/' + $after)
"""


def _powershell_exe():
    """系统自带 PowerShell 的**真实路径**（找不到就让系统按 PATH 找）。

    真实位置是 `...\\WindowsPowerShell\\v1.0\\powershell.exe` —— `v1.0` 这一层不能漏
    （漏了 isfile 就为假、只好靠 PATH；PATH 里没有时整条调用会 FileNotFoundError）。
    32 位进程看到的是 `SysWOW64`。
    """
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    cands = [os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
             os.path.join(root, "SysWOW64", "WindowsPowerShell", "v1.0", "powershell.exe")]
    for p in cands:
        if os.path.isfile(p):
            return p
    try:
        found = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    except Exception:
        found = ""
    return found or "powershell.exe"


def _counts_from(out):
    """从 PowerShell 输出里取 `OPB_COUNT=发前/发后`（取不到就是 (-1, -1)）。"""
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("OPB_COUNT="):
            try:
                a, b = line.split("=", 1)[1].split("/")
                return int(a), int(b)
            except Exception:
                return (-1, -1)
    return (-1, -1)


def _run_script(script, extra_env=None, timeout=TIMEOUT_S):
    """跑一段 PowerShell（参数走环境变量，中文/引号都不会炸）。

    返回 (ok, 说明, 条数信息)；`条数信息` = (动手之前的条数, 之后的)，拿不到 = -1。
    """
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ)
    env.update(extra_env or {})
    cmd = [_powershell_exe(), "-NoProfile", "-NonInteractive",
           "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc]
    kw = dict(capture_output=True, text=True, encoding="utf-8", errors="replace",
              env=env, timeout=timeout)
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    r = subprocess.run(cmd, **kw)                          # noqa: S603
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    counts = _counts_from(out)
    if r.returncode == 0 and "OPB_OK" in out:
        return True, "", counts
    detail = (err or out or "（没有输出）").replace("\n", " ")[:300]
    return False, "PowerShell 返回 %s：%s" % (r.returncode, detail), counts


def _run_ps(xml, aumid, timeout=TIMEOUT_S):
    """把 XML 交给 PowerShell 发出去。返回 (ok, 说明, 条数信息)。"""
    return _run_script(PS_SCRIPT, {"OPB_XML": xml, "OPB_AUMID": aumid}, timeout)


def send(title="", body="", logger=None):
    """发一条通知。返回 (ok, 说明)。

    **不谎报**：只有真的交给系统并且通知中心条数涨了，才说「已进通知中心」。
    """
    say = logger or log
    t = str(title or "").strip() or DEFAULT_TITLE
    b = str(body or "").strip()
    if os.name != "nt":
        say("⚠ 非 Windows 环境：通知没发出去")
        return False, "非 Windows 环境，通知发不出去"
    ensure_aumid(say)
    xml = build_xml(t, b)
    try:
        ok, msg, counts = _run_ps(xml, AUMID)
    except subprocess.TimeoutExpired:
        return False, "发通知超时（%ds）" % TIMEOUT_S
    except Exception as e:
        return False, "发通知失败：%r" % (e,)
    if not ok:
        return False, msg
    before, after = counts
    if after >= 0 and before >= 0:
        if after > before:
            return True, "已发送系统通知「%s」（已进通知中心）" % t
        return False, ("通知交给系统了，但通知中心没多出来（专注助手 / 全屏游戏时 Windows "
                       "会屏蔽横幅）：「%s」" % t)
    return True, "已发送系统通知「%s」" % t
