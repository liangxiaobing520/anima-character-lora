#!/usr/bin/env python3
"""燕如嫣干净素材集构建。

只用三个已人工验证纯净的源（密抽样 6/6 均为燕如嫣）：
  BV1Vnec67ERv 48帧 / BV18zvSBkE52 13帧 / BV1BRYB6RE5h 19帧 = 80 帧
其余 11 个源经密抽样判定为男性角色/粉发少女/真人AI图/远景/器物/嘴部特写，一律排除。

处理：最短边过滤 → 近乎重复帧剔除（ahash 汉明 <=2）→ 输出 raw/yan_ruyan
同时生成总览拼图供人工复核。不改动源帧目录。
"""
import os
import glob
import numpy as np
from PIL import Image, ImageDraw

V = "/home/xiaozeng/lora_train/yanruyan_video"
RAW = "/home/xiaozeng/lora_train/genshin_dataset/raw/yan_ruyan"
CAPTION = "yan_ruyan, fanren_xiuxian_zhuan, 1girl, solo"
MIN_SIDE = 300          # 480x852 这类竖版源要留
DUP_HAMMING = 2         # 只剔除近乎完全相同的帧

CLEAN = ["BV1Vnec67ERv", "BV18zvSBkE52", "BV1BRYB6RE5h", "BV1cvP8z1Egz"]


def src_files(bv):
    f = sorted(glob.glob(f"{V}/frames_all/{bv}_*.jpg"))
    if not f:
        f = sorted(glob.glob(f"{V}/frames2/{bv}/{bv}_*.jpg"))
    return f


def ahash(im, hs=12):
    g = im.convert("L").resize((hs, hs), Image.LANCZOS)
    a = np.asarray(g, dtype=np.float32)
    return (a > a.mean()).flatten()


def sharpness(im):
    """Laplacian 方差，越高越锐利。"""
    g = np.asarray(im.convert("L").resize((512, 512)), dtype=np.float32)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
           + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


os.makedirs(RAW, exist_ok=True)
kept, dropped, seen = [], [], []
scores = []

for bv in CLEAN:
    for p in src_files(bv):
        try:
            im = Image.open(p)
            im.load()
        except Exception as e:
            print(f"  跳过损坏文件 {p}: {e}")
            continue
        w, h = im.size
        if min(w, h) < MIN_SIDE:
            dropped.append((p, f"最短边 {min(w,h)}<{MIN_SIDE}"))
            continue
        a = ahash(im)
        dup = False
        for b in seen:
            if int((a != b).sum()) <= DUP_HAMMING:
                dup = True
                break
        if dup:
            dropped.append((p, "近乎重复"))
            continue
        seen.append(a)
        kept.append((bv, p, im.copy(), sharpness(im)))

print(f"保留 {len(kept)} 帧，剔除 {len(dropped)} 帧")
for p, why in dropped:
    print(f"  剔除 {os.path.basename(p)}: {why}")
sc = [s for *_x, s in kept]
if sc:
    print(f"清晰度 Laplacian 方差: min={min(sc):.0f} 中位={sorted(sc)[len(sc)//2]:.0f} max={max(sc):.0f}")

# ---- 输出到 raw/yan_ruyan ----
for old in glob.glob(f"{RAW}/*"):
    os.remove(old)
for i, (bv, p, im, s) in enumerate(kept):
    name = f"yan_ruyan_{i:04d}"
    im.convert("RGB").save(f"{RAW}/{name}.jpg", quality=95)
    with open(f"{RAW}/{name}.txt", "w") as f:
        f.write(CAPTION + "\n")
print(f"写入 {RAW}: {len(kept)} 组 jpg+txt")

# ---- 总览拼图 ----
CELL, COLS = 150, 10
rows = (len(kept) + COLS - 1) // COLS
sheet = Image.new("RGB", (CELL * COLS, CELL * rows), (18, 18, 22))
dr = ImageDraw.Draw(sheet)
for i, (bv, p, im, s) in enumerate(kept):
    t = im.copy()
    t.thumbnail((CELL, CELL), Image.LANCZOS)
    x = (i % COLS) * CELL + (CELL - t.width) // 2
    y = (i // COLS) * CELL + (CELL - t.height) // 2
    sheet.paste(t, (x, y))
sheet.save("/tmp/clean_preview.png")
print(f"拼图 -> /tmp/clean_preview.png {sheet.size}  ({COLS} 列)")
by_src = {}
for bv, *_ in kept:
    by_src[bv] = by_src.get(bv, 0) + 1
print("各源保留:", by_src)
