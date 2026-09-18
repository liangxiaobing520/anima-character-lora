#!/usr/bin/env python3
"""混合源分段预检：按时间顺序均匀抽 16 帧并标注序号，用于人工判定可保留的镜头区间。
只读，不改动任何帧。
"""
import glob
import os
from PIL import Image, ImageDraw

V = "/home/xiaozeng/lora_train/yanruyan_video"

MIXED = [
    ("BV1V16pBpEDn", f"{V}/frames2/BV1V16pBpEDn", "前段燕如嫣/后段男性"),
    ("BV1acZEBmEUx", f"{V}/frames2/BV1acZEBmEUx", "女性+男性交替"),
    ("BV1cvP8z1Egz", f"{V}/frames_all", "燕如嫣+男性"),
    ("BV1BDArzgEQP", f"{V}/frames2/BV1BDArzgEQP", "整部剧集混剪"),
]

NPICK, COLS, CELL = 16, 8, 120
rows_total = len(MIXED) * (NPICK // COLS)
sheet = Image.new("RGB", (CELL * COLS, CELL * rows_total), (16, 16, 20))
dr = ImageDraw.Draw(sheet)

r = 0
for bv, d, note in MIXED:
    files = sorted(glob.glob(f"{d}/{bv}_*.jpg"))
    n = len(files)
    print(f"{bv}: {n} 帧  ({note})")
    for c in range(NPICK):
        idx = min(int(n * (c + 0.5) / NPICK), n - 1)
        im = Image.open(files[idx]).convert("RGB")
        t = im.copy()
        t.thumbnail((CELL, CELL), Image.LANCZOS)
        x = c * CELL + (CELL - t.width) // 2
        y = r * CELL + (CELL - t.height) // 2
        sheet.paste(t, (x, y))
        # 标注帧序号
        dr.rectangle([c * CELL, r * CELL, c * CELL + 58, r * CELL + 11], fill=(0, 0, 0))
        dr.text((c * CELL + 2, r * CELL + 1), f"{idx+1}/{n}", fill=(255, 230, 60))
        if c == 0:
            dr.rectangle([0, r * CELL + CELL - 12, 96, r * CELL + CELL], fill=(0, 0, 0))
            dr.text((2, r * CELL + CELL - 12), bv[:13], fill=(120, 255, 120))
    r += NPICK // COLS

sheet.save("/tmp/mixed_preview.png")
print(f"\n拼图 -> /tmp/mixed_preview.png {sheet.size}")
