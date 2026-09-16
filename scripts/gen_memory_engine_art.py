#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记忆引擎 dsh-local-vector-memory — 生图说明图（复用已验证 Anima 工作流）"""
import os
from neg_policy import neg_safety  # 画风开关: ANIMA_ALLOW_3D=1 或 --allow-3d
import json, os, shutil, time, urllib.request, urllib.error

COMFY = "http://127.0.0.1:8188"
COMFY_OUT = "/home/xiaozeng/ComfyUI/output"
OUTDIR = "/home/xiaozeng/deepseek工作区/图片生成"

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
       "bad anatomy, fused bodies, color bleeding, extra limbs, extra digits, deformed, "
       "disfigured, mutated, " + neg_safety() +
       "text, watermark, signature, ui, screenshot, "
       "close-up, portrait, upper body, half body, cowboy shot, cropped legs, cropped, "
       "headshot, zoom in, (extra people:1.4), (2girls:1.3), duplicate, ")

PROMPT = (
    "1girl, solo, full body, standing, from head to toe, feet visible, "
    "silver long flowing hair, glowing cyan eyes, white and teal futuristic outfit, "
    "long coat, holographic hair ornament, "
    "celestial library of memory, gigantic magical archive, "
    "countless floating glowing memory crystals connected by streams of light, "
    "spiral holographic data ribbons, luminous spheres orbiting her, "
    "cyan and magenta glowing runes floating in air, "
    "starfield and soft particles, dark blue cosmic background, "
    "soft rim light, volumetric light, magical atmosphere, "
    "reaching out one hand, crystals reflecting in her palm, looking at viewer"
)

def build(seed, w=832, h=1216, steps=32, cfg=4.5, lora=("anima_artiststylemix_5.safetensors", 0.5)):
    wf = {
        "44": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-aesthetic-v1.1.safetensors", "weight_dtype": "default"}},
        "45": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": Q + PROMPT, "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG, "clip": ["45", 0]}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {"model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0],
                 "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
                 "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "memory_engine", "images": ["8", 0]}},
    }
    if lora:
        wf["46"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["44", 0], "lora_name": lora[0], "strength_model": lora[1]}}
        wf["31"]["inputs"]["model"] = ["46", 0]
    return wf

def run(name, seed, **kw):
    wf = build(seed, **kw)
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("提交失败 %s: %s" % (e.code, e.read().decode()[:600])); return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join(COMFY_OUT, im["filename"])
                    os.makedirs(OUTDIR, exist_ok=True)
                    dst = os.path.join(OUTDIR, name + ".png")
                    shutil.copy2(src, dst)
                    print("OK %s (%.0fs) -> %s" % (name, time.time() - t0, dst)); return dst
            print("无输出 %s: %s" % (name, json.dumps(h)[:400])); return None
    print("超时 %s" % name); return None

if __name__ == "__main__":
    seeds = [88011001, 88011002, 88011003]
    for i, s in enumerate(seeds, 1):
        run("记忆引擎_说明图_%02d" % i, s)
