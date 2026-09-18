#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""燕如嫣 LoRA 补充验收：服装/角度泛化。

用户标准（2026-09-16 最终版）：①脸必须像原版；②服饰配件不要求还原，原版和其他
版本都可以；③全身照原版和其他版本都可以。核心 = 脸像原版 + 能出全身照。

因此本批专测：换掉训练时的黑金古装之后，脸是否还是同一个人。
复用 verify_yan_ruyan.py 的 build/gen（同一套质量词、全身构图词与负面词）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_yan_ruyan as V

CASES = [
    ("F_white_full",   1.0, "black hair, white dress, standing", 111222333),
    ("G_modern_full",  1.0, "black hair, modern clothes, t-shirt, jeans, standing", 444555666),
    ("H_redhanfu_full", 1.0, "black hair, red hanfu, ancient chinese clothes", 777888999),
    ("I_back_full",    1.0, "black hair, hanfu, from behind, back view", 121212121),
    # B/D 用 seed 757218282 被 LoRA 拉成了胸部特写：48 张训练素材全是胸像/近景，
    # 模型把"特写构图"当成了角色特征。这里降权重 + 换 seed + 加 wide shot，
    # 验证全身构图能否稳定拿回来。
    ("J_lora07_full",  0.7, "black hair, hanfu, ancient chinese clothes, wide shot", 314159265),
    ("K_lora08_full",  0.8, "black hair, hanfu, ancient chinese clothes, wide shot", 271828182),
]

if not os.path.exists(os.path.join(V.COMFY_LORAS, V.LORA)):
    print("❌ ComfyUI 里还没有该 LoRA，先跑 verify_yan_ruyan.py")
    sys.exit(1)

print("=== 服装/角度泛化补充出图（全部全身）", flush=True)
for tag, strength, extra, seed in CASES:
    print(f"   [{tag}] strength={strength}", flush=True)
    V.gen(V.build(V.LORA, strength, f"{V.TRIGGER}, 1girl, solo, {extra}", seed, True), tag)
print("补充批次完成", flush=True)
