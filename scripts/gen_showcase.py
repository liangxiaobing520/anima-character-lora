#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原神角色图批量生成（全身 / 多视图 / 原神实景背景 / 多人）

工作流：anima-aesthetic-v1.1 + qwen_3_06b_base + qwen_image_vae
32步 / cfg4.5 / er_sde+simple

三种模式（job 里的 mode 字段）：
  single  单人全身立绘（默认）—— 竖版 832x1216，带单人压制词
  multi   多人 —— 横版 1216x832，正面加 Ngirls，撤掉单人压制词
  sheet   多视图/三视图（用户 2026-09-14 要求）—— 横版 1216x832，白底，
          正/侧/背多视角排在同一张；且**必须**撤掉单人压制词，
          否则多出来的视图会被当成"多余的人"压掉

用法：
  python3 gen_showcase.py          # 跑 JOBS（实景全身 / 多人）
  python3 gen_showcase.py sheet    # 跑 SHEET_JOBS（多视图）

成品复制到 /home/xiaozeng/deepseek工作区/图片生成/
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

V_W, V_H = 832, 1216    # 竖屏单人
H_W, H_H = 1216, 832    # 宽屏多人 / 多视图

FULL_BODY_POS = "full body, standing, from head to toe, feet visible, "
FULL_BODY_NEG = (", close-up, portrait, upper body, half body, cowboy shot, "
                 "cropped legs, cropped, headshot, zoom in")
# 单人专用：压制多出来的人（多人 / 多视图时必须撤掉）
SOLO_NEG = "(extra people:1.4), (2girls:1.3), duplicate, "
# 手部强化（2026-09-14 用户指出侧面手有问题）：小画幅下每格才 304px、一只手约 40px，
# 模型会把手画成"钩爪状"；加大画幅 + 下面这些词后恢复正常掌型五指。
HAND_POS = "perfect hands, detailed hands, five fingers, "
HAND_NEG = ("bad hands, poorly drawn hands, extra fingers, missing fingers, fused fingers, "
            "mutated hands, malformed hands, claw shaped fingers, ")
# 多视图专用：实测 character sheet 走白底 3 视图、turnaround 走 4 视图
# 画幅取 1536x1024——比 1216x832 每格多约 60% 像素，手才不会糊
MULTIVIEW_W, MULTIVIEW_H = 1536, 1024
MULTIVIEW_POS = ("multiple views, character sheet, reference sheet, front view, side view, "
                 "back view, full body, standing, white background, simple background, " + HAND_POS)

Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")
NEG_BASE = ("worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, "
            "bad anatomy, fused bodies, color bleeding, "
            "extra limbs, extra digits, deformed, disfigured, mutated, "
            + neg_safety() + HAND_NEG)


def build(prompt, seed, lora=None, steps=32, cfg=4.5, w=None, h=None,
          people=1, mode="single"):
    if mode == "sheet":
        # 多视图：不带单人压制词，让人物的多个视角都能画出来
        pos = Q + MULTIVIEW_POS + prompt
        neg = NEG_BASE + FULL_BODY_NEG
    elif people > 1:
        pos = Q + "%dgirls, multiple girls, " % people + FULL_BODY_POS + prompt
        neg = NEG_BASE + FULL_BODY_NEG
    else:
        pos = Q + FULL_BODY_POS + prompt
        neg = NEG_BASE.replace("color bleeding, ", "color bleeding, " + SOLO_NEG) + FULL_BODY_NEG
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
            "width": w or V_W, "height": h or V_H, "batch_size": 1}},
        "31": {"class_type": "KSampler", "inputs": {
            "model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0],
            "latent_image": ["28", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["31", 0], "vae": ["15", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {
            "filename_prefix": "genshin_showcase", "images": ["8", 0]}},
    }
    if lora:
        wf["46"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["44", 0], "lora_name": lora[0], "strength_model": lora[1]}}
        wf["31"]["inputs"]["model"] = ["46", 0]
    return wf


def run(job):
    wf = build(job["prompt"], job["seed"], job.get("lora"),
               w=job.get("w"), h=job.get("h"),
               people=job.get("people", 1), mode=job.get("mode", "single"))
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pid = json.loads(r.read())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("   ❌ %s 提交失败 %s: %s" % (job["name"], e.code, e.read().decode()[:800]))
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
                    dst = os.path.join(SHOWCASE, job["name"] + ".png")
                    shutil.copy2(src, dst)
                    print("   ✅ %s  (%.0fs) -> %s" % (job["name"], time.time() - t0, dst))
                    return dst
            print("   ⚠️ %s 无输出（KSampler Fault 偶发，原样重跑）" % job["name"])
            return None
    print("   ❌ %s 超时" % job["name"])
    return None


def main():
    jobs = SHEET_JOBS if (len(sys.argv) > 1 and sys.argv[1] == "sheet") else JOBS
    with urllib.request.urlopen(COMFY + "/system_stats", timeout=10) as r:
        st = json.loads(r.read())
    print("ComfyUI 就绪: %s" % st.get("system", {}).get("comfyui_version", "?"))
    print("输出目录: %s   任务数: %d\n" % (SHOWCASE, len(jobs)))
    ok = 0
    for i, job in enumerate(jobs, 1):
        print("[%d/%d] %s" % (i, len(jobs), job["name"]))
        if run(job):
            ok += 1
    print("\n完成 %d/%d" % (ok, len(jobs)))
    return 0


# ─────────────── 任务表 A：全身单人 / 多人（原神实景背景） ───────────────
# 提示词不必写 full body/standing —— build() 已自动带
JOBS = [
    dict(
        name="雷电将军_稻妻城_竖屏_01",
        lora=("raiden_shogun_anima_lora.safetensors", 1.0),
        seed=991401001,
        prompt=("raiden_shogun_(genshin_impact), 1girl, solo, purple hair, long braid, "
                "purple eyes, mole under eye, japanese clothes, kimono, hair ornament, "
                "inazuma city, tenshukaku, japanese castle, stone stairs, red maple, "
                "purple lightning, storm clouds, dusk, dramatic sky, looking at viewer"),
    ),
    dict(
        name="甘雨_璃月港_竖屏_02",
        lora=None,
        seed=991401002,
        prompt=("ganyu_(genshin_impact), 1girl, solo, blue hair, horns, red eyes, "
                "bodysuit, detached sleeves, gold trim, "
                "liyue harbor, chinese architecture, harbor, wooden ships, red lanterns, "
                "night, full moon, reflections on water, fireworks in sky, "
                "looking at viewer, gentle smile"),
    ),
    dict(
        name="八重神子_鸣神大社_竖屏_03",
        lora=None,
        seed=991401003,
        prompt=("yae_miko_(genshin_impact), 1girl, solo, pink hair, fox ears, purple eyes, "
                "shrine maiden, japanese clothes, red hakama, "
                "grand narukami shrine, torii gate, stone stairs, cherry blossom trees, "
                "paper lanterns, petals falling, sunset, god rays, elegant"),
    ),
    dict(
        name="芙宁娜_枫丹廷_竖屏_04",
        lora=None,
        seed=991401004,
        prompt=("furina_(genshin_impact), 1girl, solo, white hair, blue eyes, hat, "
                "white coat, blue ribbon, "
                "court of fontaine, european architecture, fountain, plaza, marble steps, "
                "blue sky, fluffy clouds, birds, sunlight, elegant pose, looking at viewer"),
    ),
    dict(
        name="双人_雷电将军与八重神子_稻妻城_宽屏_05",
        lora=None, people=2, w=H_W, h=H_H,
        seed=991401005,
        prompt=("raiden_shogun_(genshin_impact), yae_miko_(genshin_impact), "
                "purple hair, long braid, pink hair, fox ears, purple eyes, "
                "japanese clothes, kimono, shrine maiden, red hakama, "
                "inazuma city, japanese architecture, cherry blossom trees, red torii, "
                "paper lanterns, festival stalls, night, fireworks in sky, "
                "standing side by side, looking at viewer"),
    ),
    dict(
        name="双人_甘雨与刻晴_璃月港_宽屏_06",
        lora=None, people=2, w=H_W, h=H_H,
        seed=991401006,
        prompt=("ganyu_(genshin_impact), keqing_(genshin_impact), "
                "blue hair, horns, purple hair, twin tails, "
                "bodysuit, detached sleeves, "
                "liyue harbor, chinese architecture, harbor, red lanterns, "
                "stone bridge, plum blossoms, night, festival, "
                "standing side by side, looking at viewer"),
    ),
]

# ─────────────── 任务表 B：多视图/三视图（白底，正面+侧面+背面） ───────────────
# 提示词不必写 multiple views —— build(mode="sheet") 已自动带
SHEET_JOBS = [
    dict(
        name="雷电将军_多视图_00",
        mode="sheet", w=MULTIVIEW_W, h=MULTIVIEW_H,
        lora=("raiden_shogun_anima_lora.safetensors", 1.0),
        seed=992101,
        prompt=("raiden_shogun_(genshin_impact), 1girl, purple hair, long braid, purple eyes, "
                "mole under eye, japanese clothes, kimono, hair ornament"),
    ),
    dict(
        name="甘雨_多视图_01",
        mode="sheet", w=MULTIVIEW_W, h=MULTIVIEW_H,
        lora=None,
        seed=993301,
        prompt=("ganyu_(genshin_impact), 1girl, blue hair, horns, red eyes, "
                "bodysuit, detached sleeves, gold trim"),
    ),
    dict(
        name="八重神子_多视图_02",
        mode="sheet", w=MULTIVIEW_W, h=MULTIVIEW_H,
        lora=None,
        seed=993302,
        prompt=("yae_miko_(genshin_impact), 1girl, pink hair, fox ears, purple eyes, "
                "shrine maiden, japanese clothes, red hakama"),
    ),
    dict(
        name="胡桃_多视图_03",
        mode="sheet", w=MULTIVIEW_W, h=MULTIVIEW_H,
        lora=None,
        seed=993303,
        prompt=("hu_tao_(genshin_impact), 1girl, brown hair, twin tails, red eyes, "
                "flower-shaped pupils, chinese clothes, black coat, hat"),
    ),
]

if __name__ == "__main__":
    sys.exit(main())
