#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画风与脸型还原测试。

诊断依据（2026-09-16 对比 A / B 两张实测）：
  A 无 LoRA → 干净的二次元动漫画风
  B 有 LoRA → 3D 写实渲染风；五官像燕如嫣，但脸型被拉成"3D 网红脸"，
              与参考帧里动画版燕如嫣的脸型对不上
成因：训练素材是《凡人修仙传》3D 动画截图，LoRA 连画风一起学走了；
      而底模 Anima-Aesthetic 是二次元底模，两者打架 → 脸型失真。

本批把画风明确往二次元按，并在负面里压制 3D/写实词，
用来判断"脸型不像"到底是画风问题还是训练不足。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_yan_ruyan as V

# 强化 2D，压制 3D / 写实渲染
V.NEG_FULL = (V.BASE_NEG + V.CROP_NEG +
              "3d, cgi, realistic, photorealistic, photo, render, 3d render, "
              "octane render, unreal engine, hyperrealistic, " +
              V.neg_safety().rstrip(", "))
V.NEG_FACE = (V.BASE_NEG +
              "3d, cgi, realistic, photorealistic, photo, render, 3d render, "
              "octane render, unreal engine, hyperrealistic, " +
              V.neg_safety().rstrip(", "))

STYLE = "anime style, 2d, flat color, cel shading, illustration, lineart, "
SEED = 555111222

# (标签, 权重, 追加prompt, 是否全身)
CASES = [
    ("S1_2d_full",   1.0, STYLE + "black hair, hanfu, ancient chinese clothes", True),
    ("S2_2d_full08", 0.8, STYLE + "black hair, hanfu, ancient chinese clothes", True),
    ("S3_2d_face",   1.0, STYLE + "black hair, close-up, portrait, face focus", False),
]

if not os.path.exists(os.path.join(V.COMFY_LORAS, V.LORA)):
    print("❌ ComfyUI 里还没有该 LoRA")
    sys.exit(1)

print("=== 画风/脸型测试（强化 2D + 负面压制 3D、写实）", flush=True)
for tag, strength, extra, full in CASES:
    print(f"   [{tag}] strength={strength} full={full}", flush=True)
    V.gen(V.build(V.LORA, strength, f"{V.TRIGGER}, 1girl, solo, {extra}", SEED, full), tag)
print("画风测试完成", flush=True)
