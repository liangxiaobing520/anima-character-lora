#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比两个 LoRA：视角配平前(v1) vs 配平后(v2)

同一组提示词、同一 seed，只换 LoRA，看构图倾向和视角还原的差异。
重点验证：配平数据集训出的 LoRA 是否不再"爱裁半身"。

用法：
  python3 compare_loras.py <v1.safetensors> <v2.safetensors> [tag]
不加参数则用默认的两个：
  v1 = output/raiden_shogun_anima_lora_v1_568imgs.safetensors
  v2 = output/raiden_shogun_anima_lora.safetensors
"""
from neg_policy import neg_safety  # 画风开关: ANIMA_ALLOW_3D=1 或 --allow-3d
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

COMFY = "http://127.0.0.1:8188"
GD = "/home/xiaozeng/lora_train/genshin_dataset"
SD = "/home/xiaozeng/sd-scripts"
COMFY_LORAS = "/home/xiaozeng/ComfyUI/models/loras"
RESULT = os.path.join(GD, "verify_compare")
W, H = 832, 1216
STRENGTH = 0.85

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
       "bad anatomy, fused bodies, color bleeding, (extra people:1.4), (2girls:1.3), "
       "duplicate, extra limbs, extra digits, deformed, disfigured, mutated, "
       + neg_safety() +
       "close-up, portrait, upper body, half body, cowboy shot, cropped, headshot, zoom in")

# 三条测试提示词：正面全身 / 侧面全身 / 背面全身
PROMPTS = [
    ("front", "raiden_shogun_(genshin_impact), 1girl, solo, full body, standing, "
              "looking at viewer, purple hair, long braid, purple eyes, japanese clothes, "
              "kimono, white background, simple background"),
    ("side",  "raiden_shogun_(genshin_impact), 1girl, solo, full body, standing, "
              "from side, profile, purple hair, long braid, purple eyes, japanese clothes, "
              "kimono, white background, simple background"),
    ("back",  "raiden_shogun_(genshin_impact), 1girl, solo, full body, standing, "
              "from behind, back view, purple hair, long braid, japanese clothes, "
              "kimono, white background, simple background"),
]
SEEDS = [880770001, 880770002, 880770003]


def convert(src, tag):
    """sd-scripts LoRA -> ComfyUI 格式"""
    dst = os.path.join(COMFY_LORAS, "%s.safetensors" % tag)
    r = subprocess.run([os.path.join(SD, ".venv/bin/python"),
                        "networks/convert_anima_lora_to_comfy.py", src, dst],
                       cwd=SD, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ 转换失败 %s:\n%s" % (tag, (r.stdout + r.stderr)[-800:]))
        return None
    print("   ✅ 转换 %s -> %.1f MB" % (os.path.basename(dst), os.path.getsize(dst) / 1e6))
    return os.path.basename(dst)


def build(lora_name, prompt, seed, steps=32, cfg=4.5):
    wf = {
        "44": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-aesthetic-v1.1.safetensors", "weight_dtype": "default"}},
        "45": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion",
            "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": Q + prompt, "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["45", 0]}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {
            "model": ["46", 0], "positive": ["11", 0], "negative": ["12", 0],
            "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "cmp", "images": ["8", 0]}},
        "46": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["44", 0], "lora_name": lora_name, "strength_model": STRENGTH}},
    }
    return wf


def run(lora_name, prompt, seed, tag):
    wf = build(lora_name, prompt, seed)
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("   ❌ %s 提交失败: %s" % (tag, e.read().decode()[:400]))
        return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join("/home/xiaozeng/ComfyUI/output", im["filename"])
                    os.makedirs(RESULT, exist_ok=True)
                    dst = os.path.join(RESULT, "%s.png" % tag)
                    shutil.copy2(src, dst)
                    print("   ✅ %s (%.0fs)" % (tag, time.time() - t0))
                    return dst
            print("   ⚠️ %s 无输出（重跑）" % tag)
            return None
    print("   ❌ %s 超时" % tag)
    return None


def main():
    v1 = sys.argv[1] if len(sys.argv) > 1 else os.path.join(GD, "output/raiden_shogun_anima_lora_v1_568imgs.safetensors")
    v2 = sys.argv[2] if len(sys.argv) > 2 else os.path.join(GD, "output/raiden_shogun_anima_lora.safetensors")
    print("=== 转换两个 LoRA ===")
    n1 = convert(v1, "cmp_v1")
    n2 = convert(v2, "cmp_v2")
    if not (n1 and n2):
        return 1

    print("\n=== 同一 prompt 各出一张（seed 相同，只换 LoRA）===")
    for (name, prompt), seed in zip(PROMPTS, SEEDS):
        print("[%s]" % name)
        run(n1, prompt, seed, "v1_%s" % name)
        run(n2, prompt, seed, "v2_%s" % name)
    print("\n结果目录: %s" % RESULT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
