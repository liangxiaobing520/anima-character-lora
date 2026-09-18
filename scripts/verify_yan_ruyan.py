#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""燕如嫣 LoRA 验收出图（按用户 2026-09-16 三条验收标准）。

验收标准（三条并行，缺一不可）：
  ① 角色脸是否像原版
  ② 服饰配件是否还原（黑金古装、金色发饰）
  ③ 全身照是否还原

因此每个用例都刻意区分"全身"与"特写"两类构图：
  - 全身类：正面固定加 full body, standing, from head to toe, feet visible，
            负面固定加 close-up/portrait/upper body/half body/cowboy shot/
            cropped legs/cropped/headshot/zoom in（不压制会退化成半身像）
  - 特写类：只用于看脸，不压制裁切

与 verify_lora.py 的区别：后者把 prompt 写死成 purple hair/purple eyes/
japanese clothes（原神角色模板），套到燕如嫣身上结论无效。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from neg_policy import neg_safety

COMFY = "http://127.0.0.1:8188"
COMFY_LORAS = "/home/xiaozeng/ComfyUI/models/loras"
GD = "/home/xiaozeng/lora_train/genshin_dataset"
OUT = os.path.join(GD, "output")
RESULT = os.path.join(GD, "verify_yan_ruyan")
LORA = "yan_ruyan_anima_lora.safetensors"
TRIGGER = "yan_ruyan, fanren_xiuxian_zhuan"

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
BASE_NEG = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
            "bad anatomy, fused bodies, color bleeding, (extra people:1.4), (2girls:1.3), "
            "duplicate, extra limbs, extra digits, deformed, disfigured, mutated, ")
# 全身构图必备：不压制裁切词，模型会跑成半身像/胸像
CROP_NEG = ("close-up, portrait, upper body, half body, cowboy shot, cropped legs, "
            "cropped, headshot, zoom in, ")
FULL_POS = "full body, standing, from head to toe, feet visible, "

NEG_FULL = BASE_NEG + CROP_NEG + neg_safety().rstrip(", ")
NEG_FACE = BASE_NEG + neg_safety().rstrip(", ")

# (标签, LoRA, 强度, 追加prompt, seed, 是否全身)
CASES = [
    ("A_nolora_full",  None, 0.0,
     "1girl, solo, black hair, hanfu, ancient chinese clothes", 757218282, True),
    ("B_lora10_full",  LORA, 1.0,
     "1girl, solo, black hair, hanfu, ancient chinese clothes", 757218282, True),
    ("C_lora10_full2", LORA, 1.0,
     "1girl, solo, black hair, hanfu, ancient chinese clothes, outdoors, night", 20260916, True),
    ("D_lora085_full", LORA, 0.85,
     "1girl, solo, black hair, hanfu, ancient chinese clothes", 757218282, True),
    ("E_lora10_face",  LORA, 1.0,
     "1girl, solo, black hair, close-up, portrait, face focus, looking at viewer", 999999999, False),
]
W, H = 832, 1216


def build(lora=None, strength=1.0, prompt="", seed=1, full=True, steps=32, cfg=4.5):
    text = Q + prompt + (", " + FULL_POS.rstrip(", ") if full else "")
    neg = NEG_FULL if full else NEG_FACE
    wf = {
        "44": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-aesthetic-v1.1.safetensors", "weight_dtype": "default"}},
        "45": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion",
            "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["45", 0]}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {
            "model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0],
            "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "verify_yr", "images": ["8", 0]}},
    }
    if lora:
        wf["46"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["44", 0], "lora_name": lora, "strength_model": strength}}
        wf["31"]["inputs"]["model"] = ["46", 0]
    return wf


def gen(wf, tag, timeout=900):
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pid = json.loads(r.read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        with urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join("/home/xiaozeng/ComfyUI/output", im["filename"])
                    os.makedirs(RESULT, exist_ok=True)
                    dst = os.path.join(RESULT, f"{tag}.png")
                    shutil.copy2(src, dst)
                    print(f"   ✅ {tag} -> {dst}", flush=True)
                    return dst
            print(f"   ⚠️ {tag} 无输出图像", flush=True)
            return None
    print(f"   ❌ {tag} 超时", flush=True)
    return None


def main():
    src = os.path.join(OUT, LORA)
    dst = os.path.join(COMFY_LORAS, LORA)
    if not os.path.exists(src):
        print(f"❌ 找不到训练产物 {src}")
        sys.exit(1)
    print(f"=== 产物 {os.path.getsize(src)/1e6:.1f} MB -> 转换 ComfyUI 格式", flush=True)
    r = subprocess.run(
        ["/home/xiaozeng/sd-scripts/.venv/bin/python",
         "networks/convert_anima_lora_to_comfy.py", src, dst],
        cwd="/home/xiaozeng/sd-scripts", capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ 转换失败:\n", r.stdout[-1200:], r.stderr[-1200:])
        sys.exit(1)
    print(f"   ✅ -> {dst}", flush=True)

    print("=== 出图（全身类按三条验收标准，特写类仅用于看脸）", flush=True)
    for tag, lora, strength, extra, seed, full in CASES:
        print(f"   [{tag}] lora={lora} strength={strength} full={full}", flush=True)
        gen(build(lora, strength, f"{TRIGGER}, {extra}", seed, full), tag)
    print(f"\n结果目录: {RESULT}", flush=True)


if __name__ == "__main__":
    main()
