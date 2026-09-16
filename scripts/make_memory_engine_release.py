# -*- coding: utf-8 -*-
"""把生图合成发布版说明图：插画 + 中文说明面板 + 封面图"""
from PIL import Image, ImageDraw, ImageFont
import os, shutil

SRC = "/home/xiaozeng/deepseek工作区/图片生成/记忆引擎_说明图_01.png"
OUTDIR = "/home/xiaozeng/deepseek工作区/图片生成"
F_BOLD = "/mnt/c/Windows/Fonts/msyhbd.ttc"
F_REG  = "/mnt/c/Windows/Fonts/msyh.ttc"
W, H = 1080, 1440
CYAN = (86, 226, 255)
MAG  = (255, 106, 193)
WHITE = (240, 246, 255)
DIM = (176, 196, 220)

def font(path, size):
    for i in (0, 1, 2):
        try: return ImageFont.truetype(path, size, index=i)
        except Exception: continue
    raise RuntimeError("font load failed: " + path)

title_f  = font(F_BOLD, 52)
sub_f    = font(F_REG, 23)
badge_f  = font(F_BOLD, 25)
item_f   = font(F_REG, 26)
key_f    = font(F_BOLD, 26)
cap_f    = font(F_REG, 20)

canvas = Image.new("RGB", (W, H), (10, 13, 24))
d = ImageDraw.Draw(canvas)

# ── 顶部标题区
d.text((44, 34), "记忆引擎 · dsh-local-vector-memory", font=title_f, fill=WHITE)
d.text((46, 106), "DSH 会话持久记忆插件  |  v0.3.3  |  DeepSeek Harness 自研", font=sub_f, fill=DIM)
d.line([(46, 148), (46 + 760, 148)], fill=CYAN, width=3)

# ── 插画
art = Image.open(SRC).convert("RGB")
AW, AH = 820, 1198
art = art.resize((AW, AH), Image.LANCZOS)
ax, ay = (W - AW) // 2, 180
canvas.paste(art, (ax, ay))
d.rounded_rectangle([ax - 3, ay - 3, ax + AW + 2, ay + AH + 2], radius=14, outline=(70, 120, 160), width=3)

# ── 底部说明面板
py = 1452
panel_top = py - 46
d.rectangle([0, panel_top, W, H], fill=(13, 17, 30))
d.line([(0, panel_top), (W, panel_top)], fill=(60, 100, 140), width=2)

# 说明文字（放插画下缘之上，半透明卡片保证可读）
txt_y = ay + AH - 196
d.rounded_rectangle([60, txt_y - 18, W - 60, txt_y + 172], radius=16,
                    fill=(8, 12, 26), outline=(80, 190, 230), width=2)
d.text((84, txt_y - 4), "本机 embedding · 1024 维向量 · SQLite 落盘", font=item_f, fill=CYAN)
d.text((84, txt_y + 40), "四信号混合检索（向量 + BM25 + 时效 + 标签）", font=item_f, fill=WHITE)
d.text((84, txt_y + 84), "12 个 memory_* 工具 · 跨会话自动召回", font=item_f, fill=WHITE)
d.text((84, txt_y + 128), "现役 1113 条记忆 · 全部向量化 · 零重复残留", font=item_f, fill=MAG)

# ── 面板文字（版本信息）
d.text((44, panel_top + 18), "版本 v0.3.3（tag 已推送 GitHub）  ·  GitHub: liangxiaobing520/dsh-local-vector-memory",
       font=cap_f, fill=DIM)

full = os.path.join(OUTDIR, "记忆引擎_说明图_v0.3.3_full.png")
canvas.save(full, "PNG")
print("发布版:", full, canvas.size)

# ── 封面版：纯插画 + 极小水印
cover = art.copy()
cd = ImageDraw.Draw(cover)
cd.rounded_rectangle([AW - 470, AH - 66, AW - 18, AH - 16], radius=10, fill=(8, 12, 26))
cd.text((AW - 450, AH - 56), "dsh-local-vector-memory v0.3.3", font=font(F_BOLD, 22), fill=CYAN)
cov = os.path.join(OUTDIR, "记忆引擎_封面_v0.3.3.png")
cover.save(cov, "PNG")
print("封面:", cov, cover.size)
