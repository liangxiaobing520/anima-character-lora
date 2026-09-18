#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参考帧 vs 生成图 并排对比图。

上排：训练素材里的参考帧（燕如嫣原图，按序号均匀取 5 张）
下排：LoRA 生成的验收图（A无LoRA / B全身 / C全身夜景 / D全身0.85 / E特写）
用于按用户三条标准判断：①脸像不像 ②服饰配件还原 ③全身照还原
"""
import glob
import os
from PIL import Image, ImageDraw

RAW = "/home/xiaozeng/lora_train/genshin_dataset/raw/yan_ruyan"
GEN = "/home/xiaozeng/lora_train/genshin_dataset/verify_yan_ruyan"
OUT = "/tmp/compare_ref_gen.png"

CELL_W, CELL_H = 250, 366      # 贴近 832x1216 的比例
LABEL_H = 20

refs = sorted(glob.glob(f"{RAW}/*.jpg"))
N = 5
ref_pick = [refs[min(int(len(refs) * (i + 0.5) / N), len(refs) - 1)] for i in range(N)]

gens = []
for tag in ["A_nolora_full", "B_lora10_full", "C_lora10_full2",
            "D_lora085_full", "E_lora10_face"]:
    p = os.path.join(GEN, f"{tag}.png")
    if os.path.exists(p):
        gens.append((tag, p))

rows = 2
sheet = Image.new("RGB", (CELL_W * N, (CELL_H + LABEL_H) * rows), (18, 18, 22))
dr = ImageDraw.Draw(sheet)


def paste(im, col, row, label):
    im = im.copy()
    im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
    x = col * CELL_W + (CELL_W - im.width) // 2
    y = row * (CELL_H + LABEL_H) + LABEL_H + (CELL_H - im.height) // 2
    sheet.paste(im, (x, y))
    dr.text((col * CELL_W + 3, row * (CELL_H + LABEL_H) + 4), label, fill=(255, 230, 60))


for i, p in enumerate(ref_pick):
    paste(Image.open(p).convert("RGB"), i, 0, f"REF {os.path.basename(p)[-8:-4]}")
for i, (tag, p) in enumerate(gens):
    paste(Image.open(p).convert("RGB"), i, 1, tag)

sheet.save(OUT)
print(f"上排=素材参考帧 {len(ref_pick)} 张，下排=生成图 {len(gens)} 张")
print(f"-> {OUT} {sheet.size}")
