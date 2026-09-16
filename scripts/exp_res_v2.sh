#!/usr/bin/env bash
# ============================================================
# 分辨率对比(聪明版):复用已在跑的 640 组产物,只补跑 768
#
# 背景:队列被 kill 时它的 furina@640 训练已启动并成为孤儿继续跑,
#       与其丢弃重跑,不如认领为 640 组,省 50 分钟。
#
# 时序:等当前训练结束 -> 认领 640 产物 -> 补跑 768 -> 对比
# ============================================================
set -u

GD=/home/xiaozeng/lora_train/genshin_dataset
OUT=$GD/output
CHAR=furina
STEPS=1000          # 与孤儿训练保持一致,否则对比不公平
DIM=32

cd "$GD/scripts" || exit 1

echo "=============================================================="
echo "分辨率对比: 640(复用) vs 768(补跑)  角色=$CHAR  步数=$STEPS"
echo "开始 $(date '+%F %T')"
echo "=============================================================="

# ---------- 1) 等当前训练结束 ----------
echo "[$(date +%T)] 等当前训练结束(那个孤儿 furina@640)..."
waited=0
while pgrep -f "anima_train_network.py" >/dev/null 2>&1; do
  sleep 30; waited=$((waited+30))
done
echo "[$(date +%T)] GPU 空闲 (等了 ${waited}s)"

# ---------- 2) 认领 640 组产物 ----------
if [ -f "$OUT/${CHAR}_anima_lora.safetensors" ]; then
  mv "$OUT/${CHAR}_anima_lora.safetensors" "$OUT/exp_${CHAR}_640.safetensors"
  echo "[$(date +%T)] OK 640 组产物已认领: exp_${CHAR}_640.safetensors ($(du -h "$OUT/exp_${CHAR}_640.safetensors" | cut -f1))"
elif [ -f "$OUT/exp_${CHAR}_640.safetensors" ]; then
  echo "[$(date +%T)] 640 组已存在,直接用"
else
  echo "[$(date +%T)] WARN 没找到 640 产物,从头补跑"
  bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1; sleep 10
  bash train_lora.sh "$CHAR" 0 "$STEPS" "$DIM" 640 2>&1 | tail -5
  [ -f "$OUT/${CHAR}_anima_lora.safetensors" ] && \
    mv "$OUT/${CHAR}_anima_lora.safetensors" "$OUT/exp_${CHAR}_640.safetensors"
fi

# ---------- 3) 补跑 768 ----------
if [ ! -f "$OUT/exp_${CHAR}_768.safetensors" ]; then
  echo ""
  echo "==================== 768 组 ===================="
  bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1
  sleep 12
  echo "[$(date +%T)] 训练前显存: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

  # 后台采显存峰值
  rm -f /tmp/mem_768.log
  ( for i in $(seq 1 240); do
      nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr -d ' MiB' >> /tmp/mem_768.log 2>/dev/null
      sleep 10
    done ) &
  SAMPLER=$!

  echo "[$(date +%T)] 训练开始 @ 768px  ($(date '+%T'))"
  bash train_lora.sh "$CHAR" 0 "$STEPS" "$DIM" 768 2>&1 | tail -8
  RC=$?

  kill $SAMPLER 2>/dev/null
  wait $SAMPLER 2>/dev/null

  if [ -f "$OUT/${CHAR}_anima_lora.safetensors" ]; then
    mv "$OUT/${CHAR}_anima_lora.safetensors" "$OUT/exp_${CHAR}_768.safetensors"
    PEAK=$(sort -n /tmp/mem_768.log 2>/dev/null | tail -1)
    echo "[$(date +%T)] OK 768 组完成 | 峰值显存 ${PEAK} MiB"
  else
    echo "[$(date +%T)] FAIL 768 组无产物 (rc=$RC) —— 很可能是 OOM"
  fi
else
  echo "[$(date +%T)] 768 组已存在,跳过"
fi

echo ""
echo "=============================================================="
echo "实验结束 $(date '+%F %T')"
ls -la "$OUT"/exp_* 2>/dev/null || echo "(无产物)"
echo "=============================================================="
