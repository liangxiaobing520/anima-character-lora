#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 raw/ 里的采集结果整理成 kohya 可训练的数据集

产出：
  train/mixed/            所有角色混合（硬链接，不占额外空间）-> 训"原神女角色"综合 LoRA
  train/by_character/<id>/ 每角色独立（硬链接）              -> 训单角色 LoRA
  metadata/dataset_report.json  统计报告
  train/kohya_mixed.toml   kohya 训练配置模板

可选过滤：
  --min-side N      最短边下限
  --portrait-only   只要竖构图（全身立绘倾向）
  --sfw-only        只要安全内容（排除露点/性行为）
  --max-per-char N  每角色上限（按分辨率优先）
"""
import argparse
import hashlib
import json
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
RAW = os.path.join(ROOT, "raw")
META = os.path.join(ROOT, "metadata")
TRAIN = os.path.join(ROOT, "train")

NSFW_MARK = {
    "nude", "naked", "nipples", "pussy", "penis", "cum", "anal", "vaginal", "sex",
    "oral", "fellatio", "paizuri", "masturbation", "censored", "uncensored",
    "topless", "bottomless", "underboob", "sideboob", "no_bra", "nopan", "anus",
    "sex_toy", "bondage", "tentacles", "rape", "dildo", "vibrator",
}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# 非默认服装（此前的底模探测结论：LoRA 学"默认服装成套"最有效，这套图可选择性剔除）
ALT_COSTUME = {
    "alt_costume", "official_costume", "alternate_costume", "alternate_outfit",
    "new_year's_outfit", "swimsuit", "bikini", "wedding_dress",
    "maid", "nurse", "school_uniform", "cheerleader", "santa_costume",
    "halloween_costume", "casual", "modern_clothes", "suit",
}
FULL_BODY_MARK = {"full_body", "standing", "full_body_request"}
# 多角色同框：只信 booru 的显式人数/关系标签。
# 绝不能改成"猜 _(genshin_impact) 条目"——那里面混着神之眼(vision)、元素符号
# (hydro_symbol)、武器、食物，甚至角色皮肤(ganyu_(twilight_blossom))，
# 按名字判会把"芙宁娜拿着神之眼"当成同框图删掉，实测误判超过一半。
MULTI_MARK = {
    "2girls", "3girls", "4girls", "5girls", "6+girls", "multiple_girls",
    "2boys", "3boys", "multiple_boys", "1boy", "1male", "1other",
    "siblings", "twins", "sisters", "brothers", "group", "couple",
}
# 特色配饰（帽子/头饰类）：这些是"角色识别度"的关键，但在 booru 数据里
# 往往只占 20~30%，不加权会被素颜图淹没。命中的图会另建一份 <角色>_hat 子集，
# train_lora.sh 检测到就给它 2x 重复次数。
HAT_MARK = {
    "hat", "top_hat", "chef_hat", "green_hat", "winter_hat", "witch_hat",
    "bonnet", "hood", "blue_hood", "beret", "cap", "headwear",
    "hair_ornament", "hairband", "blue_hairband",
}


def multi_reason(tags):
    """多角色同框判定；命中返回标签名，干净则 None。

    只认显式人数/关系标签。故意不做"出现别的原神角色名"判定：
    该判定在本数据集误判过半（vision 872 次、hydro_symbol 61 次、
    各类角色皮肤 400+ 次），会把干净的单人图大量误删。
    """
    hit = tags & MULTI_MARK
    return sorted(hit)[0] if hit else None


def img_size(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def link(src, dst):
    """优先硬链接；跨设备则复制"""
    if os.path.exists(dst):
        return True
    try:
        os.link(src, dst)
        return True
    except OSError:
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-side", type=int, default=900)
    ap.add_argument("--portrait-only", action="store_true")
    ap.add_argument("--sfw-only", action="store_true")
    ap.add_argument("--max-per-char", type=int, default=0, help="0=不限制")
    # 依此前底模探测结论：LoRA 学到"默认服装成套"最有效，非默认服装(alt_costume)建议降权剔除
    ap.add_argument("--drop-alt-costume", action="store_true",
                    help="剔除 alt_costume / official_costume 等非默认服装图")
    ap.add_argument("--full-body-only", action="store_true",
                    help="只要 caption 里显式带 full_body/standing 的图")
    ap.add_argument("--solo-only", action="store_true",
                    help="剔除多角色同框（Ngirls 标签，或出现别的原神角色名）")
    ap.add_argument("--out", default="mixed")
    args = ap.parse_args()

    chars = []
    if os.path.exists(os.path.join(BASE, "characters.json")):
        with open(os.path.join(BASE, "characters.json"), encoding="utf-8") as f:
            chars = [c for c in json.load(f)["characters"] if not c.get("skip")]
    cn_map = {c["id"]: c["cn"] for c in chars}

    for d in (TRAIN, os.path.join(TRAIN, "by_character"), os.path.join(TRAIN, args.out), META):
        os.makedirs(d, exist_ok=True)

    report, total = [], 0
    seen_hash = {}          # md5 -> 已被哪个角色收录（跨角色去重）
    dup_cross = 0
    for char_id in sorted(os.listdir(RAW)):
        cdir = os.path.join(RAW, char_id)
        if not os.path.isdir(cdir):
            continue
        imgs = [f for f in os.listdir(cdir) if f.lower().endswith(IMG_EXT)]
        cands = []
        n_multi = 0
        for f in imgs:
            p = os.path.join(cdir, f)
            txt = os.path.join(cdir, os.path.splitext(f)[0] + ".txt")
            if not os.path.exists(txt):
                continue
            caption = open(txt, encoding="utf-8").read().strip()
            tags = set(caption.replace(",", " ").split())
            w, h = img_size(p)
            if min(w, h) < args.min_side:
                continue
            if args.portrait_only and h < w * 1.15:
                continue
            if args.sfw_only and (tags & NSFW_MARK):
                continue
            if args.drop_alt_costume and (tags & ALT_COSTUME):
                continue
            if args.full_body_only and not (tags & FULL_BODY_MARK):
                continue
            multi = multi_reason(tags)
            if multi:
                n_multi += 1
                if args.solo_only:
                    continue
            # 跨角色重复：同一张图已归给别的角色 -> 跳过（避免训练时同图多标签打架）
            try:
                with open(p, "rb") as fh:
                    h_md5 = hashlib.md5(fh.read()).hexdigest()
            except Exception:
                h_md5 = ""
            if h_md5 and h_md5 in seen_hash and seen_hash[h_md5] != char_id:
                dup_cross += 1
                continue
            cands.append((f, w, h, bool(tags & NSFW_MARK), h_md5))

        # 高分辨率优先
        cands.sort(key=lambda x: -(x[1] * x[2]))
        if args.max_per_char:
            cands = cands[:args.max_per_char]

        # 单角色目录
        cdir_out = os.path.join(TRAIN, "by_character", char_id)
        os.makedirs(cdir_out, exist_ok=True)
        # 混合目录
        mdir_out = os.path.join(TRAIN, args.out)

        n_nsfw = 0
        for f, w, h, is_nsfw, h_md5 in cands:
            if h_md5:
                seen_hash[h_md5] = char_id
            src = os.path.join(cdir, f)
            stem = os.path.splitext(f)[0]
            link(src, os.path.join(cdir_out, f))
            link(os.path.join(cdir, stem + ".txt"), os.path.join(cdir_out, stem + ".txt"))
            link(src, os.path.join(mdir_out, "%s_%s" % (char_id, f)))
            link(os.path.join(cdir, stem + ".txt"),
                 os.path.join(mdir_out, "%s_%s.txt" % (char_id, stem)))
            n_nsfw += is_nsfw
        total += len(cands)
        # 自动建"特色加权子集"：把带帽子/头饰的图再硬链接一份到 <角色>_hat，
        # train_lora.sh 检测到该目录就给它 2x 重复次数。
        # 数据一张不删，只调频率——这是让低频特色特征能被学到的正确姿势。
        hat_dir = os.path.join(TRAIN, "by_character", char_id + "_hat")
        if os.path.isdir(hat_dir):
            # 保留 .npz 缓存，只清旧的图/标注。
            # 必须容错：两条队列切换时可能有两个 build_dataset 并发清理同一目录，
            # listdir 拿到的快照里会混进已被对方删掉的文件。
            # （2026-09-15 实际撞到过 FileNotFoundError 让整个 build 挂掉，
            #   而 build 失败会直接中断训练队列。）
            for fn in os.listdir(hat_dir):
                if fn.endswith(".npz"):
                    continue
                try:
                    os.remove(os.path.join(hat_dir, fn))
                except FileNotFoundError:
                    pass
        n_hat = 0
        for f, w, h, is_nsfw, h_md5 in cands:
            stem = os.path.splitext(f)[0]
            txt = os.path.join(cdir, stem + ".txt")
            try:
                tags = set(open(txt, encoding="utf-8").read().strip().replace(",", " ").split())
            except Exception:
                continue
            if not (tags & HAT_MARK):
                continue
            os.makedirs(hat_dir, exist_ok=True)
            link(os.path.join(cdir, f), os.path.join(hat_dir, f))
            link(txt, os.path.join(hat_dir, stem + ".txt"))
            n_hat += 1

        report.append({"id": char_id, "cn": cn_map.get(char_id, ""), "kept": len(cands),
                       "raw": len(imgs), "nsfw": n_nsfw, "multi": n_multi, "hat": n_hat})
        print("%-22s 收录 %3d / 原始 %3d  (NSFW %d, 同框 %d, 特色 %d)" %
              (char_id, len(cands), len(imgs), n_nsfw, n_multi, n_hat), flush=True)

    # kohya 配置模板（指向混合目录）
    toml = """[general]
enable_bucket = true
bucket_no_upscale = false
bucket_reso_steps = 64

[[datasets]]
resolution = [768, 768]
batch_size = 1

  [[datasets.subsets]]
  image_dir = "%s"
  caption_extension = ".txt"
  num_repeats = 1
""" % os.path.join(TRAIN, args.out)
    with open(os.path.join(TRAIN, "kohya_%s.toml" % args.out), "w", encoding="utf-8") as f:
        f.write(toml)

    with open(os.path.join(META, "dataset_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    n_files = len([f for f in os.listdir(os.path.join(TRAIN, args.out))
                   if f.lower().endswith(IMG_EXT)])
    print("\n=== 完成 ===")
    print("混合目录 %s: %d 张（含 caption）" % (args.out, n_files))
    print("单角色目录: %d 个角色" % len(report))
    print("kohya 配置: train/kohya_%s.toml" % args.out)


if __name__ == "__main__":
    main()
