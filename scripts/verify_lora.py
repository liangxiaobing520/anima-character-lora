#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""训练产物验证：转换 Anima LoRA -> ComfyUI 格式 -> 出图对比

用法:
  python3 verify_lora.py <角色id> [触发词]
默认触发词 = 角色id。
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
OUT = os.path.join(GD, "output")
RESULT = os.path.join(GD, "verify")
W, H = 1216, 832

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
       "bad anatomy, fused bodies, color bleeding, (extra people:1.4), (2girls:1.3), "
       "duplicate, extra limbs, extra digits, deformed, disfigured, mutated, "
       + neg_safety().rstrip(", "))


def post(wf, tag):
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pid = json.loads(r.read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(3)
        with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            outs = h[pid].get("outputs", {})
            for _n, o in outs.items():
                for im in o.get("images", []):
                    src = os.path.join("/home/xiaozeng/ComfyUI/output", im["filename"])
                    os.makedirs(RESULT, exist_ok=True)
                    dst = os.path.join(RESULT, "%s_%s" % (tag, im["filename"]))
                    shutil.copy2(src, dst)
                    print("   ✅ %s -> %s" % (tag, dst))
                    return dst
            print("   ⚠️ %s 无输出图像" % tag)
            return None
    print("   ❌ %s 超时" % tag)
    return None


def build(lora_name=None, lora_strength=1.0, prompt="", seed=757218282,
          steps=32, cfg=4.5):
    wf = {
        "44": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-aesthetic-v1.1.safetensors", "weight_dtype": "default"}},
        "45": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion",
            "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": Q + prompt, "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["45", 0]}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {
            "width": W, "height": H, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {
            "model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0],
            "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "verify", "images": ["8", 0]}},
    }
    if lora_name:
        # Anima 的 LoRA 只挂在 DiT 上(network_train_unet_only)，用 ModelOnly 即可
        wf["46"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["44", 0], "lora_name": lora_name, "strength_model": lora_strength}}
        wf["31"]["inputs"]["model"] = ["46", 0]
    return wf


def main():
    char = sys.argv[1] if len(sys.argv) > 1 else "raiden_shogun"
    trigger = sys.argv[2] if len(sys.argv) > 2 else char

    src = os.path.join(OUT, "%s_anima_lora.safetensors" % char)
    dst = os.path.join(COMFY_LORAS, "%s_anima_lora.safetensors" % char)

    print("=== 1. 检查训练产物 ===")
    if not os.path.exists(src):
        print("❌ 找不到 %s" % src)
        sys.exit(1)
    print("   源文件 %.1f MB" % (os.path.getsize(src) / 1e6))

    print("=== 2. 转换为 ComfyUI 格式 ===")
    r = subprocess.run([os.path.join(SD, ".venv/bin/python"),
                        "networks/convert_anima_lora_to_comfy.py", src, dst],
                       cwd=SD, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ 转换失败:\n", r.stdout[-1500:], r.stderr[-1500:])
        sys.exit(1)
    print("   ✅ -> %s (%.1f MB)" % (dst, os.path.getsize(dst) / 1e6))

    print("=== 3. 出图对比（无 LoRA / 有 LoRA）===")
    p = "%s, full body, standing, purple hair, purple eyes, japanese clothes" % trigger
    post(build(None, prompt=p), "nolora")
    post(build("%s_anima_lora.safetensors" % char, 1.0, prompt=p), "lora10")
    post(build("%s_anima_lora.safetensors" % char, 0.75, prompt=p), "lora075")
    print("\n结果目录: %s" % RESULT)


if __name__ == "__main__":
    main()
