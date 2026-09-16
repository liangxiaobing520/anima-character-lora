#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量角色验收图 —— 每个已训练完成的角色出一张全身立绘，检查 LoRA 效果

用法:
  python3 gen_all_chars.py                  # 全部已完成角色（batch_state/*.done）
  python3 gen_all_chars.py hu_tao zi_ling   # 只跑指定角色
产物: /home/xiaozeng/deepseek工作区/图片生成/角色验收/
"""
import glob
import json
import os
import shutil
import subprocess
import sys

GD = "/home/xiaozeng/lora_train/genshin_dataset"
SCRIPT = os.path.join(GD, "scripts", "studio_gen.py")
OUT_DIR = "/home/xiaozeng/deepseek工作区/图片生成"
DEST = os.path.join(OUT_DIR, "角色验收")

# 视角锁定 + 穿着要求。训练素材里俯视/背面/裸露构图占比高，LoRA 会把这种倾向带出来
# （技能踩坑 6：LoRA 权重会压过 prompt 里的构图词）。所以正向显式锁平视正面、
# 负向压掉其他机位与裸露，否则实测大部分图是俯视、背面甚至全裸。
EXTRA = ("from front, eye level, straight-on, facing viewer, looking at viewer, smile, "
         "fully clothed, simple background")
NEG_EXTRA = ("from above, looking down, high angle, from below, low angle, foreshortening, "
             "from behind, back view, wide angle, dutch angle, head out of frame, "
             "nude, naked, topless, bottomless, nipples, pussy, uncensored, "
             "underwear, lingerie, bikini, swimsuit")

# 姿势按角色轮换（用户 2026-09-16 反馈"怎么都是站立"）。
# 姿势名必须是 studio_gen.py POSES 表里的合法值，否则会 KeyError；
# 动作细节走 extra，用 danbooru 通用 tag。
# 刻意回避 spread_legs / all_fours / lying 等不适合验收立绘的姿势，
# 也不放 looking_back / bent_over —— 会和上面锁视角的 from behind 压制词打架。
POSE_CYCLE = [
    ("standing",        "hand_on_hip"),
    ("sitting",         "legs_crossed"),
    ("standing",        "waving"),
    ("walking",         "hair_flip"),
    ("kneeling",        "holding_sword"),
    ("running",         ""),
    ("squatting",       "peace_sign"),
    ("standing",        "arms_crossed"),
    ("sitting",         "hand_on_cheek"),
    ("leaning_forward", "hand_on_hip"),
    ("standing",        "holding_sword"),
    ("sitting",         "legs_crossed"),
    ("walking",         "waving"),
    ("standing",        "covering_mouth"),
    ("standing",        "stretching"),
]

# 各角色标志性造型。不点名服装时模型自由发挥（实测胡桃穿成黑毛衣+牛仔裤，甚至直接裸体）。
# 全部用 danbooru 通用 tag，与训练 caption 同一套词表。
OUTFIT = {
    "arlecchino":         "white_jacket, black_pants, gloves",
    "barbara":            "white_dress, nun, cross_necklace",
    "eula":               "white_jacket, black_shorts, thighhighs, cape",
    "fischl":             "eyepatch, black_dress, purple_cape, twintails",
    "furina":             "top_hat, blue_coat, shorts, bowtie",
    "hu_tao":             "porkpie_hat, chinese_clothes, brown_jacket, black_shorts, twin_braids",
    "jean":               "white_shirt, blue_skirt, cape",
    "kamisato_ayaka":     "japanese_clothes, hair_ornament, white_dress",
    "keqing":             "purple_dress, thighhighs, hair_ornament",
    "lynette":            "cat_ears, maid, white_apron, hair_ribbon",
    "mona":               "witch_hat, black_dress, thighhighs, cape",
    "sangonomiya_kokomi": "japanese_clothes, bow, hair_ornament",
    "shenhe":             "chinese_clothes, white_dress, hair_ornament",
    "xiangling":          "chinese_clothes, hair_flower, white_shirt",
    "yae_miko":           "fox_ears, japanese_clothes, shrine_maiden",
    "yoimiya":            "japanese_clothes, hair_flower, hair_ribbon",
}
# 凡人修仙传角色：素材 caption 里没有服装描述（只有 id/作品/1girl/solo），用通用仙侠服装
FANREN_OUTFIT = "chinese_clothes, hanfu, ancient_chinese_clothes, long_hair"


def cn_map():
    try:
        with open(os.path.join(GD, "scripts", "characters.json"), encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    rows = data if isinstance(data, list) else data.get("characters", [])
    return {r.get("id"): r.get("cn") for r in rows if isinstance(r, dict) and r.get("id")}


def done_chars():
    return sorted(os.path.basename(p)[:-5]
                  for p in glob.glob(os.path.join(GD, "batch_state", "*.done")))


def main():
    targets = sys.argv[1:] or done_chars()
    cn = cn_map()
    os.makedirs(DEST, exist_ok=True)
    ok, fail = [], []
    for i, cid in enumerate(targets, 1):
        name = cn.get(cid) or cid
        tag = "%s(%s)" % (name, cid)
        outfit = OUTFIT.get(cid) or FANREN_OUTFIT
        pose, action = POSE_CYCLE[(i - 1) % len(POSE_CYCLE)]
        extra = EXTRA + ", " + outfit
        if action:
            extra += ", " + action
        params = {"characters": cid, "filename": "%s_验收" % name,
                  "pose": pose, "extra": extra, "negative": NEG_EXTRA}
        cw = os.environ.get("CHAR_LORA_WEIGHT")
        if cw:
            params["char_lora_weight"] = float(cw)
        print("[%d/%d] %s  pose=%s/%s  outfit=%s"
              % (i, len(targets), tag, pose, action or "-", outfit), flush=True)
        try:
            r = subprocess.run(["python3", SCRIPT, "--params", "-"],
                               input=json.dumps(params), capture_output=True,
                               text=True, timeout=900,
                               cwd=os.path.join(GD, "scripts"))
        except subprocess.TimeoutExpired:
            print("   ❌ 超时", flush=True)
            fail.append(tag)
            continue
        line = ""
        for ln in reversed((r.stdout or "").strip().splitlines()):
            if ln.strip().startswith("{"):
                line = ln
                break
        try:
            out = json.loads(line)
        except Exception:
            print("   ❌ 输出异常: %s" % ((r.stderr or r.stdout or "")[-300:]), flush=True)
            fail.append(tag)
            continue
        if out.get("ok"):
            for src in out.get("images", []):
                dst = os.path.join(DEST, os.path.basename(src))
                shutil.copy2(src, dst)
                print("   ✅ %s" % dst, flush=True)
            ok.append(tag)
        else:
            print("   ❌ %s" % out.get("error"), flush=True)
            fail.append(tag)
    print("\n===== 完成: %d 成功 / %d 失败 =====" % (len(ok), len(fail)), flush=True)
    if fail:
        print("失败: " + " ".join(fail), flush=True)


if __name__ == "__main__":
    main()
