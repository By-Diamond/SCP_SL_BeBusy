# -*- coding: utf-8 -*-
"""
动作列表的规则（纯数据，无界面）—— 添加 / 删除 / 上移下移 / 查重
==============================================================

规则（用户定义）：
* **每个框里，同一个操作最多一条** —— 因为「媒体播放」不能播放两次；
* 例外：`OpSpec.allow_multiple = True` 的操作可以多条（当前只有「打开网页」，
  用户可以放多个不同网址）；
* 未来新增的操作只要在注册表里声明 `allow_multiple`，这里和界面自动生效。

两个框是独立的：同一个操作**允许**同时出现在「死亡后」和「复活后」。
"""

import operations


class OpList:
    """一个动作列表（死亡后 / 复活后）的规则门面。"""

    def __init__(self, items=None, label=""):
        self.label = label
        self.items = [operations.normalize_item(i) for i in (items or [])]
        self.items = [i for i in self.items if i]

    # ---------------- 查询 ----------------

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def types(self):
        return [i["type"] for i in self.items]

    def count_of(self, op_type):
        return sum(1 for i in self.items if i["type"] == op_type)

    def can_add(self, op_type):
        """能不能再放一条。返回 (ok, 原因)。"""
        spec = operations.get_spec(op_type)
        if spec is None:
            return False, "未知操作类型：%s" % op_type
        if spec.allow_multiple:
            return True, ""
        if self.count_of(op_type) > 0:
            return False, "「%s」已经在列表里了（同一个框里不能重复）" % spec.name
        return True, ""

    def describe(self):
        return [operations.describe_item(i) for i in self.items]

    def to_config(self):
        import json
        return json.loads(json.dumps(self.items))

    # ---------------- 增删改 ----------------

    def add(self, op_type, **params):
        ok, why = self.can_add(op_type)
        if not ok:
            return False, why
        item = operations.new_item(op_type, **params)
        if item is None:
            return False, "未知操作类型：%s" % op_type
        self.items.append(item)
        return True, "已添加：%s" % operations.describe_item(item)

    def add_item(self, item):
        item = operations.normalize_item(item)
        if item is None:
            return False, "条目无效"
        ok, why = self.can_add(item["type"])
        if not ok:
            return False, why
        self.items.append(item)
        return True, "已添加：%s" % operations.describe_item(item)

    def set_params(self, index, **params):
        """改某一条的参数（例如「打开网页」的网址）。"""
        if not (0 <= index < len(self.items)):
            return False, "下标越界"
        spec = operations.get_spec(self.items[index]["type"])
        if spec is None:
            return False, "未知操作类型"
        p = dict(spec.defaults())
        p.update(self.items[index].get("params") or {})
        p.update(params)
        self.items[index]["params"] = p
        return True, "已修改：%s" % operations.describe_item(self.items[index])

    def remove(self, index):
        if not (0 <= index < len(self.items)):
            return False, "下标越界"
        gone = self.items.pop(index)
        return True, "已删除：%s" % operations.describe_item(gone)

    def move(self, index, delta):
        """上移(-1)/下移(+1)。"""
        j = index + delta
        if not (0 <= index < len(self.items)) or not (0 <= j < len(self.items)):
            return False, "到头了"
        self.items[index], self.items[j] = self.items[j], self.items[index]
        return True, "已移动"

    def clear(self):
        n = len(self.items)
        self.items = []
        return n
