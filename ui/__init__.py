# -*- coding: utf-8 -*-
"""PySide6 界面层：只负责「显示」+「调用 appcore」，业务逻辑一律在 appcore/operations 里。

| 文件 | 作用 |
|---|---|
| `bridge.py`      | Qt 信号桥（后台线程 → 界面线程） |
| `icons.py`       | 用 QPainter 现画的托盘/窗口图标（绿=存活 / 红=死亡） |
| `util.py`        | 打开文件/文件夹、消息弹窗等小工具 |
| `page_log.py`    | 日志页（过滤、跟随、清空、导出） |
| `page_features.py` | 功能配置页（死亡后 / 复活后 两个列表） |
| `op_dialog.py`   | 「添加操作」弹窗 |
| `page_settings.py` | 设置页（自启动 / Player.log / 日志文件 / 配置文件位置） |
| `page_about.py`  | 关于页（版本、作者、用法、精简日志） |
| `main_window.py` | 主窗口（左侧导航 + 右侧页面栈） |
| `tray.py`        | 托盘图标与菜单 |
"""
