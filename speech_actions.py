# -*- coding: utf-8 -*-
"""
语音播报（无界面）：先播提示音（可选）→ 再朗读文本（可选）
==========================================================

* 一个后台线程 + **一个队列**：死亡播报和复活播报都排在这一个队列里（用户要求），
  同一时刻只有一条在响，永远不会两条声音叠在一起。
* **提示音文件**：交给**系统自带的播放器**（WinRT `MediaPlayer`）去放，所以
  mp3 / m4a / wav / flac / mp4 里装的声音都行 —— 不看扩展名、看内容
  （实测：扩展名是 .mp3、其实是 MP4 容器的文件，MCI 放不了、这条路能放）。
  音量用播放器自己的音量，**和语音朗读音量互不影响**（用户要求）。
  打断 = 收掉播放器进程（声音立刻停）。
* **朗读文本**：用 Windows 自带的语音引擎（SAPI）直接朗读，音量 = 引擎音量
  （同样和提示音音量互不影响）；打断 = 清空引擎队列，立刻停。
* 没装 comtypes / 系统没有语音引擎 / 不是 Windows / 文件不存在 → 老实报失败，不崩、不谎报。
"""

import base64
import os
import queue
import shutil
import subprocess
import threading
import time

import volume_actions

try:
    import comtypes
except Exception:                                        # 没装 comtypes
    comtypes = None

GAP_S = 0.05                       # 查打断 / 读播放器状态的间隔
PLAY_MAX_S = 600                   # 兜底：再长也不超过 10 分钟
CREATE_NO_WINDOW = 0x08000000
LOG_TEXT_MAX = 20                  # 日志里文本最长留几个字

# SAPI 的朗读标志（SpeechVoiceSpeakFlags）
SVSF_ASYNC = 1                     # 异步朗读（边读边查打断）
SVSF_PURGE = 2                     # 清掉还没读的（打断用）

_logger = print


def set_logger(fn):
    global _logger
    _logger = fn


def log(msg):
    try:
        _logger(msg)
    except Exception:
        pass


# ----------------------------- 小工具 -----------------------------


def _init_com():
    """SAPI 是 COM 组件：**每个用它的线程都要先初始化**（不然报 -2147221008）。"""
    if comtypes is None:
        return False
    try:
        comtypes.CoInitialize()
        return True
    except Exception:
        return True                       # 已经初始化过也算成功


def _cancelled(cancel):
    if cancel is None:
        return False
    try:
        if callable(cancel):
            return bool(cancel())
        return bool(cancel.is_set())
    except Exception:
        return False


def _short(text):
    t = str(text or "").strip().replace("\n", " ")
    return (t[:LOG_TEXT_MAX] + "…") if len(t) > LOG_TEXT_MAX else t


def _ps_exe():
    """系统自带 PowerShell（放音 / 通知都用它）。"""
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    p = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.isfile(p):
        return p
    return shutil.which("powershell.exe") or "powershell.exe"


# ----------------------------- 提示音：系统播放器 -----------------------------

# 交给系统播放器去放（能放什么由系统解码器决定，不看扩展名）。
# 逐 100ms 报一次状态：'PLAY' = 真的开始放了；'END' = 放完了；'ERR=' = 放不了。
PLAY_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[void][Windows.Media.Playback.MediaPlayer, Windows.Media, ContentType=WindowsRuntime]
[void][Windows.Media.Core.MediaSource, Windows.Media.Core, ContentType=WindowsRuntime]
try {
  $p = New-Object Windows.Media.Playback.MediaPlayer
  $p.Volume = [double]$env:OPB_VOL
  $p.Source = [Windows.Media.Core.MediaSource]::CreateFromUri(
      [uri]((Get-Item -LiteralPath $env:OPB_AUDIO).FullName))
  $p.Play()
} catch {
  Write-Output ('ERR=' + $_.Exception.Message)
  exit 3
}
Write-Output 'PLAY'
$played = $false
for ($i = 0; $i -lt 36000; $i++) {
  Start-Sleep -Milliseconds 100
  $st = [int]$p.PlaybackSession.PlaybackState
  try { if ($p.PlaybackSession.Position.TotalMilliseconds -gt 0) { $played = $true } } catch { }
  if ($st -eq 3) { $played = $true }                       # 3 = 正在播
  if ($played -and ($st -eq 4 -or $st -eq 0)) { Write-Output 'END'; break }
  if (-not $played -and $i -gt 80) {
    Write-Output 'ERR=等了 8 秒还没开始播放（系统解不了这个文件？）'
    break
  }
}
$p.Dispose()
"""


def _pump(stream, sink):
    """把子进程的输出读进队列（读线程不许堵住主循环）。"""
    try:
        for line in stream:
            sink.put(line)
    except Exception:
        pass
    finally:
        sink.put(None)                       # 收尾标记


def _play_cmd(path, volume_0_100):
    """拼出交给系统播放器的命令 + 环境变量（自检用，跨平台也能看）。"""
    enc = base64.b64encode(PLAY_PS.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, OPB_AUDIO=os.path.abspath(path),
               OPB_VOL="%.4f" % (float(volume_0_100) / 100.0))
    cmd = [_ps_exe(), "-NoProfile", "-NonInteractive",
           "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc]
    return cmd, env


def play_file(path, volume=100, cancel=None, logger=None):
    """放一个提示音文件（同步，放完才返回）。返回 (ok, 说明)。

    * 格式由**系统解码器**决定（mp3 / m4a / wav / flac… 都行），不看扩展名。
    * 音量 = 播放器自己的音量（0-100），**不动系统总音量、不动别的程序**。
    * 播放期间可被打断（`cancel` 是 Event 或返回 bool 的函数）：立刻停。
    """
    say = logger or log
    p = str(path or "").strip()
    name = os.path.basename(p)
    if not p:
        return False, "没有音频文件"
    if os.name != "nt":
        return False, "非 Windows 环境，放音用不了"
    if not os.path.isfile(p):
        return False, "音频文件不存在：%s" % p
    ok, lv = volume_actions.parse_level(volume)
    if not ok:
        return False, lv

    cmd, env = _play_cmd(p, lv)
    kw = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
              encoding="utf-8", errors="replace", env=env)
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    pr = None
    try:
        pr = subprocess.Popen(cmd, **kw)                          # noqa: S603
    except Exception as e:
        return False, "起不了系统播放器：%r" % (e,)

    lines = queue.Queue()
    threading.Thread(target=_pump, args=(pr.stdout, lines), daemon=True,
                     name="play-read").start()

    started = False
    why = ""
    deadline = time.monotonic() + PLAY_MAX_S
    try:
        while True:
            if _cancelled(cancel):
                return False, "播放被打断：%s" % name
            try:
                line = lines.get(timeout=GAP_S)
            except queue.Empty:
                line = ""
            if line is None:                                      # 输出结束
                break
            line = (line or "").strip()
            if line == "PLAY":
                started = True
            elif line == "END":
                break
            elif line.startswith("ERR="):
                why = line[4:].strip()
                break
            elif line and not started:
                why = why or line
            if time.monotonic() > deadline:
                return False, "放音超时（%s），已停止" % name
    finally:
        _kill(pr)

    if why and not started:
        return False, "放不了这个音频文件：%s（%s）" % (name, why)
    if not started:
        return False, "没能开始播放：%s" % name
    if why:
        return False, "播放中断：%s（%s）" % (name, why)
    return True, "已播放 %s（音量 %d）" % (name, lv)


def _kill(pr):
    """收掉播放器进程（声音随进程一起停）。"""
    if pr is None:
        return
    try:
        if pr.poll() is None:
            pr.kill()
        pr.wait(timeout=3)
    except Exception:
        pass
    try:
        if pr.stdout is not None:
            pr.stdout.close()
    except Exception:
        pass


# ----------------------------- 朗读：系统语音引擎 -----------------------------


def speak_text(text, volume=100, cancel=None, logger=None):
    """用系统语音引擎朗读（同步，读完才返回）。返回 (ok, 说明)。

    音量 = 引擎自己的音量（0-100），和提示音音量各管各的。
    """
    text = str(text or "").strip()
    if not text:
        return False, "没有要播报的文字"
    if comtypes is None:
        return False, "没装 comtypes，用不了系统语音引擎"
    if os.name != "nt":
        return False, "非 Windows 环境，语音播报用不了"
    ok, lv = volume_actions.parse_level(volume)
    if not ok:
        return False, lv
    try:
        from comtypes import client as _client          # 注意：别 `import comtypes.client`
        _init_com()
        voice = _client.CreateObject("SAPI.SpVoice")
        voice.Volume = int(lv)
        voice.Speak(text, SVSF_ASYNC)
        while True:
            if _cancelled(cancel):
                voice.Speak("", SVSF_ASYNC | SVSF_PURGE)     # 立刻停
                return False, "朗读被打断：%s" % _short(text)
            if voice.WaitUntilDone(50):                      # 每 50ms 回来看一眼
                break
        return True, "已朗读：%s（音量 %d）" % (_short(text), lv)
    except Exception as e:
        return False, "朗读失败：%r" % (e,)


# ----------------------------- 队列后端 -----------------------------


class SpeechBackend(object):
    """一条队列 + 一条播放线程。死亡和复活共用它。"""

    def __init__(self, logger=None, speaker=None, player=None):
        self.log = logger if logger is not None else log
        self.q = queue.Queue()
        self.speaker = speaker or speak_text            # 可替换（测试）
        self.player = player or play_file               # 可替换（测试）
        self._thread = None
        self._started = False
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self.lock = self._lock
        self.done = 0                                   # 播完的条数（测试/诊断用）

    # ---------------- 生命周期 ----------------

    def start(self):
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="speech")
        self._thread.start()

    def _worker(self):
        _init_com()
        while True:
            job = self.q.get()
            if job is None:                              # 收队
                return
            if callable(job):
                try:                                     # wait_idle 的"队列空了"标记
                    job()
                except Exception:
                    pass
                continue
            text, path, fvol, tvol = job
            try:
                with self._lock:
                    self._cancel = threading.Event()
                    cancel = self._cancel
                self._play_one(text, path, fvol, tvol, cancel)
            except Exception as e:
                self.log("⚠ 播报出错：%r" % (e,))

    def stop(self, wait=3.0):
        """收队：清空排队 + 停当前 + 结束线程。"""
        self.purge("程序退出")
        if self._started:
            self.q.put(None)
            t = self._thread
            if t is not None:
                t.join(timeout=wait)
        self._started = False

    def wait_idle(self, timeout=5.0):
        """等队列跑完（自检 / 测试用）。"""
        if not self._started:
            return True
        done = threading.Event()
        self.q.put(done.set)
        return done.wait(timeout)

    # ---------------- 对外 ----------------

    def pending(self):
        """还没轮到播的条数。"""
        return sum(1 for j in list(self.q.queue) if isinstance(j, tuple))

    def say(self, text="", file="", file_volume=100, tts_volume=100):
        """入队一条播报。返回 (ok, 说明) —— 是"已排进队列"，不是"已播完"。"""
        text = str(text or "").strip()
        path = str(file or "").strip()
        if not text and not path:
            return False, "既没填播报文本，也没选提示音文件"
        fvol, tvol = 100, 100
        if path:                                     # 只有真的会用到才校验那一项
            ok, fvol = volume_actions.parse_level(file_volume)
            if not ok:
                return False, "提示音音量：%s" % fvol
        if text:
            ok, tvol = volume_actions.parse_level(tts_volume)
            if not ok:
                return False, "语音音量：%s" % tvol
        if path and not os.path.isfile(path):
            return False, "提示音文件不存在：%s" % path
        self.start()
        self.q.put((text, path, fvol, tvol))
        n = self.pending() - 1
        what = "提示音+文本" if (text and path) else ("文本" if text else "提示音")
        if n > 0:
            return True, "已排进播报队列（%s，前面还有 %d 条）" % (what, n)
        return True, "已排进播报队列（%s）" % what

    def purge(self, why=""):
        """立刻打断 + 清空排队（用户要求）。返回丢掉的条数。"""
        with self._lock:
            self._cancel.set()
        dropped = 0
        keep = []
        while True:
            try:
                job = self.q.get_nowait()
            except queue.Empty:
                break
            if job is None or callable(job):             # 收队信号 / wait_idle 标记：留着
                keep.append(job)
                continue
            dropped += 1
        for job in keep:                                 # 放回队尾（顺序无所谓，只影响"谁先醒"）
            self.q.put(job)
        if dropped:
            self.log("[say] %s：丢掉 %d 条还没播的播报" % (why or "被打断", dropped))
        return dropped

    # ---------------- 内部 ----------------

    def _play_one(self, text, path, fvol, tvol, cancel):
        if _cancelled(cancel):
            return
        if path:
            ok, msg = self.player(path, fvol, cancel, self.log)
            self.log(("[say] %s" % msg) if ok else ("⚠ [say] %s" % msg))
            if not ok and _cancelled(cancel):
                return
        if _cancelled(cancel):
            return
        if text:
            ok, msg = self.speaker(text, tvol, cancel, self.log)
            self.log(("[say] %s" % msg) if ok else ("⚠ [say] %s" % msg))
        if not _cancelled(cancel):
            with self._lock:
                self.done += 1
