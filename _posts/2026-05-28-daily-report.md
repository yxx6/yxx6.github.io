---
layout: single
title: "推荐算法日报 2026-05-28"
date: 2026-05-28 08:00:00 +0800
permalink: /daily/2026-05-28/
paper_count: 2
share: false
related: false
read_time: false
comments: false
topics:
  - "cs.IR"
---

## 今日概述



## 论文列表（共 2 篇）

### 1. ACE: Anisotropy-Controllable Embedding for LLM-enhanced Sequential Recommendation

<div class="paper-card">
<div class="paper-authors">Dongcheol Lee、Hye-young Kim、Jongwuk Lee</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2605.29322v1" target="_blank">arXiv:2605.29322v1</a> · 2026-05-28</div>
</div>

**论文定位**
这篇论文聚焦 LLM 增强序列推荐（Sequential Recommendation）中的**embedding 几何失衡问题**。具体来说，LLM-as-Extractor 范式下，LLM 生成的物品 embedding 存在严重的**各向异性（Anisotropy）**——绝大多数向量聚集在狭窄锥形区域内，沿少数主导方向分布，导致物品表示多样性丧失。这使得在下游微调时，这些富含语义的 embedding 难以有效适配协同信号。已有方法要么忽略这个问题（LLM2X、LLMEmb），要么用白化操作强行等向化（WhitenRec+），后者虽消除了各向异性，却抹平了反映语义重要性的奇异值谱层次，造成语义失真。ACE 的核心差异在于**提供连续可控的各向异性调节能力**——既缓解几何失衡，又保留语义层次结构。

**核心架构**
整体数据流：**物品文本元数据 → LLM Encoder → 𝐄 ∈ ℝⁿˣᵈ（原始各向异性 embedding 矩阵）→ ACE 线性自编码器 → 𝐄_ACE ∈ ℝⁿˣᵈ（几何校准后的 embedding 矩阵）→ PCA 降维至 k 维 → 初始化 SR 模型 item embedding table → 正常训练**。

ACE 的线性自编码器目标是学习一个物品-物品相似度矩阵 **𝐁_ACE**，优化目标为 `min ‖𝐄ᵀ − 𝐄ᵀ𝐁‖²_F + λ‖𝐁‖²_F`。该目标有闭式解 **𝐁̂_ACE = (𝐄𝐄ᵀ + λ𝐈)⁻¹𝐄𝐄ᵀ**。通过对 𝐁̂_ACE 做谱分解得到：**𝐄_ACE = 𝐔 · g_λ(𝐒)**，其中 g_λ(σ) = √(σ²/(σ² + λ)) 是一个作用于奇异值的收缩函数。最终取 top-k 奇异方向并乘以缩放因子 γ 得到 SR 模型初始化权重。

**关键机制拆解**
最值得关注的设计是 **λ 加权正则化项对奇异值谱的连续调控机制**。ACE 目标函数的两个组成各有明确几何角色：

- **重建损失项** `‖𝐄ᵀ − 𝐄ᵀ𝐁‖²_F`：当 λ=0 时，收缩函数 g₀(σ)=1，所有奇异分量等权保留，此时相当于白化操作——保留了原始 LLM embedding 空间的语义方向（𝐔 基），但强行拉平方差谱，导致语义层次结构丢失。
- **λ 加权正则化项** `λ‖𝐁‖²_F`：随 λ 增大，g_λ(σ) 渐进地抑制主导奇异值的权重幅度，从等向（λ=0）平滑过渡到保留原始方差分布（λ→∞）。图 2 清晰展示了 λ 对特征值谱的平滑调控效果——这就是"各向异性可控"的本质。

这个设计的有效性在于：**它用一个连续超参数 λ，替代了白化那种"全有或全无"的离散操作**。不同语义重要性的方向被差异化保留，而非统一抹平。代价是引入了一个需要调参的 λ，且 λ 的最佳取值依赖数据集和 LLM encoder（论文中 λ 搜索空间跨度 0 到 5000）。从工业角度看，这个参数是全局的、不依赖用户/物品粒度，调参成本可控。

**实验结果**
- **数据集**：Amazon Beauty、Amazon Toys、Yelp 2018、ML-20M，均按 leave-one-out 协议划分。
- **对比 baseline**：LLM2X（PCA 直接降维）、WhitenRec+（分组白化）、LLMEmb（MLP 投影对齐）、AlphaRec（MLP 语义空间对齐）、AlphaFuse（冻结语义子空间+重初始化剩余维度）。
- **backbone**：SASRec、GRU4Rec、BERT4Rec。
- **核心指标**：Recall@10/20、NDCG@10/20。
- **提升数字**：在 SASRec backbone 上，Beauty 数据集 R@20 从 AlphaFuse 的 0.1263 提升至 0.1288（+2.0%），Toys 从 0.1317 提升至 0.1342（+1.9%），Yelp 从 0.0879 提升至 0.0892（+1.5%），ML-20M 从 0.2798 提升至 0.2825（+1.0%）。在 GRU4Rec 和 BERT4Rec 上提升更显著，Beauty 数据集 GRU4Rec R@20 从 0.1025 提升至 0.1107（+8.0%），Yelp 从 0.0765 提升至 0.0860（+12.4%）。多 LLM encoder 实验（F2LLM-4B、Qwen3-8B、KaLM-12B）均一致提升。

**工程挑战与落地建议**
- **特征接入成本**：ACE 的前置依赖是 LLM encoder 生成的离线 embedding，这本身是 LLM-as-Extractor 范式的固定成本（对每个物品调用一次 LLM API 或本地推理），ACE 并未额外增加这一成本。ACE 在线性自编码器阶段的 SVD 计算是离线一次性完成的，对 n 个物品的复杂度为 O(n²d)，在百万级物品规模下可接受（可只对活跃物品做 SVD，新物品通过映射近似）。
- **线上延迟**：无新增延迟。ACE 产出校准后的 embedding 矩阵后，直接替代 SR 模型的 item embedding table 初始值，线上推理过程与传统 SR 完全一致。
- **冷启动**：新物品可用已有 SVD 基 𝐔 和收缩函数 g_λ 做投影，但论文未对此展开实验验证。实际落地建议沿用 LLM-as-Extractor 的通用做法——新物品走 LLM encoder 后用已有 PCA 矩阵投影。
- **关键局限**：ACE 假设各向异性是全局的问题，对物品集的同一个 λ 做统一调节。不同品类的物品语义分布可能存在异质性，统一调控可能不是最优。另外 λ 的调参目前依赖验证集，缺乏自动化选择策略。
- **最有价值的建议**：在引入 LLM embedding 做推荐模型初始化时，**不要直接做 PCA 降维就投喂给 SR 模型，也避免使用激进的白化操作**。用一个轻量的、带正则化的线性自编码器做 embedding 重塑，本质上是一种"免费午餐"——不增加线上成本，但能显著改善后续微调时的几何条件。这个思路可以推广到任何"将预训练 embedding 作为下游模型初始化"的场景。

**一句话总结**
ACE 用带 L2 正则的线性自编码器实现对 LLM embedding 各向异性的连续调控，保留语义层次的同时缓解几何失衡，在所有 LLM 增强 SR 模型上可即插即用、一致提升。

### 2. Looking Farther with Confidence: Uncertainty-Guided Future Learning for Sequential Recommendation

<div class="paper-card">
<div class="paper-authors">Ziqiang Cui、Xing Tang、Peiyang Liu 等7人</div>
<div class="paper-arxiv"><a href="https://arxiv.org/abs/2605.28493v1" target="_blank">arXiv:2605.28493v1</a> · 2026-05-27</div>
</div>

**论文定位**  
这篇论文聚焦于**序列推荐（Sequential Recommendation）** 中的**训练效率与数据稀疏**问题，具体解决“训练期间仅用下一个 item 作为监督信号，忽略了更远未来交互中蕴含的丰富信息”。已有少数工作（DSSRec、FENRec）尝试引入未来多步监督，但它们在所有样本上**以相同强度施加未来损失**。当模型对当前时刻的下一 item 预测高度不确定时，强行预测更远行为会引入噪声，反而损害主任务。核心差异在于：UFRec 提出**不确定性引导的自适应未来学习**——用模型对下一 item 的预测熵动态调制未来监督的权重，自信时多看远，迟疑时聚焦眼前；同时用**未来轨迹级别的对比学习**补充整体偏好，且所有辅助模块**仅训练时存在，推理零开销**。

**核心架构**  
输入是一条用户交互序列（截断到时间步 \(t\)）：
\[
\mathcal{S}_{1:t}^u = [v_1^u, v_2^u, \dots, v_t^u]
\]
经过 **Transformer backbone**（由 Embedding + Position Encoding + L 层 Self-Attention 组成）得到当前时刻的隐状态 \(\mathbf{h}\)。  
基于 \(\mathbf{h}\) 并行做三件事：
1. **主任务头**：用 \(\mathbf{h}\) 与 item embedding matrix 点积得到下一 item 的概率分布 \(\hat{\mathbf{y}}\)，计算主损失 \(\mathcal{L}_M\)。  
2. **不确定性未来监督分支**：通过 \(K-1\) 个并行的轻量投影头（Linear+ReLU）得到“看向 \(k\) 步之后”的用户意图 \(\mathbf{h}^{(k)}\)，同样用共享 item embedding 生成第 \(t+k\) 步的预测分布 \(\hat{\mathbf{y}}^{(k)}\)；同时根据主任务分布 \(\hat{\mathbf{y}}\) 的熵计算自适应权重 \(\omega = \exp(-\mathcal{H}(\hat{\mathbf{y}})/\tau)\)，用 \(\omega\) 对每个未来步的交叉熵损失加权得到 \(\mathcal{L}_{FS}\)。  
3. **未来感知对比学习分支**：将时间步 \(t+1\) 到 \(t+K\) 的真实未来 items 通过池化（论文用 mean-pooling）得到“未来地平线”表示 \(\mathbf{z}\)；将当前状态 \(\mathbf{h}\) 经另一个投影头得到 \(\mathbf{h}^z\)，以 \(\langle \mathbf{h}^z, \mathbf{z} \rangle\) 为相似度做 InfoNCE 对比损失 \(\mathcal{L}_{FC}\)（正样本是自己的未来轨迹，负样本是 batch 内其他用户的未来轨迹）。  
训练总损失：\(\mathcal{L} = \mathcal{L}_M + \lambda_{FS} \mathcal{L}_{FS} + \lambda_{FC} \mathcal{L}_{FC}\)。推理时仅保留 backbone 和主任务头，直接输出 \(\hat{\mathbf{y}}\)。

**关键机制拆解**  
- **不确定性引导的未来调制**：用 Shannon 熵 \(\mathcal{H}(\hat{\mathbf{y}})\) 量化主任务的预测置信度，设计指数衰减权重 \(\omega\)。当主任务对下一 item 概率分布尖锐（熵低）时，\(\omega \to 1\)，未来监督接近完整强度，模型被鼓励学习更远偏好；当分布平坦（熵高）时，\(\omega \to 0\)，未来损失被自动压制，避免不可靠的当前状态污染未来步的学习。这个设计有效的原因在于：它将未来信息的使用与当前理解质量挂钩，形成“先站稳再看远”的课程式正则，防止对未来标签的生硬拟合干扰主要目标。代价仅为训练阶段多计算一次熵和指数运算，且完全不影响推理。  
- **未来感知对比学习**：与步级交叉熵互补，以整体轨迹为单位进行表征对齐，直接拉近当前用户状态与其自身未来轨迹的全局模式，同时推开其他用户未来，这比逐步预测更能捕获偏好演化的大方向，有助于缓解单步噪声（如误点击）。代价是需要对每个训练序列构造未来池化表示，并增加一次对比损失计算。

**实验结果**  
- **数据集**：Amazon Beauty, Sports, Toys 及 Yelp。  
- **Baseline**：经典序列模型（SASRec, BERT4Rec）、自监督方法（S³-Rec, CL4SRec, DuoRec, ICLRec）以及使用未来信息的方法
