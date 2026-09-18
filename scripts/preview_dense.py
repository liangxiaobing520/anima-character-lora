#!/usr/bin/env python3
"""密抽样预检：每个候选源均匀抽 6 帧排成一行，人工判定该源是否整源可用。
只读，不做任何修改。
"""
import os
import glob
from PIL import Image, ImageDraw

V = "/home/xiaozeng/lora_train/yanruyan_video"
F2, FA = f"{V}/frames2", f"{V}/frames_all"
ANIM = ["BV1kyiKBVEaF", "BV1cvP8z1Egz", "BV1Vnec67ERv", "BV1gdj46BEHz", "BV1BRYB6RE5h"]

src = {}
for d in sorted(glob.glob(f"{F2}/*/")):
    n = os.path.basename(d.rstrip("/"))
    if "." in n or "*" in n:
        continue
    f = sorted(glob.glob(d + "*.jpg"))
    if f:
        src[n] = f
for bv in ANIM:
    f = sorted(glob.glob(f"{FA}/{bv}_*.jpg"))
    if f:
        src[bv] = f

NPICK, CELL, LABW = 6, 150, 130
names = sorted(src)
sheet = Image.new("RGB", (LABW + CELL * NPICK, CELL * len(names)), (20, 20, 24))
dr = ImageDraw.Draw(sheet)

for r, name in enumerate(names):
    files = src[name]
    n = len(files)
    dr.text((4, r * CELL + 6), name, fill=(255, 255, 0))
    dr.text((4, r * CELL + 22), f"{n} frames", fill=(160, 160, 170))
    for c in range(NPICK):
        idx = min(int(n * (c + 0.5) / NPICK), n - 1)
        im = Image.open(files[idx]).convert("RGB")
        w, h = im.size
        s = min(CELL / w, CELL / h)
        im = im.resize((max(1, int(w * s)), max(1, int(h * s))))
        sheet.paste(im, (LABW + c * CELL + (CELL - im.width) // 2,
                         r * CELL + (CELL - im.height) // 2))

out = "/tmp/dense_preview.png"
sheet.save(out)
print(f"saved {out} {sheet.size}  sources={len(names)}, {NPICK} frames each")
