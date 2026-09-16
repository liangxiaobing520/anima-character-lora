#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分辨率对比：同一角色、同一 prompt、同一 seed，只换 LoRA（640 vs 768）

compare_loras.py 是写死 raiden_shogun 的；这个版本参数化角色，
专门给「训练分辨率 A/B 实验」出图用。

用法：
  python3 compare_res.py <char_dir> <loraA> <loraB> <tagA> <tagB>
例：
  python3 compare_res.py furina \
      output/exp_furina_640.safetensors \
      output/exp_furina_768.safetensors 640 768

输出：
  verify_compare/res_<char>_<tag>_<view>.png
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

# 角色 -> (booru tag, 外观特征词)。要对比分辨率，特征词必须足够细：
# 头发挑染、帽檐、领结这类小结构最容易看出 640/768 的差别。
CHARS = {
    "furina": ("furina_(genshin_impact)",
               "white hair, short hair, streaked hair, blue hair, blue eyes, "
               "hair ornament, hat, blue jacket, necktie, gloves"),
    "raiden_shogun": ("raiden_shogun_(genshin_impact)",
                      "purple hair, long braid, purple eyes, japanese clothes, "
                      "kimono, hair flower, hair ornament"),
}

# 三条视角提示词：正面 / 侧面 / 背面
VIEWS = ["front", "side", "back"]
VIEW_TAGS = {
    "front": "looking at viewer",
    "side": "from side, profile",
    "back": "from behind, back view",
}
SEEDS = [880770001, 880770002, 880770003]


def convert(src, tag):
    """sd-scripts LoRA -> ComfyUI 格式"""
    dst = os.path.join(COMFY_LORAS, "%s.safetensors" % tag)
    r = subprocess.run([os.path.join(SD, ".venv/bin/python"),
                        "networks/convert_anima_lora_to_comfy.py", src, dst],
                       cwd=SD, capture_output=True, text=True)
    if r.returncode != 0:
        print("   [X] 转换失败 %s:\n%s" % (tag, (r.stdout + r.stderr)[-800:]))
        return None
    print("   [OK] 转换 %s -> %.1f MB" % (os.path.basename(dst),
                                          os.path.getsize(dst) / 1e6))
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
            "filename_prefix": "cmpres", "images": ["8", 0]}},
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
        print("   [X] %s 提交失败: %s" % (tag, e.read().decode()[:400]))
        return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        try:
            with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
                h = json.loads(r.read())
        except Exception as e:
            print("   [!] %s 轮询异常(%s)，重试" % (tag, e.__class__.__name__))
            continue
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join("/home/xiaozeng/ComfyUI/output", im["filename"])
                    os.makedirs(RESULT, exist_ok=True)
                    dst = os.path.join(RESULT, "%s.png" % tag)
                    shutil.copy2(src, dst)
                    print("   [OK] %s (%.0fs)" % (tag, time.time() - t0))
                    return dst
            print("   [!] %s 无输出" % tag)
            return None
    print("   [X] %s 超时" % tag)
    return None


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        return 2
    char = sys.argv[1]
    lora_a, lora_b = sys.argv[2], sys.argv[3]
    tag_a, tag_b = sys.argv[4], sys.argv[5]

    if char not in CHARS:
        print("未知角色 %s，可选: %s" % (char, ", ".join(CHARS)))
        return 2
    char_tag, traits = CHARS[char]

    for p in (lora_a, lora_b):
        if not os.path.isfile(p):
            print("[X] 找不到 %s" % p)
            return 1

    print("=== 转换两个 LoRA ===")
    na = convert(lora_a, "res_%s_%s" % (char, tag_a))
    nb = convert(lora_b, "res_%s_%s" % (char, tag_b))
    if not (na and nb):
        return 1

    print("\n=== 同 prompt/seed，各出 %d 张（640 与 768 逐张对照）===" % len(VIEWS))
    ok = 0
    for view, seed in zip(VIEWS, SEEDS):
        prompt = ("%s, 1girl, solo, full body, standing, %s, %s, "
                  "from head to toe, feet visible, "
                  "white background, simple background" % (char_tag, VIEW_TAGS[view], traits))
        print("[%s]" % view)
        for n, tg in ((na, tag_a), (nb, tag_b)):
            if run(n, prompt, seed, "res_%s_%s_%s" % (char, tg, view)):
                ok += 1
    print("\n结果目录: %s  (成功 %d/%d)" % (RESULT, ok, len(VIEWS) * 2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
