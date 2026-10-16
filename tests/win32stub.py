# -*- coding: utf-8 -*-
"""最小 Win32 桩：让 `scpsl_state.py` / `win32_window.py` 能在 Linux 上被 import。

只做两件事：给 `ctypes` 补上 `WinDLL` / `WINFUNCTYPE`（Linux 上没有）。
所有 API 调用都返回 0 —— 测试里要用的行为请自己 monkeypatch 具体函数。
"""

import ctypes


class _FakeFunc(object):
    def __init__(self, name):
        self.name = name
        self.argtypes = None
        self.restype = None

    def __call__(self, *a, **k):
        return 0


class _FakeDLL(object):
    def __init__(self, *a, **k):
        self.dll_args = a

    def __getattr__(self, name):
        f = _FakeFunc(name)
        self.__dict__[name] = f          # 缓存，避免每次新建
        return f


class _FakeCallbackProto(object):
    """`ctypes.WINFUNCTYPE(...)` 的替身：实例化时直接把回调原样返回。"""

    def __init__(self, *types):
        self.types = types

    def __call__(self, fn):
        return fn


def install():
    if not hasattr(ctypes, "WinDLL"):
        ctypes.WinDLL = _FakeDLL
    if not hasattr(ctypes, "windll"):
        ctypes.windll = _FakeDLL()
    if not hasattr(ctypes, "WinError"):
        ctypes.WinError = lambda *a, **k: OSError("WinError(stub)")
    if not hasattr(ctypes, "WINFUNCTYPE"):
        # 必须是**真的函数指针类型**：它要能放进 ctypes.Structure 的 _fields_
        ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE
    return ctypes
