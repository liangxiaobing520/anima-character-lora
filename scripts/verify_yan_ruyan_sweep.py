#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""燕如嫣 LoRA 权重阶梯测试：找出"既保住脸、又能拿到全身"的权重。

背景（2026-09-16 实测）：
  - 训练素材 48 张全是胸像/近景，0 张全身 → LoRA 把"特写取景"当成角色特征学走了
  - 权重 1.0 时，即使 prompt 写 full body, standing, from head to toe, feet visible
    且负面压制 close-up/upper body/cropped，仍然出俯视特写（F/B/D 三张均如此）
  - 权重 0.85 同样出特写（D 那张）
  → 本脚本扫 0.5 / 0.6 / 0.7 / 0.8 四档，全部用同一 prompt 与 seed，
    只变权重，直接看出"构图被 LoRA 接管"的临界点。

复用 verify_yan_ruyan.py 的 build/gen（同一套质量词、全身构图词与负面词）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_yan_ruyan as V

PROMPT = "black hair, hanfu, ancient chinese clothes, wide shot"
SEED = 606060606

CASES = [(f"W{int(s * 100):02d}_full", s, PROMPT, SEED) for s in (0.5, 0.6, 0.7, 0.8)]

if not os.path.exists(os.path.join(V.COMFY_LORAS, V.LORA)):
    print("❌ ComfyUI 里还没有该 LoRA")
    sys.exit(1)

print("=== 权重阶梯测试（同一 prompt/seed，只变权重，全部全身构图）", flush=True)
for tag, strength, extra, seed in CASES:
    print(f"   [{tag}] strength={strength}", flush=True)
    V.gen(V.build(V.LORA, strength, f"{V.TRIGGER}, 1girl, solo, {extra}", seed, True), tag)
print("权重阶梯测试完成", flush=True)
