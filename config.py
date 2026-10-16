# -*- coding: utf-8 -*-
"""
配置系统（无界面）：settings.json 读写 + 位置可迁移 + 路径自动识别
==================================================================

设计
----
* **配置文件的位置**由一个很小的「位置指针」记住：
  默认 `<默认配置目录>\\config_location.txt`，里面一行就是 settings.json 的绝对路径。
  查找顺序：① 指针指向的文件 → ② 默认配置目录里的 settings.json → ③ 内置默认值。
* 改配置位置 = 把当前配置写到新路径 + 更新位置指针（**旧文件保留不删**，只是不再使用）。
* 路径支持 `%USERPROFILE%` / `%APPDATA%` 这类环境变量，读写时自动展开。
* 所有写入都是「先写临时文件，再原子替换」——断电/崩溃不会留下半个坏文件。
* 默认配置目录：程序目录可写就用程序目录（便携），不可写（如装在 Program Files）退回
  `%APPDATA%\\SCP_SL_BeBusy`。
* **改名迁移**：旧版本叫 `SCPSL_AutoAudio`，首次运行会把旧目录里的配置/日志/数据**复制**过来
  （只复制、不删除旧文件），见 `migrate_from_legacy()`。

settings.json 内容
------------------
```json
{
  "version": "0.1.0",
  "player_log": "",                 // 空 = 自动识别
  "log_file": "",                   // 空 = 与配置文件同目录的 SCP_SL_BeBusy.log
  "log_max_mb": 5,
  "log_backups": 2,
  "autostart": false,
  "open_url_default": "https://www.bilibili.com",
  "death_ops": [{"type": "media_play",  "params": {}}],
  "alive_ops": [{"type": "media_pause", "params": {}}],
  "ui": {"page": 0, "log_filter": "key", "follow_log": true}
}
```
"""

import glob
import json
import os
import re
import shutil
import sys
import tempfile

_ENV_PERCENT = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")

# ----------------------------- 程序基本信息（打包/关于页共用） -----------------------------

APP_NAME = "SCP_SL_BeBusy"
APP_TITLE = "SCP:SL BeBusy"
VERSION = "0.1.0"
AUTHOR = "By Diamond"
DESCRIPTION = "自动识别玩家存活/死亡 并执行相关操作，未修改游戏本体，不是作弊行为"
GAME_NAME = "SCPSL"

LOCATION_FILE = "config_location.txt"
DEFAULT_LOG_NAME = "SCP_SL_BeBusy.log"

# 旧名字（改名前的 SCP:SL BeBusy = SCPSL 自动音频）。首次运行会把旧目录里的东西复制过来。
LEGACY_APP_NAMES = ("SCPSL_AutoAudio",)
LEGACY_LOG_NAME = "SCPSL_AutoAudio.log"

DEFAULTS = {
    "version": VERSION,
    "player_log": "",                 # 空 = 自动识别
    "log_file": "",                   # 空 = <配置目录>/<DEFAULT_LOG_NAME>
    "log_max_mb": 5,
    "log_backups": 2,
    "autostart": False,
    "open_url_default": "https://www.bilibili.com",
    "death_ops": [{"type": "media_play", "params": {}}],
    "alive_ops": [{"type": "media_pause", "params": {}}],
    "ui": {"page": 0, "log_filter": "key", "follow_log": True},
}


# ----------------------------- 路径工具 -----------------------------


def is_frozen():
    """是否是 PyInstaller 打出来的 exe。"""
    return bool(getattr(sys, "frozen", False))


def app_dir():
    """程序所在目录（源码运行 = 项目目录；exe 运行 = exe 所在目录）。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def expand(path):
    """展开环境变量与 ~（`%USERPROFILE%` 和 `$HOME` 两种写法都认）。"""
    if not path:
        return path
    path = _ENV_PERCENT.sub(lambda m: os.environ.get(m.group(1), m.group(0)), path)
    return os.path.expanduser(os.path.expandvars(path))


def abspath(path):
    return os.path.abspath(expand(path))


def user_home():
    home = os.environ.get("USERPROFILE")
    if not home:
        home = os.environ.get("HOME") or os.path.expanduser("~")
    return home


def appdata_dir(name=None):
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.join(user_home(), "AppData", "Roaming")
    return os.path.join(base, name or APP_NAME)


def legacy_appdata_dirs():
    """旧名字对应的目录列表（改名前的 %APPDATA%\\SCPSL_AutoAudio 等）。"""
    return [appdata_dir(n) for n in LEGACY_APP_NAMES]


def migrate_from_legacy():
    """改名迁移：把旧目录里的配置/日志/数据**复制**到新目录（只复制，绝不删旧文件）。

    只在「新目录里还没有 settings.json」且「确实在用 %APPDATA% 目录」时动手。
    返回说明文字（没做事则返回空串）。
    """
    dest = appdata_dir()
    if os.path.normcase(dest) != os.path.normcase(default_config_dir()):
        return ""                                  # 用的是程序目录（便携）→ 不用迁移
    if os.path.exists(os.path.join(dest, "settings.json")):
        return ""                                  # 新目录已有配置 → 不动
    moved = []
    for old in legacy_appdata_dirs():
        if not os.path.isdir(old):
            continue
        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as e:
            return "迁移失败（建目录）：%r" % (e,)
        # settings.json / 位置指针 / 死亡记录 + 旧日志（含轮转备份）
        names = ["settings.json", LOCATION_FILE, "state_log.csv"]
        try:
            names += [n for n in os.listdir(old) if n.startswith(LEGACY_LOG_NAME)]
        except Exception:
            pass
        for fn in names:
            src = os.path.join(old, fn)
            if not os.path.isfile(src):
                continue
            # 旧日志改名成新日志名，保持日志连续
            dst_name = DEFAULT_LOG_NAME + fn[len(LEGACY_LOG_NAME):] \
                if fn.startswith(LEGACY_LOG_NAME) else fn
            dst = os.path.join(dest, dst_name)
            if os.path.exists(dst):
                continue
            try:
                shutil.copy2(src, dst)
                moved.append(dst_name)
            except Exception:
                pass
    if not moved:
        return ""
    return "已从旧目录迁移：%s（旧文件保留）" % "、".join(moved)


def is_writable_dir(d):
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_probe.tmp")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


_WRITABLE_CACHE = {}


def default_config_dir():
    """默认配置目录：程序目录（可写）→ %APPDATA%\\SCP_SL_BeBusy。"""
    d = app_dir()
    key = os.path.normcase(d)
    if key not in _WRITABLE_CACHE:
        _WRITABLE_CACHE[key] = is_writable_dir(d)
    if _WRITABLE_CACHE[key]:
        return d
    return appdata_dir()


def default_settings_path():
    return os.path.join(default_config_dir(), "settings.json")


def location_pointer_path():
    return os.path.join(default_config_dir(), LOCATION_FILE)


def resolve_settings_path():
    """按「指针 → 默认位置」顺序找出该读哪个 settings.json。"""
    ptr = location_pointer_path()
    if os.path.isfile(ptr):
        try:
            with open(ptr, "r", encoding="utf-8") as f:
                p = f.read().strip()
            if p:
                return abspath(p)
        except Exception:
            pass
    return default_settings_path()


def set_location_pointer(path):
    """写位置指针；失败返回 (False, 原因)。"""
    ptr = location_pointer_path()
    try:
        os.makedirs(os.path.dirname(ptr) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".loc-", suffix=".tmp",
                                   dir=os.path.dirname(ptr) or ".")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(abspath(path) + "\n")
        os.replace(tmp, ptr)
        return True, ptr
    except Exception as e:
        return False, "位置指针写入失败：%r" % (e,)


def clear_location_pointer():
    """删掉指针 = 回到默认位置。"""
    try:
        os.remove(location_pointer_path())
        return True, "已恢复默认配置位置"
    except FileNotFoundError:
        return True, "本来就是默认位置"
    except Exception as e:
        return False, "删除位置指针失败：%r" % (e,)


# ----------------------------- Player.log 自动识别 -----------------------------


def default_player_log():
    """游戏日志的规范位置（不一定存在）。"""
    return os.path.join(user_home(), "AppData", "LocalLow", "Northwood",
                        GAME_NAME, "Player.log")


def player_log_candidates():
    """候选路径：规范位置 + LocalLow 下扫到的其它 Player.log（带 scpsl 字样的优先）。"""
    cands = [default_player_log()]
    local_low = os.path.join(user_home(), "AppData", "LocalLow")
    if os.path.isdir(local_low):
        extra = [p for p in glob.glob(os.path.join(local_low, "*", "*", "Player.log"))
                 if GAME_NAME.lower() in p.lower()]
        extra.sort()
        cands.extend(extra)
    seen, out = set(), []
    for c in cands:
        k = os.path.normcase(c)
        if k and k not in seen:
            seen.add(k)
            out.append(c)
    return out


def autodetect_player_log():
    """自动识别：返回 (路径, 是否存在, 说明)。"""
    cands = player_log_candidates()
    for p in cands:
        if os.path.isfile(p):
            return p, True, "自动识别（已找到 %s）" % p
    if cands:
        return cands[0], False, "自动识别（用默认位置，文件当前不存在）"
    return "", False, "自动识别失败，请手动指定 Player.log 位置"


def effective_player_log(cfg):
    """运行时真正用的 Player.log：配置有就用配置，否则自动识别。"""
    p = (cfg.get("player_log") or "").strip()
    if p:
        return abspath(p), os.path.isfile(abspath(p))
    return autodetect_player_log()[:2]


def effective_log_file(cfg):
    """运行时日志文件路径。"""
    p = (cfg.get("log_file") or "").strip()
    if p:
        return abspath(p)
    return os.path.join(os.path.dirname(cfg.path) or ".", DEFAULT_LOG_NAME)


# ----------------------------- 配置对象 -----------------------------


def _deep_defaults():
    return json.loads(json.dumps(DEFAULTS))


class Config:
    """settings.json 的读写与迁移。所有 set 之后记得 `save()`。"""

    def __init__(self, path=None):
        self.last_error = ""
        self.path = abspath(path) if path else resolve_settings_path()
        self.data = _deep_defaults()
        self.loaded = False
        self.load()

    # ---- 读 ----

    def load(self):
        self.data = _deep_defaults()
        self.loaded = False
        if not os.path.isfile(self.path):
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("配置根节点必须是 JSON 对象")
            for k, v in raw.items():          # 未知键保留（向后兼容）
                self.data[k] = v
            self.loaded = True
            return True
        except Exception as e:
            self.last_error = "配置读取失败（本次用默认值）：%r" % (e,)
            return False

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        return value

    def update(self, mapping):
        self.data.update(mapping)

    # ---- 写 ----

    def save(self, path=None):
        target = abspath(path) if path else self.path
        d = os.path.dirname(target) or "."
        tmp = None
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=d)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, target)
            self.path = target
            self.loaded = True
            return target
        except Exception as e:
            self.last_error = "配置保存失败：%r" % (e,)
            if tmp:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            return ""

    def move_to(self, new_path):
        """迁移配置到新位置（写过去 + 更新指针；旧文件保留）。返回 (新路径, 说明)。

        同时把「日志文件」也一起搬过去（如果日志用的是默认位置）。
        """
        old = self.path
        new_path = abspath(new_path)
        saved = self.save(new_path)
        if not saved:
            return "", self.last_error
        ok, detail = set_location_pointer(saved)
        if not ok:
            return saved, "配置已写到 %s，但%s" % (saved, detail)
        if os.path.normcase(saved) == os.path.normcase(old):
            return saved, "配置位置未变化（仍是 %s）" % saved
        return saved, "配置已迁移到 %s；旧文件 %s 保留（可自行删除）" % (saved, old)

    def reset_location(self):
        """回到默认位置：配置写到默认路径并删掉指针。"""
        default = default_settings_path()
        saved = self.save(default)
        clear_location_pointer()
        return saved or default, "配置已回到默认位置：%s" % (saved or default)

    # ---- 便捷视图 ----

    def ops(self, which):
        """which = "death" / "alive"；返回列表（深拷贝，避免调用方改到内部）。"""
        key = "death_ops" if which == "death" else "alive_ops"
        v = self.get(key)
        return json.loads(json.dumps(v if isinstance(v, list) else []))

    def set_ops(self, which, items):
        key = "death_ops" if which == "death" else "alive_ops"
        self.set(key, json.loads(json.dumps(items)))
