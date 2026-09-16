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
EXTRA = "looking at viewer, smile, simple background"


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
        params = {"characters": cid, "filename": "%s_验收" % name, "extra": EXTRA}
        print("[%d/%d] %s" % (i, len(targets), tag), flush=True)
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
