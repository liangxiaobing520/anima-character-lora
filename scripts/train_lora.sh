#!/usr/bin/env bash
# ============================================================
# Anima 单角色 LoRA 训练一条龙
#   用法: train_lora.sh <角色id> [epochs] [max_steps] [dim] [resolution] [max_bucket]
#   例:   train_lora.sh raiden_shogun 8 0 32 768
#         train_lora.sh raiden_shogun 0 1500 32 640     # 按步数训练(epochs 传 0)
# 前置: 训练独占显存 -> 先停 ComfyUI:  pkill -f "[m]ain.py --listen"
# 注意: max_train_steps 与 max_train_epochs 同时传时 epochs 会覆盖 steps，
#       本脚本按"传了 steps 就只传 steps"处理。
# ============================================================
set -euo pipefail

SD=/home/xiaozeng/sd-scripts
PY=$SD/.venv/bin/python
GD=/home/xiaozeng/lora_train/genshin_dataset
BASE=/home/xiaozeng/lora_train/models/anima-base-v1.0.safetensors
QWEN3=/home/xiaozeng/ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors
VAE=/home/xiaozeng/ComfyUI/models/vae/qwen_image_vae.safetensors

CHAR=${1:?用法: train_lora.sh <角色id> [epochs] [max_steps] [dim] [resolution] [max_bucket]}
EPOCHS=${2:-8}
MAXSTEPS=${3:-0}
DIM=${4:-32}
RES=${5:-768}
MAXBUCKET=${6:-$RES}

DATA="$GD/train/by_character/$CHAR"
OUT="$GD/output"
CFG="$GD/train/train_${CHAR}.toml"
LOGDIR="$GD/logs"
mkdir -p "$OUT" "$LOGDIR"

[ -d "$DATA" ] || { echo "❌ 找不到角色目录: $DATA"; exit 1; }
N=$(find "$DATA" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.webp' \) | wc -l)
[ "$N" -gt 0 ] || { echo "❌ $CHAR 没有图片"; exit 1; }
for f in "$BASE" "$QWEN3" "$VAE"; do
  [ -f "$f" ] || { echo "❌ 缺模型文件: $f"; exit 1; }
done
if pgrep -f "[m]ain.py --listen" >/dev/null; then
  echo "⚠️  ComfyUI 还在跑，显存不够训练。请先: pkill -f \"[m]ain.py --listen\""; exit 1
fi

# 可选加权子集：存在 by_character/<char>_hat 时，给"带帽子"的图 2 倍重复。
# 理由：帽子/礼帽这类配饰在 booru 数据里是低频标签（实测 furina 仅 21%），
# 不加权会被大量无帽图淹没，LoRA 学不到"帽子属于这个角色"。
HAT_DATA="$GD/train/by_character/${CHAR}_hat"
HAT_BLOCK=""
if [ -d "$HAT_DATA" ]; then
  HAT_N=$(find "$HAT_DATA" -maxdepth 1 -name '*.txt' 2>/dev/null | wc -l)
  if [ "$HAT_N" -gt 0 ]; then
    HAT_BLOCK="
  [[datasets.subsets]]
  image_dir = \"$HAT_DATA\"
  caption_extension = \".txt\"
  num_repeats = 2"
    echo "加权子集  : ${CHAR}_hat  $HAT_N 张 x2"
  fi
fi

cat > "$CFG" <<EOF
[general]
enable_bucket = true
bucket_no_upscale = false
bucket_reso_steps = 64
min_bucket_reso = 512
max_bucket_reso = $MAXBUCKET
caption_extension = ".txt"
shuffle_caption = true
keep_tokens = 1

[[datasets]]
resolution = [$RES, $RES]
batch_size = 1
enable_bucket = true

  [[datasets.subsets]]
  image_dir = "$DATA"
  caption_extension = ".txt"
  num_repeats = 1
$HAT_BLOCK
EOF

# ---------- 小样本自动降步数（2026-09-16）----------
# 360 图源对冷门国漫角色收录有限（林银屏 13 张、柳乐儿 32 张、甘九真 49 张）。
# 拿 800 步去训 13 张图 = 60 个 epoch，LoRA 会退化成"把这几十张背下来"，
# 一换姿势/服装就崩。按素材量收敛步数，让有效 epoch 落在 5~8 的合理区间。
CAP=0
if   [ "$N" -lt 60 ];  then CAP=300
elif [ "$N" -lt 120 ]; then CAP=500
fi
if [ "$MAXSTEPS" -gt 0 ] && [ "$CAP" -gt 0 ] && [ "$MAXSTEPS" -gt "$CAP" ]; then
  echo "⚠️  小样本降步数: $MAXSTEPS → $CAP（仅 $N 张图，避免过拟合）"
  MAXSTEPS=$CAP
fi

# steps 与 epochs 互斥：指定 steps 时不再传 epochs（否则 epochs 会覆盖 steps）
if [ "$MAXSTEPS" -gt 0 ]; then
  STEP_ARGS="--max_train_steps $MAXSTEPS"
  TOTAL="$MAXSTEPS 步(上限)"
else
  STEP_ARGS="--max_train_epochs $EPOCHS"
  TOTAL="$(( N * EPOCHS )) 步"
fi

echo "=========================================="
echo "角色    : $CHAR     图片 $N 张"
echo "训练量  : $TOTAL"
echo "分辨率  : $RES (bucket ≤ $MAXBUCKET)   LoRA dim $DIM"
echo "输出    : $OUT/${CHAR}_anima_lora.safetensors"
echo "=========================================="

cd "$SD"
"$PY" anima_train_network.py \
  --pretrained_model_name_or_path "$BASE" \
  --qwen3 "$QWEN3" \
  --vae "$VAE" \
  --dataset_config "$CFG" \
  --output_dir "$OUT" \
  --output_name "${CHAR}_anima_lora" \
  --logging_dir "$LOGDIR/tb_${CHAR}" \
  --network_module networks.lora_anima \
  --network_dim "$DIM" \
  --network_alpha $((DIM / 2)) \
  --network_train_unet_only \
  --network_dropout 0.0 \
  --resolution "$RES,$RES" \
  --train_batch_size 1 \
  $STEP_ARGS \
  --learning_rate 1e-4 \
  --unet_lr 1e-4 \
  --text_encoder_lr 0 \
  --optimizer_type AdamW8bit \
  --lr_scheduler cosine \
  --lr_warmup_steps 0 \
  --mixed_precision bf16 \
  --save_precision bf16 \
  --save_model_as safetensors \
  --gradient_checkpointing \
  --cache_latents_to_disk \
  --sdpa \
  --split_attn \
  --max_data_loader_n_workers 2 \
  --persistent_data_loader_workers \
  --seed 42 \
  --save_every_n_epochs 2 \
  --no_metadata \
  2>&1 | tee "$LOGDIR/train_${CHAR}.log"

echo
echo "✅ 训练结束。产物:"
ls -la "$OUT"/*.safetensors 2>/dev/null | tail -5
