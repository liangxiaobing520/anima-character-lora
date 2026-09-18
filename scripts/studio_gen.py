#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片工作室·出图引擎 —— 供 dsh-image-studio 插件调用

单一数据源：菜单定义(MENU_*)与 prompt 拼装都在本文件里，
Node 侧通过 `studio_gen.py --menu` 拿可选项，避免两边映射不同步。

用法:
  python3 studio_gen.py --menu                      # 输出菜单 JSON
  python3 studio_gen.py --params p.json             # 按参数出图 -> 结果 JSON
  python3 studio_gen.py --params p.json --dry-run   # 只拼 prompt，不出图
  echo '<json>' | python3 studio_gen.py -           # 参数从 stdin 读

stdout 只输出单行 JSON；日志一律走 stderr。
"""
from neg_policy import neg_safety, NEG_MINOR, NEG_STYLE  # 画风开关: ANIMA_ALLOW_3D=1 或 --allow-3d
import argparse
import json
import os
import random
import shutil
import sys
import time
import urllib.error
import urllib.request

COMFY = "http://127.0.0.1:8188"
COMFY_OUT = "/home/xiaozeng/ComfyUI/output"
LORA_ROOT = "/home/xiaozeng/ComfyUI/models/loras"
OUT_DIR = "/home/xiaozeng/deepseek工作区/图片生成"
CHAR_LORA_DIR = "/home/xiaozeng/lora_train/genshin_dataset/output"
CONCEPT_LORA_DIR = "/home/xiaozeng/lora_train/genshin_dataset/concept_loras/output"

V_W, V_H = 832, 1216      # 竖屏单人立绘
H_W, H_H = 1216, 832      # 宽屏多人
S_W, S_H = 1536, 1024     # 多视图/三视图（每格像素更多，手不糊）

# ───────────────────────── 基础词 ─────────────────────────
Q = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
     "illustration, 2d, (detailed face:1.3), beautiful detailed eyes, ")

FULL_BODY_POS = "full body, standing, from head to toe, feet visible, "
# 用户明确指定了非站立姿势(sitting/lying/kneeling...)时用这条:
# 否则 standing 会和姿势词打架,把人物拽回站立
FULL_BODY_POS_NOSTAND = "full body, from head to toe, feet visible, "
FULL_BODY_NEG = (", close-up, portrait, upper body, half body, cowboy shot, "
                 "cropped legs, cropped, headshot, zoom in")
SOLO_NEG = "(extra people:1.4), (2girls:1.3), duplicate, "
# 2026-09-16 修复：单人分支此前从不发 1girl —— 而训练 caption 全是 "1girl, solo"，
# train/inference 的 token 对不上，会让 LoRA 的性别信号漂移
# （实测燕如嫣新 LoRA 的标准立绘被画成男装人物）。现在默认带上主体词 + 性别反向负面。
SUBJECT_DEFAULT = "1girl, solo, female, "
GENDER_NEG = "1boy, male, man, "
HAND_POS = "perfect hands, detailed hands, five fingers, "
HAND_NEG = ("bad hands, poorly drawn hands, extra fingers, missing fingers, fused fingers, "
            "mutated hands, malformed hands, claw shaped fingers, ")

MULTIVIEW_POS = ("multiple views, character sheet, reference sheet, front view, side view, "
                 "back view, full body, standing, white background, simple background, "
                 + HAND_POS)

# ── 纯风景/建筑模式(画面无人物) ──
# 关键差异:不要 detailed face / beautiful eyes(没人可画),改加强景深与场景;
# 负向必须压制一切人物词,否则模型会往空镜里硬塞一个人
Q_SCENERY = ("masterpiece, best quality, score_7, absurdres, highly detailed, anime style, "
             "illustration, 2d, scenery, no humans, landscape, depth of field, ")
SCENERY_NEG = ("1girl, 1boy, person, people, solo, human, face, portrait, "
               "full body, standing, close-up, ")


# 底线：未成年词永远锁死(从 neg_policy 来)；画风压制可切
NEG_SAFETY = NEG_MINOR + NEG_STYLE  # 向后兼容；实际取值走 neg_safety()
NEG_QUALITY = ("worst quality, low quality, score_1, score_2, score_3, blurry, "
               "jpeg artifacts, bad anatomy, fused bodies, color bleeding, "
               "extra limbs, extra digits, deformed, disfigured, mutated, ")

# ───────────────────────── 菜单定义 ─────────────────────────
CHARACTERS = {
    "arlecchino": "阿蕾奇诺", "barbara": "芭芭拉", "beidou": "北斗",
    "candace": "坎蒂丝", "charlotte": "夏洛蒂", "chasca": "恰斯卡",
    "chiori": "千织", "citlali": "茜特菈莉", "clorinde": "克洛琳德",
    "dehya": "迪希雅", "emilie": "艾梅莉埃", "escoffier": "爱可菲",
    "eula": "优菈", "faruzan": "珐露珊", "fischl": "菲谢尔",
    "furina": "芙宁娜", "ganyu": "甘雨", "hu_tao": "胡桃",
    "iansan": "伊安珊", "jean": "琴", "kamisato_ayaka": "神里绫华",
    "keqing": "刻晴", "kujou_sara": "九条裟罗", "kuki_shinobu": "久岐忍",
    "lan_yan": "蓝砚", "layla": "莱依拉", "lisa": "丽莎",
    "lumine": "荧", "lynette": "琳妮特", "mavuika": "玛薇卡",
    "mona": "莫娜", "mualani": "玛拉妮", "navia": "娜维娅",
    "nilou": "妮露", "ningguang": "凝光", "noelle": "诺艾尔",
    "raiden_shogun": "雷电将军", "rosaria": "罗莎莉亚",
    "sangonomiya_kokomi": "珊瑚宫心海", "shenhe": "申鹤",
    "signora": "女士", "skirk": "丝柯克", "sucrose": "砂糖",
    "varesa": "瓦蕾莎", "xiangling": "香菱", "xianyun": "闲云",
    "xilonen": "希诺宁", "yae_miko": "八重神子", "yanfei": "烟绯",
    "yelan": "夜兰", "yoimiya": "宵宫", "yun_jin": "云堇",
}


# 从训练工程的角色表补充非原神角色（凡人修仙传等），避免两处维护。
# characters.json 与本脚本同目录；文件缺失/格式异常时静默跳过，不影响原有功能。
def _merge_external_chars():
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters.json")
    try:
        with open(_p, encoding="utf-8") as _f:
            _rows = json.load(_f)
    except Exception:
        return
    if isinstance(_rows, dict):
        _rows = _rows.get("characters", [])
    for _r in (_rows if isinstance(_rows, list) else []):
        if isinstance(_r, dict) and _r.get("id") and _r.get("cn"):
            CHARACTERS.setdefault(_r["id"], _r["cn"])   # 已硬编码的原神角色不覆盖


_merge_external_chars()

# 角色 LoRA：训练输出目录里存在 {tag}_anima_lora.safetensors 就自动登记，
# 不必每训完一个新角色都回来改这张表。要换文件或调强度，写进 CHAR_LORA_OVERRIDES。
CHAR_LORA_WEIGHT = 0.85          # 角色 LoRA 默认强度
CHAR_LORA_FILE_FMT = "%s_anima_lora.safetensors"
CHAR_LORA_OVERRIDES = {          # 显式覆盖，优先级最高
    "raiden_shogun": ("raiden_shogun_anima_lora.safetensors", 0.85),
}


def char_lora_for(tag):
    """该角色是否已有训好的 LoRA -> (文件名, 强度)；没训过则 None。"""
    if tag in CHAR_LORA_OVERRIDES:
        return CHAR_LORA_OVERRIDES[tag]
    fname = CHAR_LORA_FILE_FMT % tag
    if os.path.isfile(os.path.join(CHAR_LORA_DIR, fname)):
        return (fname, CHAR_LORA_WEIGHT)
    return None

POSES = {
    "standing": "站立", "sitting": "坐姿", "kneeling": "跪姿",
    "squatting": "蹲姿", "lying": "侧躺", "on_back": "仰卧",
    "all_fours": "四肢着地", "bent_over": "弯腰", "arms_up": "举手",
    "spread_legs": "张腿", "running": "奔跑", "jumping": "跳跃",
    "straddling": "骑跨", "walking": "行走", "leaning_forward": "前倾",
}

EXPRESSIONS = {
    "smile": "微笑", "grin": "咧嘴笑", "open_mouth": "张嘴",
    "blush": "脸红", "half-closed_eyes": "半眯眼", "closed_eyes": "闭眼",
    "crying": "哭泣", "angry": "生气", "surprised": "惊讶",
    "expressionless": "无表情", "embarrassed": "害羞", "seductive": "挑逗",
    "smirk": "坏笑", "parted_lips": "微启唇",
}

OUTFITS = {
    "casual": ("便服", "casual clothes, t-shirt, jeans"),
    "kimono": ("和服", "japanese clothes, kimono, floral print"),
    "yukata": ("浴衣", "yukata, sash, summer festival"),
    "dress": ("连衣裙", "dress, frills"),
    "evening_gown": ("晚礼服", "evening gown, elegant, jewelry"),
    "maid": ("女仆装", "maid outfit, apron, maid headdress"),
    "school_uniform": ("校服", "school uniform, pleated skirt, necktie"),
    "swimsuit": ("泳装", "swimsuit, one-piece swimsuit"),
    "bikini": ("比基尼", "bikini, side-tie bikini bottom"),
    "hanfu": ("汉服", "hanfu, chinese clothes, wide sleeves"),
    "cheongsam": ("旗袍", "cheongsam, qipao, side slit"),
    "armor": ("铠甲", "armor, breastplate, gauntlets"),
    "suit": ("西装", "business suit, necktie, formal"),
    "lingerie": ("内衣", "lingerie, lace, garter belt"),
    "nude": ("全裸", "completely nude, nipples, navel"),
    "topless": ("上半裸", "topless, bare breasts, nipples"),
}

SCENES = {
    "inazuma_castle": ("稻妻城·天守阁",
        "inazuma city, tenshukaku, japanese castle, purple sky, cherry blossoms, lanterns"),
    "narukami_shrine": ("鸣神大社",
        "narukami shrine, torii gate, stone stairs, sacred sakura tree, petals falling"),
    "liyue_harbor": ("璃月港夜景",
        "liyue harbor, night, chinese architecture, lanterns, fireworks, sea"),
    "fontaine_court": ("枫丹廷",
        "fontaine, palais mermonia, european architecture, fountain, cloudy sky"),
    "mondstadt": ("蒙德城",
        "mondstadt, windmills, medieval town, blue sky, white clouds, pigeons"),
    "sumeru_forest": ("须弥雨林",
        "sumeru, rainforest, giant trees, glowing mushrooms, green light"),
    "snezhnaya_snow": ("至冬雪原",
        "snowfield, blizzard, frozen lake, aurora, ice crystals"),
    "dragonspine": ("龙脊雪山",
        "dragonspine, snowy mountain, pine trees, cold mist, ice"),
    "seirai_island": ("清籁岛",
        "seirai island, thunderstorm, purple lightning, ruined shrine"),
    "hanachirusato": ("花见坂·祭典",
        "inazuma festival, paper lanterns, food stalls, night, fireworks"),
    "beach": ("海滩黄昏",
        "beach, sunset, ocean waves, golden hour, seagulls"),
    "onsen": ("温泉",
        "onsen, hot spring, steam, rocks, night, moon"),
    "bedroom": ("卧室",
        "bedroom, bed, soft lighting, curtains, warm lamp"),
    "bamboo_forest": ("竹林",
        "bamboo forest, dappled sunlight, green, mist"),
    "flower_field": ("花海",
        "flower field, blooming flowers, butterflies, bright sky"),
    "white_bg": ("纯白背景", "white background, simple background, studio lighting"),
}

FRAMINGS = {
    # 纯风景/建筑档(people=0 -> 走 scenery 模式,不拼任何人物词)
    "scenic_h":    ("风景横版", 0, 1216, 832),
    "scenic_wide": ("风景宽幅", 0, 1536, 864),
    "solo_v":  ("单人竖版", 1, V_W, V_H),
    "solo_h":  ("单人横版", 1, H_W, H_H),
    "duo_h":   ("双人横版", 2, H_W, H_H),
    "trio_h":  ("三人横版", 3, H_W, H_H),
    "quad_h":  ("四人横版", 4, H_W, H_H),
    "sheet":   ("三视图/角色卡", 1, S_W, S_H),
}

LORA_NOTES = {
    "anima_artiststylemix_3": "画风混合 3",
    "anima_artiststylemix_4": "画风混合 4",
    "anima_artiststylemix_5": "画风混合 5",
    "anima_artiststylemix_6": "画风混合 6",
    "anima_artiststylemix_7": "画风混合 7",
    "anima_bathroom_deepthroat": "浴室·深喉",
    "anima_bathroom_paizuri": "浴室·乳交",
    "anima_breeding_mount_restraints": "骑乘·拘束",
    "anima_breeding_season_purple": "发情期·紫",
    "anima_breeding_slave": "繁殖·奴",
    "anima_ethereal_penis": "灵体·阴茎",
    "anima_futanari_down_bulge": "扶他·下凸",
    "anima_futanari_side_bulge": "扶他·侧凸",
    "anima_futanari_up_bulge": "扶他·上凸",
    "anima_milf_saggy_breasts": "熟女·垂乳",
    "anima_pov_paizuri_twisted": "POV·乳交",
    "anima_pregnant_veiny_belly": "孕妇·青筋肚",
    "anima_tentacle_oviposition": "触手·产卵",
}


# ───────────────────────── 工具函数 ─────────────────────────
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def ensure_char_lora(tag):
    """把角色 LoRA 从训练输出目录软链进 ComfyUI loras 目录。"""
    entry = char_lora_for(tag)
    if entry is None:
        return None
    fname, weight = entry
    src = os.path.join(CHAR_LORA_DIR, fname)
    dst = os.path.join(LORA_ROOT, fname)
    if not os.path.exists(src):
        log("   ⚠️ 角色 LoRA 不存在: %s" % src)
        return None
    if not os.path.exists(dst):
        try:
            os.symlink(src, dst)
            log("   🔗 已链接角色 LoRA: %s" % fname)
        except OSError as e:
            log("   ⚠️ 链接失败 %s: %s" % (fname, e))
            return None
    return (fname, weight)


def available_loras():
    out = []
    if not os.path.isdir(LORA_ROOT):
        return out
    for f in sorted(os.listdir(LORA_ROOT)):
        if not f.endswith(".safetensors"):
            continue
        if not f.startswith("anima_"):
            continue
        key = f[:-len(".safetensors")]
        out.append({"name": f, "note": LORA_NOTES.get(key, key)})
    return out


def build_menu():
    chars = []
    for tag, name in sorted(CHARACTERS.items(), key=lambda kv: kv[1]):
        entry = {"tag": tag, "name": name}
        got = char_lora_for(tag)
        if got:
            entry["lora"] = got[0]
            entry["lora_weight"] = got[1]
        chars.append(entry)
    return {
        "characters": chars,
        "poses": [{"tag": k, "name": v} for k, v in POSES.items()],
        "expressions": [{"tag": k, "name": v} for k, v in EXPRESSIONS.items()],
        "outfits": [{"tag": k, "name": v[0]} for k, v in OUTFITS.items()],
        "scenes": [{"tag": k, "name": v[0]} for k, v in SCENES.items()],
        "framings": [{"tag": k, "name": v[0], "people": v[1], "w": v[2], "h": v[3]}
                     for k, v in FRAMINGS.items()],
        "loras": available_loras(),
        "defaults": {"framing": "solo_v", "steps": 32, "cfg": 4.5, "count": 1},
    }


def resolve(table, key, label):
    """把 tag 或中文名都解析回 tag。"""
    key = str(key).strip()
    if key in table:
        return key
    for tag, val in table.items():
        name = val[0] if isinstance(val, (tuple, list)) else val
        if name == key:
            return tag
    raise KeyError("未知%s: %r" % (label, key))


def make_filename(p):
    """自动生成中文文件名:角色_姿势_服装_场景。
    用户显式传 filename 时优先用用户的。"""
    parts = []
    chars = p.get("characters") or []
    if isinstance(chars, str):
        chars = [c.strip() for c in chars.replace("，", ",").split(",") if c.strip()]
    for c in chars:
        try:
            parts.append(CHARACTERS[resolve(CHARACTERS, c, "角色")])
        except KeyError:
            parts.append(str(c))
    for key, table, label in (("pose", POSES, "姿势"), ("outfit", OUTFITS, "服装"),
                              ("scene", SCENES, "场景")):
        v = str(p.get(key) or "").strip()
        if v and v not in ("none", "无", "-"):
            try:
                val = table[resolve(table, v, label)]
                parts.append(val[0] if isinstance(val, (tuple, list)) else val)
            except KeyError:
                pass
    if p.get("framing") in ("scenic_h", "scenic_wide"):
        f = FRAMINGS.get(str(p.get("framing")))
        if f:
            parts.append(f[0])
    return "_".join(parts) if parts else (p.get("filename") or "studio")


def build_prompt(p):
    """把选择拼成 (正向, 负向, 宽, 高, people, mode)。"""
    framing = p.get("framing") or "solo_v"
    framing = resolve(FRAMINGS, framing, "画幅")
    fname, fpeople, w, h = FRAMINGS[framing]
    mode = "sheet" if framing == "sheet" else "single"

    tags = []

    # 角色：>=2 个按多人处理
    chars = p.get("characters") or []
    if isinstance(chars, str):
        chars = [c for c in chars.replace("，", ",").split(",") if c.strip()]
    char_tags = []
    for c in chars:
        c = c.strip()
        if not c:
            continue
        char_tags.append(resolve(CHARACTERS, c, "角色"))
    people = max(fpeople, len(char_tags)) if char_tags else fpeople

    # 姿势
    pose = p.get("pose") or ""
    pose_tags = []
    if pose:
        for x in str(pose).replace("，", ",").split(","):
            x = x.strip()
            if x and x not in ("none", "无", "-"):
                pose_tags.append(resolve(POSES, x, "姿势"))

    # 表情
    expr = p.get("expression") or ""
    expr_tag = None
    if expr and expr not in ("none", "无", "-"):
        expr_tag = resolve(EXPRESSIONS, expr.strip(), "表情")

    # 服装
    outfit = p.get("outfit") or ""
    outfit_prompt = ""
    if outfit and outfit not in ("none", "无", "-"):
        otag = resolve(OUTFITS, outfit.strip(), "服装")
        outfit_prompt = OUTFITS[otag][1]

    # 场景
    scene = p.get("scene") or ""
    scene_prompt = ""
    if scene and scene not in ("none", "无", "-"):
        stag = resolve(SCENES, scene.strip(), "场景")
        scene_prompt = SCENES[stag][1]

    # 纯风景:不走人物那套(无 full body / 无 detailed face),直接拼场景词
    if people <= 0:
        scenic = []
        if scene_prompt:
            scenic.append(scene_prompt)
        ex = (p.get("extra") or "").strip()   # 注意:全局的 extra 定义在下方,此处局部取
        if ex:
            scenic.append(ex)
        pos_s = Q_SCENERY + ", ".join(scenic)
        neg_s = NEG_QUALITY + neg_safety() + SCENERY_NEG
        neg_extra_s = (p.get("negative") or "").strip().strip(",").strip()
        if neg_extra_s:
            neg_s = neg_s.rstrip().rstrip(",").rstrip() + ", " + neg_extra_s + ", "
        return pos_s, neg_s, w, h, 0, "scenery"

    # 组装正向:有明确姿势时不要 standing(否则和 sitting/lying 打架)
    body = FULL_BODY_POS if (not pose_tags or pose_tags == ["standing"]) else FULL_BODY_POS_NOSTAND
    if mode == "sheet":
        pos = Q + MULTIVIEW_POS
    elif people > 1:
        pos = Q + "%dgirls, multiple girls, " % people + body
    else:
        pos = Q + SUBJECT_DEFAULT + body
    if char_tags:
        tags.append(" ".join(char_tags))
    if pose_tags:
        tags.append(", ".join(pose_tags))
    if expr_tag:
        tags.append(expr_tag)
    if outfit_prompt:
        tags.append(outfit_prompt)
    if scene_prompt:
        tags.append(scene_prompt)
    extra = (p.get("extra") or "").strip()
    if extra:
        tags.append(extra)
    pos = pos + ", ".join(tags)

    # 组装负向
    #   neg_mode="free" -> 只留「质量词 + 底线 + 自定义词」，构图排除/手部/多人排除
    #   三块固定词全部去掉，构图完全交给调用方控制。
    #   底线 NEG_MINOR(child/kid/loli/shota/minor) 两种模式都强制保留，不开放修改。
    neg = NEG_QUALITY + NEG_MINOR
    if str(p.get("neg_mode") or "").strip().lower() != "free":
        neg = NEG_QUALITY + neg_safety() + HAND_NEG
        if mode != "sheet" and people <= 1:
            neg += SOLO_NEG
        neg += FULL_BODY_NEG
    # 单人主体为女性时压掉男性特征 —— 两种模式都加：性别不是构图，防漂移是刚需
    if mode != "sheet" and people <= 1:
        neg += GENDER_NEG
    neg_extra = (p.get("negative") or "").strip().strip(",").strip()
    if neg_extra:
        # 各固定块结尾不一定带分隔符（FULL_BODY_NEG 就以 "zoom in" 收尾），
        # 统一在拼接前补齐，避免出现 "zoom inFROM_ABOVE_TEST" 这种粘连。
        neg = neg.rstrip().rstrip(",").rstrip() + ", " + neg_extra + ", "

    return pos, neg, w, h, people, mode


def build_workflow(pos, neg, w, h, seed, steps, cfg, loras):
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
            "filename_prefix": "studio", "images": ["8", 0]}},
    }
    # LoRA 链式叠加（原脚本只支持 1 个，这里改成链）
    prev = ["44", 0]
    for i, (lname, lw) in enumerate(loras):
        nid = str(46 + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": prev, "lora_name": lname, "strength_model": lw}}
        prev = [nid, 0]
    if loras:
        wf["31"]["inputs"]["model"] = prev
    return wf


def submit(wf):
    data = json.dumps({"prompt": wf}).encode()
    req = urllib.request.Request(COMFY + "/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["prompt_id"]


def wait_output(pid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        with urllib.request.urlopen("%s/history/%s" % (COMFY, pid), timeout=20) as r:
            h = json.loads(r.read())
        if pid in h:
            for _n, o in h[pid].get("outputs", {}).items():
                for im in o.get("images", []):
                    return os.path.join(COMFY_OUT, im["filename"])
            return None  # KSampler Fault 偶发
    return None


def gen_one(p, loras, idx, seed=None):
    pos, neg, w, h, people, mode = build_prompt(p)
    steps = int(p.get("steps") or 32)
    cfg = float(p.get("cfg") or 4.5)
    seed = int(seed if seed is not None else (p.get("seed") or random.randint(1, 2**31 - 1)))
    wf = build_workflow(pos, neg, w, h, seed, steps, cfg, loras)

    if p.get("dry_run"):
        return {"ok": True, "dry": True, "prompt": pos, "negative": neg,
                "w": w, "h": h, "seed": seed, "loras": loras}

    last_err = ""
    for attempt in (1, 2):
        try:
            pid = submit(wf)
        except urllib.error.HTTPError as e:
            last_err = "提交失败 %s: %s" % (e.code, e.read().decode()[:500])
            log("   ❌ %s" % last_err)
            if attempt == 2:
                return {"ok": False, "error": last_err}
            time.sleep(3)
            continue
        t0 = time.time()
        src = wait_output(pid)
        if src and os.path.exists(src):
            os.makedirs(OUT_DIR, exist_ok=True)
            base = p.get("filename") or make_filename(p)
            dst = os.path.join(OUT_DIR, "%s_%02d.png" % (base, idx))
            shutil.copy2(src, dst)
            el = time.time() - t0
            log("   ✅ %s (%.0fs)" % (dst, el))
            return {"ok": True, "path": dst, "seed": seed, "elapsed": round(el),
                    "prompt": pos, "w": w, "h": h}
        last_err = "无输出（KSampler Fault 偶发）"
        log("   ⚠️ 第 %d 次无输出，重试…" % attempt)
    return {"ok": False, "error": last_err, "seed": seed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", action="store_true")
    ap.add_argument("--params")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-comfy-check", action="store_true")
    ap.add_argument("--allow-3d", action="store_true",
                    help="放开 3D/写实画风(默认压制,保持二次元)")
    args = ap.parse_args()

    if args.allow_3d:
        os.environ["ANIMA_ALLOW_3D"] = "1"

    if args.menu:
        print(json.dumps(build_menu(), ensure_ascii=False))
        return 0

    if not args.params:
        print(json.dumps({"ok": False, "error": "缺少 --params 或 --menu"}))
        return 1

    if args.params == "-":
        raw = sys.stdin.read()
    else:
        with open(args.params, "r", encoding="utf-8") as f:
            raw = f.read()
    p = json.loads(raw)
    if args.dry_run:
        p["dry_run"] = True

    # 角色 LoRA + 用户自选 LoRA
    loras = []
    chars = p.get("characters") or []
    if isinstance(chars, str):
        chars = [c.strip() for c in chars.replace("，", ",").split(",") if c.strip()]
    cw = p.get("char_lora_weight")      # 临时压低角色 LoRA 强度（构图被 LoRA 带偏时用）
    for c in chars:
        try:
            tag = resolve(CHARACTERS, c, "角色")
        except KeyError:
            continue
        got = ensure_char_lora(tag)
        if got:
            if cw is not None:
                got = (got[0], float(cw))
            loras.append(got)
    for item in (p.get("loras") or []):
        if isinstance(item, str):
            loras.append((item if item.endswith(".safetensors") else item + ".safetensors", 0.5))
        elif isinstance(item, dict) and item.get("name"):
            nm = item["name"]
            if not nm.endswith(".safetensors"):
                nm += ".safetensors"
            loras.append((nm, float(item.get("weight", 0.5))))

    if not p.get("dry_run") and not args.no_comfy_check:
        try:
            with urllib.request.urlopen(COMFY + "/system_stats", timeout=8) as r:
                st = json.loads(r.read())
            log("ComfyUI 就绪: %s" % st.get("system", {}).get("comfyui_version", "?"))
        except Exception as e:
            print(json.dumps({"ok": False,
                              "error": "ComfyUI 未启动或不可达 (%s): %s" % (COMFY, e)},
                             ensure_ascii=False))
            return 1

    count = int(p.get("count") or 1)
    results = []
    for i in range(1, count + 1):
        results.append(gen_one(p, loras, i))

    out = {"ok": all(r.get("ok") for r in results), "count": len(results),
           "dry": bool(p.get("dry_run")),
           "images": [r["path"] for r in results if r.get("ok") and r.get("path")],
           "results": results, "loras": loras}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
