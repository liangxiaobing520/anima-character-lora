#!/usr/bin/env bash
# ============================================================
# 768 分辨率单角色验证
#
# 目的：在 8G 卡上确认 768 训练能否跑通（显存余量仅约 0.6G，必须实测）
#
# 做三件事：
#   ① 停掉正在跑的 640 队列（systemd unit lora-queue）
#   ② 用 train_lora_768.sh 跑一个角色，全程采样显存峰值
#   ③ 打印结论：峰值 / 是否 OOM / 每步耗时 / 产物
#
# 用法：
#   bash verify_768.sh              # 默认用 furina（素材最多 751 张）
#   bash verify_768.sh raiden_shogun
#
# 注意：跑完不会自动恢复队列——确认结果后由你决定下一步
# ============================================================
set -u
GD=/home/xiaozeng/lora_train/genshin_dataset
CHAR=${1:-furina}
STEPS=${2:-400}          # 验证用不着跑满，400 步足够看显存与速度
RES=768
MEMLOG=/home/xiaozeng/lora_train/mem_768_verify.log

echo "==================== 768 验证 ===================="
echo "角色: $CHAR   步数: $STEPS   分辨率: $RES"
echo

# ---------- 0) 当前 GPU 状态 ----------
echo "[$(date +%T)] 当前 GPU:"
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader | sed 's/^/    /'

# ---------- 1) 停 640 队列 ----------
if systemctl --user is-active --quiet lora-queue 2>/dev/null; then
  echo
  echo "[$(date +%T)] 停掉 640 队列（跑完当前这步才生效）..."
  systemctl --user stop lora-queue
  # 等训练进程真正退出
  for i in $(seq 1 30); do
    pgrep -f "[a]nima_train_network" >/dev/null 2>&1 || break
    sleep 5
  done
  echo "[$(date +%T)] 队列已停，GPU 释放"
  nvidia-smi --query-gpu=memory.used --format=csv,noheader | sed 's/^/    显存: /'
fi
# 顺手停 ComfyUI 腾显存
bash /home/xiaozeng/bin/comfyui.sh stop >/dev/null 2>&1
sleep 5

# ---------- 2) 起显存采样 ----------
: > "$MEMLOG"
( while true; do
    nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader,nounits 2>/dev/null >> "$MEMLOG"
    sleep 3
  done ) &
SAMPLER=$!
echo
echo "[$(date +%T)] 显存采样已启动 (pid $SAMPLER，每 3 秒一次)"
echo "[$(date +%T)] 开始训练 $STEPS 步 @ ${RES}px ..."
echo

# ---------- 3) 跑训练 ----------
T0=$(date +%s)
bash "$GD/scripts/train_lora_768.sh" "$CHAR" 0 "$STEPS" 32 "$RES" 2>&1 \
  | grep -vE "it/s\]|s/it\]" | tail -25
RC=$?
T1=$(date +%s)

kill "$SAMPLER" 2>/dev/null
wait "$SAMPLER" 2>/dev/null

# ---------- 4) 结论 ----------
echo
echo "==================== 结论 ===================="
echo "耗时: $(( (T1-T0)/60 )) 分 $(( (T1-T0)%60 )) 秒"
python3 - "$MEMLOG" "$STEPS" "$((T1-T0))" <<'PY'
import sys
log, steps, dur = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
vals = []
for line in open(log):
    p = line.strip().split(",")
    if len(p) == 2:
        try: vals.append((int(p[0]), int(p[1])))
        except ValueError: pass
if not vals:
    print("  ⚠️ 没采到显存数据")
    raise SystemExit
peak = max(v[0] for v in vals)
avg_util = sum(v[1] for v in vals)/len(vals)
print(f"  显存峰值: {peak} MiB / 8188 MiB   （余量 {8188-peak} MiB）")
print(f"  GPU 平均利用率: {avg_util:.0f}%")
print(f"  平均每步: {dur/steps:.2f} s/it")
if peak >= 8100:
    print("  ⚠️ 贴着天花板——正式跑长步数有 OOM 风险")
elif peak >= 7900:
    print("  ✅ 能跑，但余量很小（<300 MiB）")
else:
    print("  ✅ 余量充足")
PY

echo
echo "产物:"
ls -lh "$GD/output/${CHAR}_anima_lora-768.safetensors" 2>/dev/null | sed 's/^/  /' || echo "  ❌ 未产出（可能 OOM 或仍在中途）"
echo
echo "中途保存的检查点（可选删）:"
ls -1 "$GD/output/${CHAR}_anima_lora-768-"*.safetensors 2>/dev/null | sed 's/^/  /' | head -5
echo
echo "训练日志: $GD/logs/train_${CHAR}_768.log"
echo "显存曲线: $MEMLOG"
echo
echo "⚠️ 640 队列已停，如需继续跑原队列：systemctl --user start lora-queue"
