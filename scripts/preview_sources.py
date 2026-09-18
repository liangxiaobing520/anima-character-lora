#!/usr/bin/env python3
"""样张预检：把待用的所有帧源各抽一帧拼成一张图，人工确认
  ①画面是真动画燕如嫣（不是真人/AI静图）②字幕位置（决定裁切比例）。
只读，不改任何素材。
"""
import os
import glob
from PIL import Image, ImageDraw

V = "/home/xiaozeng/lora_train/yanruyan_video"
F2, FA = f"{V}/frames2", f"{V}/frames_all"

# 底部裁切比例（现状假设，待预览图确认）
CROP = {
    "BV1kyiKBVEaF": 0.12,
    "BV13qmEBoEfL": 0.10, "BV1ZNSFBXEoo": 0.10, "BV1BDArzgEQP": 0.10,
    "BV1V16pBpEDn": 0.10, "BV1acZEBmEUx": 0.10,
}
# frames_all 里保留的 5 个动画源
ANIM = ["BV1kyiKBVEaF", "BV1cvP8z1Egz", "BV1Vnec67ERv", "BV1gdj46BEHz", "BV1BRYB6RE5h"]

src = {}
# frames2：只取无 .f 后缀目录（带 .fNNNNN 的已证实是同一视频重复抽帧）
for d in sorted(glob.glob(f"{F2}/*/")):
    name = os.path.basename(d.rstrip("/"))
    # "." 排除重复抽帧的 .fNNNNN 目录；"*" 排除字面名为 * 的伪目录（会让 glob 二次展开成全并集）
    if "." in name or "*" in name or "?" in name or "[" in name:
        continue
    f = sorted(glob.glob(d + "*.jpg"))
    if f:
        src[name] = f
for bv in ANIM:
    f = sorted(glob.glob(f"{FA}/{bv}_*.jpg"))
    if f:
        src[bv] = f

CELL, COLS = 230, 4
rows = (len(src) + COLS - 1) // COLS
sheet = Image.new("RGB", (CELL * COLS, CELL * rows), (22, 22, 26))
dr = ImageDraw.Draw(sheet)

for i, name in enumerate(sorted(src)):
    files = src[name]
    p = files[len(files) // 4]          # 取 1/4 处一帧，避开首帧黑场
    im = Image.open(p).convert("RGB")
    w, h = im.size
    s = min(CELL / w, CELL / h)
    im2 = im.resize((max(1, int(w * s)), max(1, int(h * s))))
    x = (i % COLS) * CELL + (CELL - im2.width) // 2
    y = (i // COLS) * CELL + (CELL - im2.height) // 2
    sheet.paste(im2, (x, y))
    cut = CROP.get(name, 0.0)
    if cut:
        yy = y + int(im2.height * (1 - cut))
        dr.line([(x, yy), (x + im2.width, yy)], fill=(255, 60, 60), width=2)
    dr.text(((i % COLS) * CELL + 4, (i // COLS) * CELL + 4),
            f"{name[:13]} {w}x{h}", fill=(255, 255, 0))

out = "/tmp/src_preview.png"
sheet.save(out)
print(f"saved {out} {sheet.size}  sources={len(src)}")
for k in sorted(src):
    print(f"  {k:20s} {len(src[k]):5d}  crop={CROP.get(k, 0.0)}")
