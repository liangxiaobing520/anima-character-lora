#!/usr/bin/env bash
# ============================================================
# 批量角色 LoRA 队列:扩采 -> 训练 -> 导出到 ComfyUI
#
# 特性:
#   · 断点续跑 —— 完成的角色写 batch_state/<char>.done,重跑自动跳过
#   · 随时可停 —— kill 掉进程即可,已完成的不受影响
#   · 等 GPU   —— 每步前检查是否有其他训练在跑,避免抢显存 OOM
#   · 自动步数 —— 按实际数据量决定训练步数
#
# 用法:
#   setsid nohup bash train_batch.sh > /tmp/train_batch.log 2>&1 < /dev/null &
#   bash train_batch.sh furina hu_tao        # 只跑指定角色
#
# 环境变量覆盖:
#   TARGET_IMG=800 DIM=32 RES=768 bash train_batch.sh
#
# 分辨率(2026-09-16 用户决定): 队列统一走 **768**，与 train_lora.sh 的默认值对齐。
#   之前这里是 640，导致"单跑 768 / 队列 640"两套默认值并存、估工期按错的那套算。
#   代价：768 比 640 慢（实测约 50%~4 倍区间，取决于 bucket 分布），故本队列耗时显著变长。
# ============================================================
set -u

GD=/home/xiaozeng/lora_train/genshin_dataset
SCRIPTS=$GD/scripts
STATE=$GD/batch_state
mkdir -p "$STATE"

TARGET_IMG=${TARGET_IMG:-800}
DIM=${DIM:-32}
RES=${RES:-768}

CHARS="$*"
if [ -z "$CHARS" ]; then
  # booru 素材量 >= 300 的角色(按素材量降序),已训的 raiden_shogun 不在其中
  CHARS="furina hu_tao yae_miko kamisato_ayaka mona keqing arlecchino shenhe eula \
fischl sangonomiya_kokomi barbara jean lynette yoimiya xiangling ningguang citlali \
noelle kujou_sara navia clorinde yelan faruzan sucrose rosaria beidou chiori yun_jin \
mavuika lisa signora mualani kuki_shinobu charlotte"
fi

total=$(echo $CHARS | wc -w)
i=0; ok=0; skip=0; fail=0

count_img() {
  find "$GD/train/by_character/$1" -maxdepth 1 -type f \
    \( -name '*.jpg' -o -name '*.png' -o -name '*.webp' -o -name '*.jpeg' \) \
    2>/dev/null | wc -l
}

echo "=============================================================="
echo "批量角色 LoRA 队列  共 $total 个角色"
echo "目标素材 $TARGET_IMG 张/角色 | LoRA dim $DIM | 分辨率 $RES"
echo "开始时间 $(date '+%F %T')"
echo "=============================================================="

for c in $CHARS; do
  i=$((i+1))
  if [ -f "$STATE/$c.done" ]; then
    echo "[$i/$total] SKIP $c (已完成)"
    skip=$((skip+1)); continue
  fi

  echo ""
  echo "==================== [$i/$total] $c   $(date '+%F %T') ===================="

  # ---------- 1) 扩采 ----------
  cur=$(count_img "$c")
  if [ "$cur" -lt "$TARGET_IMG" ]; then
    echo "  [$(date +%T)] 扩采: $cur -> $TARGET_IMG"
    timeout 3600 python3 "$SCRIPTS/collect.py" --chars "$c" \
      --per-char "$TARGET_IMG" --min-side 640 2>&1 | tail -4
  else
    echo "  [$(date +%T)] 素材已够 ($cur 张),跳过采集"
  fi
  # ---------- 1.5) 构建训练集: raw/<char> -> train/by_character/<char> (硬链接) ----------
  # 关键:collect.py 采到的是 raw/,不跑 build_dataset 训练目录永远是旧的
  echo "  [$(date +%T)] 构建训练集(raw -> train/by_character)..."
  python3 "$SCRIPTS/build_dataset.py" --solo-only --min-side 640 2>&1 | tail -4

  cur2=$(count_img "$c")
  echo "  [$(date +%T)] 实际素材: $cur2 张"

  # ---------- 2) 按数据量定步数 ----------
  if   [ "$cur2" -ge 800 ]; then STEPS=1200
  elif [ "$cur2" -ge 500 ]; then STEPS=1000
  else                           STEPS=800
  fi
  echo "  [$(date +%T)] 计划训练 $STEPS 步"

  # ---------- 3) 等 GPU 空闲 ----------
  # pgrep 用 [a]nima... 字符类规避自匹配：裸模式会被任何命令行里带这串字的
  # 进程(ps|grep 监控、编辑器、本脚本被 cat 出来看时)误命中，导致死等。
  waited=0
  while pgrep -f "[a]nima_train_network\.py" >/dev/null 2>&1; do
    if [ "$waited" -eq 0 ]; then echo "  [$(date +%T)] GPU 被其他训练占用,排队等待..."; fi
    sleep 60; waited=$((waited+60))
  done
  if [ "$waited" -gt 0 ]; then echo "  [$(date +%T)] GPU 空闲(等了 ${waited}s)"; fi

  # ---------- 4) 停 ComfyUI 腾显存 ----------
  bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1
  sleep 15

  # ---------- 5) 训练 ----------
  echo "  [$(date +%T)] TRAIN 开始 ($STEPS 步)"
  bash "$SCRIPTS/train_lora.sh" "$c" 0 "$STEPS" "$DIM" "$RES" 2>&1 | tail -8

  # ---------- 6) 导出 ----------
  SRC="$GD/output/${c}_anima_lora.safetensors"
  if [ -f "$SRC" ]; then
    ln -sfn "$SRC" "/home/xiaozeng/ComfyUI/models/loras/${c}_anima_lora.safetensors"
    touch "$STATE/$c.done"
    echo "  [$(date +%T)] DONE $c  ($(du -h "$SRC" | cut -f1))"
    ok=$((ok+1))
  else
    echo "  [$(date +%T)] FAIL $c 无产物(不写标记,下次重试)"
    fail=$((fail+1))
  fi

  # ---------- 7) 把 page cache 还给 Windows ----------
  # 每轮训练都要读几百张图，page cache 涨起来后 Linux 会「自认内存紧张」，
  # 把 autoMemoryReclaim 的归还卡死，vmmemWSL 就越涨越高（实测能到 6G，
  # Windows 16G 只剩 2.2G 可用）。每轮清一次，宿主机就不会一直吃紧。
  # --quiet: 只 drop_caches，不等待不打印。
  bash "$SCRIPTS/reclaim_mem.sh" --quiet >/dev/null 2>&1
done

echo ""
echo "=============================================================="
echo "队列结束 $(date '+%F %T')"
echo "成功 $ok | 跳过 $skip | 失败 $fail | 共 $total"
echo "=============================================================="

# 收尾再清一次，把最后一轮的缓存也还掉
bash "$SCRIPTS/reclaim_mem.sh" --quiet >/dev/null 2>&1
