#!/usr/bin/env python3
"""单源全帧拼图（带序号），用于精确剔除双人同框帧。只读。"""
import glob
from PIL import Image, ImageDraw

D = "/home/xiaozeng/lora_train/yanruyan_video/frames_all"
BV = "BV1cvP8z1Egz"
files = sorted(glob.glob(f"{D}/{BV}_*.jpg"))

CELL, COLS = 190, 6
rows = (len(files) + COLS - 1) // COLS
sheet = Image.new("RGB", (CELL * COLS, CELL * rows), (16, 16, 20))
dr = ImageDraw.Draw(sheet)
for i, p in enumerate(files):
    im = Image.open(p).convert("RGB")
    im.thumbnail((CELL, CELL), Image.LANCZOS)
    cx, cy = i % COLS, i // COLS
    x = cx * CELL + (CELL - im.width) // 2
    y = cy * CELL + (CELL - im.height) // 2
    sheet.paste(im, (x, y))
    dr.rectangle([cx * CELL, cy * CELL, cx * CELL + 40, cy * CELL + 12], fill=(0, 0, 0))
    dr.text((cx * CELL + 3, cy * CELL + 2), f"#{i+1}", fill=(255, 230, 60))

sheet.save("/tmp/bv1cvp8.png")
print(f"{len(files)} frames -> /tmp/bv1cvp8.png {sheet.size}")
