#!/usr/bin/env bash
# ============================================================
# 分辨率 A/B 实验:同一批数据、同一角色、同一步数,只改训练分辨率
#   A 组: furina @ 640  (当前配置)
#   B 组: furina @ 768  (待验证,可能 OOM)
# 产出: output/exp_furina_640.safetensors / exp_furina_768.safetensors
# 之后用 compare_res.py 同 prompt 同 seed 出图对比
# ============================================================
set -u

GD=/home/xiaozeng/lora_train/genshin_dataset
OUT=$GD/output
CHAR=furina
STEPS=1200
DIM=32

echo "=============================================================="
echo "分辨率 A/B 实验  角色=$CHAR  步数=$STEPS  dim=$DIM"
echo "开始 $(date '+%F %T')"
echo "=============================================================="

# 等 GPU 空闲(别的训练在跑就排队)
waited=0
while pgrep -f "anima_train_network.py" >/dev/null 2>&1; do
  if [ "$waited" -eq 0 ]; then echo "[$(date +%T)] GPU 被占用,排队中..."; fi
  sleep 30; waited=$((waited+30))
done
echo "[$(date +%T)] GPU 空闲 (等待 ${waited}s)"

# 腾显存
bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1
sleep 12
echo "[$(date +%T)] 当前显存: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

cd "$GD/scripts" || exit 1

for RES in 640 768; do
  echo ""
  echo "==================== 实验组: 分辨率 $RES ===================="
  rm -f "$OUT/${CHAR}_anima_lora.safetensors"
  echo "[$(date +%T)] 训练开始 @ ${RES}px"

  # 记录峰值显存:训练跑起来后后台采样
  ( for i in $(seq 1 200); do
      nvidia-smi --query-gpu=memory.used --format=csv,noheader >> "/tmp/mem_${RES}.log" 2>/dev/null
      sleep 10
    done ) &
  SAMPLER=$!

  bash train_lora.sh "$CHAR" 0 "$STEPS" "$DIM" "$RES" 2>&1 | tail -8
  RC=$?

  kill $SAMPLER 2>/dev/null
  wait $SAMPLER 2>/dev/null

  if [ -f "$OUT/${CHAR}_anima_lora.safetensors" ]; then
    mv "$OUT/${CHAR}_anima_lora.safetensors" "$OUT/exp_${CHAR}_${RES}.safetensors"
    PEAK=$(sort -t, -k1 -n "/tmp/mem_${RES}.log" 2>/dev/null | tail -1)
    echo "[$(date +%T)] OK ${RES} 组完成 | 峰值显存 $PEAK"
  else
    echo "[$(date +%T)] FAIL ${RES} 组无产物 (rc=$RC,可能是显存不足)"
  fi
done

echo ""
echo "=============================================================="
echo "实验训练阶段结束 $(date '+%F %T')"
ls -la "$OUT"/exp_* 2>/dev/null || echo "(无产物)"
echo "=============================================================="
