# -*- coding: utf-8 -*-
"""
生成打包用的图标 `assets/app.ico`（构建时由 build.bat 调用，需要 Pillow）。
配色与程序里 QPainter 现画的托盘图标一致：绿点 = 存活。
"""

import os
import sys


def build_images():
    from PIL import Image, ImageDraw

    bg = "#2b2f36"
    ring = "#11141a"
    dot = "#2ecc71"
    sizes = (16, 24, 32, 48, 64, 128, 256)
    imgs = []
    for s in sizes:
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        m = max(1, s // 16)
        d.ellipse((m // 2, m // 2, s - 1 - m // 2, s - 1 - m // 2),
                  fill=bg, outline=ring, width=m)
        pad = int(s * 0.22)
        d.ellipse((pad, pad, s - 1 - pad, s - 1 - pad), fill=dot)
        imgs.append(img)
    return imgs


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "assets")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app.ico")
    try:
        imgs = build_images()
    except ImportError:
        print("需要 Pillow 才能生成图标：python -m pip install pillow")
        return 1
    imgs[-1].save(out, format="ICO", sizes=[(i.width, i.height) for i in imgs],
                  append_images=imgs)
    print("已生成图标：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
