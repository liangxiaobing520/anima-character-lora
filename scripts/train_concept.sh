#!/usr/bin/env bash
# ============================================================
# Anima 通用概念 LoRA 训练（姿势 / 表情 / 动作 / 服装）
#   用法: train_concept.sh <概念名> [epochs] [max_steps] [dim] [resolution]
#   例:   train_concept.sh poses 0 1500 32 640
#
# 与 train_lora.sh 的区别：
#   · 数据来自 concept_loras/<name>/（全站随机角色，去角色化 caption）
#   · keep_tokens = 0 —— 没有触发词要保护，全部 tag 自由打乱，学概念而非位置
#   · 训练量按步数控制（数据量大，epochs 不直观）
# 前置: 训练独占显存 -> 先停 ComfyUI
# ============================================================
set -euo pipefail

SD=/home/xiaozeng/sd-scripts
PY=$SD/.venv/bin/python
ROOT=/home/xiaozeng/lora_train
BASE=$ROOT/models/anima-base-v1.0.safetensors
QWEN3=/home/xiaozeng/ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors
VAE=/home/xiaozeng/ComfyUI/models/vae/qwen_image_vae.safetensors

NAME=${1:?用法: train_concept.sh <概念名> [epochs] [max_steps] [dim] [resolution]}
EPOCHS=${2:-0}
MAXSTEPS=${3:-1500}
DIM=${4:-32}
RES=${5:-640}
MAXBUCKET=${5:-640}

DATA="$ROOT/genshin_dataset/concept_loras/$NAME"
OUT="$ROOT/genshin_dataset/concept_loras/output"
CFG="$ROOT/genshin_dataset/concept_loras/train_${NAME}.toml"
LOGDIR="$ROOT/genshin_dataset/concept_loras/logs"
mkdir -p "$OUT" "$LOGDIR"

[ -d "$DATA" ] || { echo "❌ 找不到概念目录: $DATA"; exit 1; }
N=$(find "$DATA" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.webp' \) | wc -l)
[ "$N" -gt 0 ] || { echo "❌ $NAME 没有图片"; exit 1; }
for f in "$BASE" "$QWEN3" "$VAE"; do
  [ -f "$f" ] || { echo "❌ 缺模型文件: $f"; exit 1; }
done
if pgrep -f "[m]ain.py --listen" >/dev/null; then
  echo "⚠️  ComfyUI 还在跑，显存不够训练。请先停止 ComfyUI"; exit 1
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
keep_tokens = 0

[[datasets]]
resolution = [$RES, $RES]
batch_size = 1
enable_bucket = true

  [[datasets.subsets]]
  image_dir = "$DATA"
  caption_extension = ".txt"
  num_repeats = 1
EOF

if [ "$MAXSTEPS" -gt 0 ]; then
  STEP_ARGS="--max_train_steps $MAXSTEPS"
  TOTAL="$MAXSTEPS 步"
else
  STEP_ARGS="--max_train_epochs $EPOCHS"
  TOTAL="$(( N * EPOCHS )) 步"
fi

echo "=========================================="
echo "概念    : $NAME     图片 $N 张"
echo "训练量  : $TOTAL"
echo "分辨率  : $RES (bucket ≤ $MAXBUCKET)   LoRA dim $DIM"
echo "输出    : $OUT/${NAME}_anima_lora.safetensors"
echo "=========================================="

cd "$SD"
"$PY" anima_train_network.py \
  --pretrained_model_name_or_path "$BASE" \
  --qwen3 "$QWEN3" \
  --vae "$VAE" \
  --dataset_config "$CFG" \
  --output_dir "$OUT" \
  --output_name "${NAME}_anima_lora" \
  --logging_dir "$LOGDIR/tb_${NAME}" \
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
  2>&1 | tee "$LOGDIR/train_${NAME}.log"

echo
echo "✅ 训练结束。产物:"
ls -la "$OUT"/*.safetensors 2>/dev/null | tail -5
