#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""古风熟女·太师椅慵懒嫌弃（坐姿全身立绘）

工作流：anima-aesthetic-v1.1 + qwen_3_06b_base + qwen_image_vae
32 步 / cfg 4.5 / er_sde + simple / 竖版 832x1216

构图要点（用户 2026-09-14 要求）：
  熟女 + 丰韵身材 + 古风衣着暴露 + 室内大厅 + 太师椅 + 跷二郎腿
  + 一手支头慵懒 + 看向观者、嫌弃眼神

用法：
  python3 gen_lounge_lady.py                  # 默认单张
  python3 gen_lounge_lady.py 名字 种子         # 自定义
  python3 gen_lounge_lady.py 名字 种子 milf   # 换熟女 LoRA 版
"""
from neg_policy import neg_safety  # 画风开关: ANIMA_ALLOW_3D=1 或 --allow-3d
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

COMFY = "http://127.0.0.1:8188"
COMFY_OUT = "/home/xiaozeng/ComfyUI/output"
SHOWCASE = "/home/xiaozeng/deepseek工作区/图片生成"
W, H = 832, 1216          # 单人竖版

# 坐姿全身：把 standing 换成 sitting，其余构图约束照旧
SIT_BODY_POS = "full body, sitting, from head to toe, feet visible, "
SIT_BODY_NEG = (", close-up, portrait, upper body, half body, cowboy shot, "
                "cropped legs, cropped, headshot, zoom in")
# 单人专用：压制多出来的人
SOLO_NEG = "(extra people:1.4), (2girls:1.3), duplicate, "
# 手部强化（小画幅下手容易糊成钩爪）
HAND_POS = "perfect hands, detailed hands, five fingers, "
HAND_NEG = ("bad hands, poorly drawn hands, extra fingers, missing fingers, fused fingers, "
            "mutated hands, malformed hands, claw shaped fingers, ")

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG_BASE = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
            "bad anatomy, fused bodies, color bleeding, " + SOLO_NEG +
            "extra limbs, extra digits, deformed, disfigured, mutated, "
            + neg_safety() + HAND_NEG)

# ─────────────── 画面内容 ───────────────
# 熟女 / 丰韵 / 古风暴露 / 大厅 / 太师椅 / 二郎腿 / 支头 / 嫌弃
CONTENT = (
    "mature female, milf, 1girl, solo, voluptuous, plump body, curvy, thick thighs, "
    "wide hips, huge breasts, deep cleavage, soft body, "
    "ancient chinese clothes, hanfu, revealing clothes, low cut dress, bare shoulders, "
    "translucent silk, thin veil, side slit, gold ornaments, hair ornament, "
    "long black hair, elegant updo, hair bun, red lips, mature face, makeup, "
    "wooden armchair, chinese style chair, carved wooden chair, armrest, taoist chair, "
    "crossed legs, crossed thighs, leg on leg, "
    "head resting on hand, hand on own cheek, elbow on armrest, lazy, languid, lounging, "
    "looking at viewer, disgust, disdain, contempt, frown, annoyed, displeased, "
    "half closed eyes, sneer, looking down on viewer, "
    "chinese hall, indoor, grand hall, wooden pillars, red lanterns, folding screen, "
    "wooden floor, ornate ceiling, incense burner, warm light, "
    "crimson and gold, cinematic lighting, depth of field"
)

# LoRA 方案：默认纯画风；milf 版额外挂熟女 LoRA
LORA_STYLE = ("anima_artiststylemix_5.safetensors", 0.5)
LORA_MILF = ("anima_milf_saggy_breasts.safetensors", 0.55)


def build(prompt, seed, loras, steps=32, cfg=4.5, w=W, h=H):
    pos = Q + SIT_BODY_POS + HAND_POS + prompt
    neg = NEG_BASE + SIT_BODY_NEG
    wf = {
        "44": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-aesthetic-v1.1.safetensors", "weight_dtype": "default"}},
        "45": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion",
            "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["45", 0]}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["45", 0]}},
        "28": {"class_type": "EmptyLatentImage", "inputs": {
            "width": w, "height": h, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {
            "model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0],
            "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "lounge_lady", "images": ["8", 0]}},
    }
    prev = ["44", 0]
    for i, (name, strength) in enumerate(loras):
        nid = str(46 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": prev, "lora_name": name, "strength_model": strength}}
        prev = [nid, 0]
    wf["31"]["inputs"]["model"] = prev
    return wf


def run(name, seed, loras):
    wf = build(CONTENT, seed, loras)
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("   ❌ 提交失败 %s: %s" % (e.code, e.read().decode()[:800]))
        return None
    t0 = time.time()
    while time.time() - t0 < 900:
        time.sleep(4)
        with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    src = os.path.join(COMFY_OUT, im["filename"])
                    os.makedirs(SHOWCASE, exist_ok=True)
                    dst = os.path.join(SHOWCASE, name + ".png")
                    shutil.copy2(src, dst)
                    print("   ✅ %s  (%.0fs) seed=%d -> %s" % (name, time.time() - t0, seed, dst))
                    return dst
            print("   ⚠️ %s 无输出（KSampler Fault 偶发，原样重跑）" % name)
            return None
    print("   ❌ %s 超时" % name)
    return None


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "古风熟女_太师椅嫌弃_01"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20260914001
    variant = sys.argv[3] if len(sys.argv) > 3 else ""
    loras = [LORA_STYLE] + ([LORA_MILF] if variant == "milf" else [])

    with urllib.request.urlopen(COMFY + "/system_stats", timeout=10) as r:
        st = json.loads(r.read())
    print("ComfyUI 就绪: %s" % st.get("system", {}).get("comfyui_version", "?"))
    print("LoRA: %s" % ", ".join("%s@%s" % l for l in loras))
    run(name, seed, loras)
    return 0


if __name__ == "__main__":
    sys.exit(main())
