# Anima Character LoRA Pipeline

基于 **Anima-Aesthetic** 底模 + [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts)
的角色 LoRA **采集 → 构建 → 批量训练 → 导出**全流水线。

已产出《原神》12 个、《凡人修仙传》8 个角色 LoRA，队列仍在跑，模型随 Releases 更新。

[模型下载](#-模型下载) · [快速开始](#-快速开始) · [训练参数](#-训练参数) · [踩坑记录](#-踩坑记录)

---

## ✨ 特性

| 能力 | 说明 |
|---|---|
| **多源采集** | booru 系（yande.re / safebooru）面向日系游戏；**360 图片搜索面向国漫**（booru 对国漫零收录） |
| **断点续传** | 采集按 URL / 图 ID 去重；训练按 `batch_state/<char>.done` 跳过。重跑任意次都是幂等的 |
| **一键构建** | `build_dataset.py` 用**硬链接**组织成 kohya 训练目录，不额外占磁盘 |
| **批量队列** | 自动串行、GPU 互斥等待、每轮回收 page cache；由 **systemd 托管**，重启 DSH 也不中断 |
| **小样本自适应** | 按实际素材量收敛步数（<60 张→300 步，<120 张→500 步），避免小数据集的 epoch 爆炸 |
| **自动导出** | 训练完自动软链到 ComfyUI `models/loras/`，出图立即可用 |

## 📦 模型下载

**20 个角色 LoRA**，每个约 **88 MB** —— `dim 32 / alpha 16 / 640px / bf16`。
全部在 [**Releases**](../../releases) 页面按角色下载（队列仍在训练，会继续追加）。

| 角色 | ID | 文件 | 大小 |
|---|---|---|---|
| **《原神》** | | | |
| 阿蕾奇诺 | `arlecchino` | `arlecchino_anima_lora.safetensors` | 88 MB |
| 优菈 | `eula` | `eula_anima_lora.safetensors` | 88 MB |
| 菲谢尔 | `fischl` | `fischl_anima_lora.safetensors` | 88 MB |
| 芙宁娜 | `furina` | `furina_anima_lora.safetensors` | 88 MB |
| 胡桃 | `hu_tao` | `hu_tao_anima_lora.safetensors` | 88 MB |
| 神里绫华 | `kamisato_ayaka` | `kamisato_ayaka_anima_lora.safetensors` | 88 MB |
| 刻晴 | `keqing` | `keqing_anima_lora.safetensors` | 88 MB |
| 莫娜 | `mona` | `mona_anima_lora.safetensors` | 88 MB |
| 雷电将军 | `raiden_shogun` | `raiden_shogun_anima_lora.safetensors` | 88 MB |
| 珊瑚宫心海 | `sangonomiya_kokomi` | `sangonomiya_kokomi_anima_lora.safetensors` | 88 MB |
| 申鹤 | `shenhe` | `shenhe_anima_lora.safetensors` | 88 MB |
| 八重神子 | `yae_miko` | `yae_miko_anima_lora.safetensors` | 88 MB |
| **《凡人修仙传》** | | | |
| 陈巧倩 | `chen_qiaoqian` | `chen_qiaoqian_anima_lora.safetensors` | 88 MB |
| 董宣儿 | `dong_xuaner` | `dong_xuaner_anima_lora.safetensors` | 88 MB |
| 墨彩环 | `mo_caihuan` | `mo_caihuan_anima_lora.safetensors` | 88 MB |
| 慕沛灵 | `mu_peiling` | `mu_peiling_anima_lora.safetensors` | 88 MB |
| 南宫婉 | `nangong_wan` | `nangong_wan_anima_lora.safetensors` | 88 MB |
| 银月 | `yin_yue` | `yin_yue_anima_lora.safetensors` | 88 MB |
| 元瑶 | `yuan_yao` | `yuan_yao_anima_lora.safetensors` | 88 MB |
| 紫灵 | `zi_ling` | `zi_ling_anima_lora.safetensors` | 88 MB |

**ComfyUI 用法**：把 `.safetensors` 放进 `ComfyUI/models/loras/`，然后在 prompt 里写

```
<lora:furina_anima_lora:0.85> furina_\(genshin_impact\), 1girl, solo, ...
```

> LoRA 权重建议 **0.8~0.9**。角色 LoRA 只记「角色是谁」（脸型 / 发色 / 瞳色），
> **服装配饰要写进 prompt**，且用训练 caption 里出现过的那套 tag。

## 📁 目录结构

```
genshin_dataset/
├── scripts/
│   ├── characters.json       角色表（id / 中文名 / booru tag / 是否跳过）
│   ├── collect.py            主采集器（booru 系）
│   ├── collect_fanren.py     国漫采集器（360 图片搜索）
│   ├── collect_concept.py    概念采集（国风 / 姿势）
│   ├── build_dataset.py      整理为 kohya 训练目录（硬链接 + caption 校验）
│   ├── train_lora.sh         单角色训练一条龙
│   ├── train_batch.sh        批量队列（断点续跑 / GPU 互斥 / 显存回收）
│   ├── queue_start.sh        队列入口（systemd 托管，幂等）
│   ├── reclaim_mem.sh        回收 page cache（WSL 专用）
│   └── mem_guard.sh          训练期间的内存守护
├── metadata/                 采集元数据与质检报告
├── raw/<角色id>/             ★ 采集原图 + 同名 .txt caption
├── train/by_character/<id>/  ★ 单角色训练集（硬链接）
├── train/mixed/              全角色混合集（训综合风格 LoRA）
├── output/                   ★ 训练产物（LoRA 权重，走 Releases）
└── logs/                     队列与单角色训练日志
```

## 🚀 快速开始

### 环境

```bash
# 1) 底模与配套模型
models/anima-base-v1.0.safetensors                              # Anima-Aesthetic 底模
ComfyUI/models/text_encoders/qwen_3_06b_base.safetensors        # 文本编码器
ComfyUI/models/vae/qwen_image_vae.safetensors                   # VAE

# 2) kohya sd-scripts
git clone https://github.com/kohya-ss/sd-scripts && cd sd-scripts
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

### 采集 → 构建 → 训练

```bash
# 采集（booru 系；国漫用 collect_fanren.py）
python3 scripts/collect.py --chars furina --per-char 300 --min-side 640

# 构建训练集（硬链接，可反复执行）
python3 scripts/build_dataset.py --solo-only --min-side 640

# 单角色训练：角色 id / epoch / 步数 / dim / 分辨率
bash scripts/train_lora.sh furina 0 800 32 640

# 批量队列（幂等，断点续跑）
bash scripts/queue_start.sh
```

## ⚙️ 训练参数

| 参数 | 值 | 说明 |
|---|---|---|
| 底模 | `anima-base-v1.0.safetensors` | Anima-Aesthetic |
| 网络 | LoRA（`networks.lora_anima`），**只训 UNet** | `--network_train_unet_only` |
| dim / alpha | **32 / 16** | 88 MB 产物 |
| 分辨率 | **640 × 640**（bucket 开启，`min_bucket 512`） | |
| batch size | 1 | + `--gradient_checkpointing` |
| 学习率 | **1e-4**（UNet），text encoder 不训 | `cosine` 调度，warmup 0 |
| 优化器 | `AdamW8bit` | 8G 显存友好 |
| 精度 | `bf16` | |
| 步数 | **按素材量自动**：<500 张→800 步；≥500→1000；≥800→1200；**<60 张→300；<120→500** | |
| 保存 | 每 2 epoch 存一次，最终导出 `<char>_anima_lora.safetensors` | |

单角色耗时：**约 26 分钟**（800 步 @ RTX 4060 Laptop 8G，≈2.0 s/it）。

## 🕳️ 踩坑记录

流水线里踩过的坑都固化成了代码逻辑，列几条对别人也有用的：

**① caption 文件名错位 —— 822 张图白采**
采集器写 `<md5>.txt`，而图片是 `<角色id>_<md5>.<ext>`。`build_dataset.py` 找的是
`<图片名>.txt`，于是 12 个角色的 caption 全部对不上 —— **训练集里 0 张图，日志却显示采集成功**。
现在构建阶段强制校验 caption 配对率。

**② `pgrep -f` 会匹配到自己**
等待脚本 `recollect_fanren.sh` 里的 `pgrep -f "[c]ollect_fanren"` 匹配到了**脚本自己的命令行**
（脚本名含该子串），死等自己结束 **1.5 小时**。现在一律用 `[c]ollect_fanren\.py` 锚定 python 进程，
或干脆 `ps -eo` 取全量再过滤。

**③ 双队列抢显存 → 直接 OOM**
队列在角色之间有一段约 40 秒的「无训练进程」窗口（构建数据集 + 停 ComfyUI），
两条队列的 60 秒轮询很容易同时命中 → 同时开训 → 8G 显存爆掉。
现在队列入口做了**防重入检查**，且切换队列必须等一个真实的训练间隙。

**④ 小样本的 epoch 爆炸**
`num_repeats=1` 时 **1 个 epoch 就等于数据集张数**。同一个「800 步」：
300 张图 = 2.7 epoch（正常），而 13 张图 = **61 epoch** —— LoRA 会退化成把那几十张背下来。
现在按素材量自动收敛步数，低于 20 张直接不训。

**⑤ 重启会杀掉所有后台任务**
`setsid nohup` 挡不住两件事：WSL 整体重启、以及**重启 DSH 时 `tmux kill-session` 清理进程树**。
一个跑了 7 个角色的队列就这么没的。现在队列交给 `systemd-run --user` 托管，
进程独立在 `user@1000.service/app.slice/` 下，重启不再受影响。

**⑥ booru 对国漫零收录**
yande.re / safebooru 搜《凡人修仙传》角色返回 0 结果。国漫素材改用 **360 图片搜索**
（`image.so.com/j?q=<关键词>`），并做「作品名+角色名+高清 → 裸角色名」的关键词回退 ——
后者通常能多出 2~20 倍候选量。

## ⚖️ 免责声明

- 本项目**仅用于个人学习与研究**，不涉及任何商业用途。
- 训练素材来自公开网络图源，角色形象版权归各作品方所有（《原神》© 米哈游 /《凡人修仙传》© 忘语及对应版权方）。
- 产出的 LoRA 权重仅供个人本地创作使用，请勿用于商业传播或任何侵犯原作者权益的场景。
- 采集器遵守各站点的访问频率限制，请自行控制并发与请求间隔。
