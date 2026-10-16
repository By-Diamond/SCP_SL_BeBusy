# -*- coding: utf-8 -*-
"""打开文件 / 文件夹、简易提示（跨平台，Windows 上走系统默认程序）。"""

import os
import subprocess


def open_path(path, logger=None):
    """用系统默认方式打开文件或文件夹。返回 (ok, 说明)。"""
    if not path:
        return False, "路径为空"
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False, "路径不存在：%s" % path
    try:
        if os.name == "nt":
            os.startfile(path)                                  # noqa: S606
        elif sys_platform() == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, "已打开 %s" % path
    except Exception as e:
        return False, "打开失败：%r" % (e,)


def open_folder_of(path, logger=None):
    """打开某个文件所在的文件夹。"""
    if not path:
        return False, "路径为空"
    folder = os.path.dirname(os.path.abspath(path)) or "."
    return open_path(folder, logger)


def sys_platform():
    import sys
    return sys.platform


# ----------------------------- 状态栏文字 -----------------------------

MEDIA_TIP = ("程序只能记住自己最后发过的媒体键（系统不给普通程序查询接口）："
             "你手动按过播放/暂停后，用托盘「手动」项对一下即可。")


def status_texts(alive, plog_found, media):
    """状态栏三段文字（纯函数，方便测）。

    竖线只在「段与段之间」，最后一段**不封口**；竖线前留两个空格，不贴着文字。
    """
    return {
        "state": "状态：%s  |" % ("存活" if alive else "死亡·观察者"),
        "media": "媒体：%s |" % media,
        "plog": "Player.log：%s" % ("已找到" if plog_found else "未找到"),
    }


def human_size(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "?"
