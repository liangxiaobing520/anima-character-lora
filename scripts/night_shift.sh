#!/usr/bin/env bash
# ============================================================
# 夜间任务链（用户睡觉期间无人值守）
#
#   阶段 1  等 exp_res_v2.sh 收尾 —— furina 的 640 / 768 两组 LoRA
#   阶段 2  启动 ComfyUI -> 出 640 vs 768 逐张对照图（3 视角 × 2）
#   阶段 3  认领 768 产物为 furina 队列成品（免得队列重复训一遍；768 缺失则退回 640）
#   阶段 4  写交接报告
#   阶段 5  启动 train_batch.sh 全角色队列 @768
#
# 用法:
#   setsid nohup bash night_shift.sh > /tmp/night_shift.log 2>&1 < /dev/null &
# ============================================================
set -u

GD=/home/xiaozeng/lora_train/genshin_dataset
SCRIPTS=$GD/scripts
OUT=$GD/output
STATE=$GD/batch_state
VC=$GD/verify_compare
COMFY_LORAS=/home/xiaozeng/ComfyUI/models/loras
REPORT=$GD/NIGHT_REPORT.md
CHAR=furina

# 队列分辨率：2026-09-14 用户决定「就按 768 来」。
# 依据：furina 素材最小边采样中 ≥768 占 90%（中位 850），无需放大；
#       640 组保留只作对比基线。采集侧 min-side 仍保持 640——
#       10% 的图轻微放大对 LoRA 影响远小于「少收 10% 素材」的损失。
RES=768

mkdir -p "$STATE" "$VC"

say() { echo "[$(date '+%F %T')] $*"; }
fsize() { if [ -f "$1" ]; then du -h "$1" | cut -f1; else echo "缺失"; fi; }

say "=============================================================="
say "夜间任务链启动  队列分辨率=${RES}px"
say "=============================================================="

# ---------- 阶段 1: 等分辨率实验收尾 ----------
# pgrep 用 [x]xx 字符类写法规避自匹配 —— 裸模式 "exp_res_v2.sh" 会被
# 任何命令行里带这串字的进程(包括 ps|grep 监控)误命中，导致死等。
say "[1/5] 等 exp_res_v2.sh 结束(640 认领 + 768 训练)..."
waited=0
MAXWAIT=10800          # 3 小时硬上限，防止对端卡死导致整夜空转
while pgrep -f "[e]xp_res_v2\.sh" >/dev/null 2>&1; do
  if [ "$waited" -ge "$MAXWAIT" ]; then
    say "      等待超 ${MAXWAIT}s，不再等，按现状继续"
    break
  fi
  sleep 30; waited=$((waited+30))
  if [ $((waited % 600)) -eq 0 ]; then
    say "      仍在等待... ${waited}s  |  GPU $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"
  fi
done
say "      exp_res_v2 已结束(等了 ${waited}s)"

P768=$OUT/exp_${CHAR}_768.safetensors     # 队列分辨率产物，优先认领
P640=$OUT/exp_${CHAR}_640.safetensors     # 对比基线产物
say "      768 产物(队列用): $(fsize "$P768")"
say "      640 产物(对比用): $(fsize "$P640")"

# 安全网：768 组没产出（多半 OOM）说明这张 8G 卡扛不住 768 训练，
# 队列整体退回 640，否则 35 个角色会一个接一个撞同一堵墙。
if [ ! -f "$P768" ]; then
  RES=640
  say "      [WARN] 768 组未产出 -> 队列整体退回 ${RES}px"
fi

# ---------- 阶段 2: 出对比图 ----------
COMPARE_OK=0
if [ -f "$P640" ] && [ -f "$P768" ]; then
  say "[2/5] 启动 ComfyUI 出对比图..."
  bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1; sleep 8
  # 注意: 不能用 "cmd | tail" 判断退出码(管道会吞掉),所以先存变量再判
  START_OUT=$(bash /home/xiaozeng/bin/comfyui.sh start 2>&1); START_RC=$?
  echo "$START_OUT" | tail -3
  if [ "$START_RC" -eq 0 ] && curl -sf -o /dev/null -m 5 http://127.0.0.1:8188/; then
    cd "$SCRIPTS" || exit 1
    python3 compare_res.py "$CHAR" "$P640" "$P768" 640 768 2>&1 | tail -24
    COMPARE_OK=${PIPESTATUS[0]}
    say "      compare_res 退出码 $COMPARE_OK"
  else
    say "      ComfyUI 启动失败(rc=$START_RC)，跳过对比图"
  fi
  bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1; sleep 8
  say "      对比图: $(ls $VC/res_${CHAR}_*.png 2>/dev/null | wc -l) 张 -> $VC"
else
  say "[2/5] 产物不全，跳过对比图（768 组很可能是 OOM）"
fi

# ---------- 阶段 3: 认领队列分辨率产物,免得队列重复训 furina ----------
say "[3/5] 认领队列分辨率产物..."
# 只认领 768 组：640 产物分辨率与队列口径不一致，宁可让队列按当前 RES 重训，
# 也不拿低分辨率的顶包（否则 furina 一个角色跟其余 34 个不同源）。
if [ -f "$STATE/${CHAR}.done" ]; then
  say "      furina 已有 .done，跳过"
elif [ -f "$P768" ]; then
  cp -f "$P768" "$OUT/${CHAR}_anima_lora.safetensors"
  ln -sfn "$OUT/${CHAR}_anima_lora.safetensors" "$COMFY_LORAS/${CHAR}_anima_lora.safetensors"
  touch "$STATE/${CHAR}.done"
  say "      furina 已标记完成(768 组)。要重训: 删 $STATE/${CHAR}.done"
else
  say "      768 产物缺失，不认领 —— furina 留给队列按 ${RES}px 自己训"
fi

# ---------- 阶段 4: 写报告 ----------
{
  echo "# 夜间任务报告"
  echo
  echo "生成时间: $(date '+%F %T')"
  echo
  echo "## 分辨率 A/B 实验 (furina)"
  echo
  echo "| 组 | 文件 | 大小 | 用途 |"
  echo "|---|---|---|---|"
  if [ -f "$P768" ]; then
    echo "| 768 | \`$(basename "$P768")\` | $(du -h "$P768" | cut -f1) | 队列采用 |"
  else
    echo "| 768 | 缺失 | - | (可能 OOM) |"
  fi
  if [ -f "$P640" ]; then
    echo "| 640 | \`$(basename "$P640")\` | $(du -h "$P640" | cut -f1) | 对比基线 |"
  else
    echo "| 640 | 缺失 | - | - |"
  fi
  echo
  echo "训练参数: dim 32 / alpha 16 / 1000 步 / lr 1e-4 / AdamW8bit / bf16，仅分辨率不同"
  echo
  echo "### 逐张对照图"
  echo
  if ls "$VC"/res_${CHAR}_*.png >/dev/null 2>&1; then
    for v in front side back; do
      echo "- **$v**: \`$VC/res_${CHAR}_640_${v}.png\` vs \`$VC/res_${CHAR}_768_${v}.png\`"
    done
  else
    echo "(未生成 —— 产物不全或 ComfyUI 启动失败)"
  fi
  echo
  echo "同 prompt、同 seed、同 LoRA 强度 0.85，只有分辨率不同。"
  echo "看头发挑染、帽檐、领结这类小结构，哪组更稳。"
  echo
  echo "## 队列"
  echo
  echo "- 分辨率: **${RES}px**（用户决定；素材 ≥768 占 90%，无需放大）"
  echo "- 采集 min-side 仍为 640（保素材量，10% 轻微放大影响可忽略）"
  echo "- 日志: \`/tmp/train_batch.log\`"
  echo "- 单角色预计 ~50 分钟（768 比 640 慢约 1.44×）"
  echo
  echo "## 明早看这里"
  echo
  echo "1. \`$VC\` 里的对照图 —— 768 相对 640 的提升幅度，决定后续要不要统一口径"
  echo "2. \`/tmp/train_batch.log\` 末尾 —— 队列跑完了几个角色"
  echo "3. 本文件顶部时间戳 —— 夜班链路走到哪一步了"
  echo
} > "$REPORT"
say "[4/5] 报告已写 -> $REPORT"

# ---------- 阶段 5: 启动队列 ----------
say "[5/5] 启动全角色队列 @${RES}px ..."
say "      等待 GPU 完全空闲..."
gwait=0
while pgrep -f "[a]nima_train_network\.py" >/dev/null 2>&1; do
  if [ "$gwait" -ge 600 ]; then say "      等 GPU 超 10 分钟，强行继续"; break; fi
  sleep 20; gwait=$((gwait+20))
done
sleep 5
say "      GPU: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

cd "$SCRIPTS" || exit 1
export RES                                    # train_batch.sh 读 RES=${RES:-640}
say "      队列开始 —— 本脚本使命完成，后续进度看 /tmp/train_batch.log"
say "=============================================================="

exec bash "$SCRIPTS/train_batch.sh"
