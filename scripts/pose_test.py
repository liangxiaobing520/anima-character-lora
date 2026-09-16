#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""点名测试：验证 LoRA 是否把 caption 里的姿势/表情/服装 tag 学进去了

原理：LoRA 学的是「tag ↔ 画面」的对应关系。训练集里已有
      sitting 477 / lying 222 / kneeling 51 / smile / sword 等标签，
      那么推理时点名这些 tag 就应该能召之即来。

用法：
  python3 pose_test.py [lora文件] [输出标签]
默认用 output/raiden_shogun_anima_lora.safetensors
"""
from neg_policy import neg_safety  # 画风开关: ANIMA_ALLOW_3D=1 或 --allow-3d
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

COMFY = "http://127.0.0.1:8188"
GD = "/home/xiaozeng/lora_train/genshin_dataset"
SD = "/home/xiaozeng/sd-scripts"
COMFY_LORAS = "/home/xiaozeng/ComfyUI/models/loras"
RESULT = os.path.join(GD, "pose_test")
W, H = 832, 1216
STRENGTH = 0.85

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
       "bad anatomy, fused bodies, color bleeding, duplicate, extra limbs, extra digits, "
       "deformed, disfigured, mutated, " + neg_safety() +
       "close-up, portrait, upper body, half body, cowboy shot, cropped, headshot, zoom in")

BASE = "raiden_shogun_(genshin_impact), 1girl, solo, purple hair, long braid, "

# 点名测试表：每个 tag 在训练集里的图片数标注在注释里
CASES = [
    ("01_standing",  BASE + "full body, standing, white background"),                 # 参考基准
    ("02_sitting",   BASE + "full body, sitting, white background"),                  # 477 张
    ("03_lying",     BASE + "full body, lying, on_back, white background"),           # 222 张
    ("04_kneeling",  BASE + "full body, kneeling, white background"),                 # 51 张（少）
    ("05_sword",     BASE + "full body, holding_sword, katana, fighting_stance"),     # 187 张
    ("06_smile",     BASE + "full body, standing, smile, open_mouth, white background"),
    ("07_nude",      BASE + "full body, standing, nude, white background"),           # 265 张
    ("08_kimono",    BASE + "full body, standing, kimono, purple_kimono"),            # 536 张
]
SEED = 991001


def convert(src, tag):
    dst = os.path.join(COMFY_LORAS, "%s.safetensors" % tag)
    r = subprocess.run([os.path.join(SD, ".venv/bin/python"),
                        "networks/convert_anima_lora_to_comfy.py", src, dst],
                       cwd=SD, capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ 转换失败:\n%s" % (r.stdout + r.stderr)[-700:])
        return None
    print("   ✅ 转换 -> %.1f MB" % (os.path.getsize(dst) / 1e6))
    return os.path.basename(dst)


def build(lora_name, prompt, seed, steps=32, cfg=4.5):
    return {
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
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "posetest", "images": ["8", 0]}},
        "46": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["44", 0], "lora_name": lora_name, "strength_model": STRENGTH}},
    }


def run(lora_name, prompt, seed, tag):
    wf = build(lora_name, prompt, seed)
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("   ❌ %s 提交失败: %s" % (tag, e.read().decode()[:300]))
        return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        try:
            with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
                h = json.loads(r.read())
        except Exception:
            continue
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join("/home/xiaozeng/ComfyUI/output", im["filename"])
                    os.makedirs(RESULT, exist_ok=True)
                    dst = os.path.join(RESULT, "%s_%s.png" % (tag, (sys.argv[2] if len(sys.argv) > 2 else "v3")))
                    shutil.copy2(src, dst)
                    print("   ✅ %s (%.0fs)" % (tag, time.time() - t0))
                    return dst
            print("   ⚠️ %s 无输出" % tag)
            return None
    print("   ❌ %s 超时" % tag)
    return None


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(GD, "output/raiden_shogun_anima_lora.safetensors")
    ver = sys.argv[2] if len(sys.argv) > 2 else "v3"
    print("=== 转换 LoRA ===")
    name = convert(src, "posetest_%s" % ver)
    if not name:
        return 1
    print("\n=== 点名测试（%d 项）===" % len(CASES))
    for i, (tag, prompt) in enumerate(CASES):
        run(name, prompt, SEED + i, tag)
    print("\n结果目录: %s" % RESULT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
