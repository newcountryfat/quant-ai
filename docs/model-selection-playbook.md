# 模型训练、回测与筛选复用手册

> 最后更新：2026-05-22  
> 适用范围：当前仓库的 `lasso` / `LightGBM` 择时模型训练、模型回测、模型保留与清理流程

---

## 1. 目标

这份文档记录当前采用的模型选取方法，方便后续对 ETF、指数或个股复用同一套流程。

核心思想是把流程拆成两个阶段：

1. 训练模型阶段：只使用训练区间内的数据训练模型。
2. 模型回测阶段：使用训练好的模型，在独立回测区间生成信号并评估表现。

这样可以避免把训练区间和模型回测区间混在一起，降低样本内结果误导。

---

## 2. 当前默认时间区间

### 2.1 训练模型阶段

默认训练区间：

```text
2024-01-01 到 2025-08-31
```

训练时继续按时间顺序做内部切分：

```text
train_ratio = 0.8
```

含义：

- 前 80%：用于拟合模型。
- 后 20%：用于训练阶段的测试指标，例如 AUC、F1。
- 内部切分只发生在训练区间内，不使用模型回测区间的数据。

注意：`label_dir_N` 需要未来 N 天收益来生成标签，因此训练区间末尾 N 天标签为空，会自动从训练样本中剔除。

### 2.2 模型回测阶段

默认模型回测区间：

```text
2025-09-01 到 2026-05-22
```

模型回测阶段使用训练好的模型，在该区间重新计算因子、生成预测信号，并执行回测。

如果某个产品本地行情数据没有覆盖完整区间，则实际使用本地可用数据。例如比亚迪 `002594` 的数据只到 `2026-05-08`，则回测实际只能到 `2026-05-08`。

---

## 3. 候选模型范围

### 3.1 模型类型

当前固定尝试两类模型：

```text
lasso
lightgbm
```

项目中 `lasso` 实际由 L1 正则的逻辑回归实现，`lightgbm` 由 `LGBMClassifier` 实现。

### 3.2 标签周期

当前候选标签周期为：

```text
label_dir_1
label_dir_2
label_dir_3
label_dir_5
label_dir_7
label_dir_8
label_dir_10
```

对应 `forward_period`：

```text
1 / 2 / 3 / 5 / 7 / 8 / 10
```

含义是预测未来 N 个交易日后的方向标签。

---

## 4. 训练流程

对每个产品、每个模型类型、每个 `forward_period` 组合执行一次训练。

逻辑流程：

1. 从 `daily_quotes` 读取训练区间日线。
2. 调用 `FactorLibrary.compute_all` 生成全量因子。
3. 调用 `LabelEngine.generate_all_labels` 生成 `label_dir_N`。
4. 删除标签为空的样本。
5. 用 `FeatureSelector` 做特征筛选。
6. 按 `train_ratio = 0.8` 时间顺序切分训练集和测试集。
7. 训练 `lasso` 或 `lightgbm`。
8. 保存模型文件到 `data/models`：

```text
data/models/{model_id}.pkl
data/models/{model_id}.json
```

模型 ID 格式：

```text
{model_type}_{symbol}_{label_col}_{YYYYMMDD_HHMMSS}
```

示例：

```text
lightgbm_sz159813_label_dir_2_20260522_224948
```

---

## 5. 模型回测流程

对训练出来的每个候选模型执行模型回测。

回测参数：

```text
start = 2025-09-01
end = 2026-05-22
threshold = 0.5
initial_capital = 1,000,000
commission = 0.001
```

信号生成规则：

- 预测概率 `>= 0.5`：买入信号。
- 预测概率 `< 0.5`：卖出信号。
- 回测引擎默认有 1 个交易日执行延迟。

回测结果保存到 `backtest_results` 表，策略 ID 格式为：

```text
ml:{model_id}
```

---

## 6. 当前筛选规则

模型回测完成后，按回测结果筛选。

当前标准：

```text
trade_count > 10
sharpe_ratio > 2.5
win_rate > 0.48
```

即：

- 交易次数超过 10 次。
- 夏普比率大于 2.5。
- 胜率大于 48%。

当前新版规则不再强制要求年化收益大于 50%。早期曾使用过：

```text
trade_count > 100
sharpe_ratio > 2.5
annual_return > 0.5
win_rate > 0.46
```

后续如无特别说明，以新版规则为准。

---

## 7. 保留与清理规则

### 7.1 自动保留

满足筛选规则的模型自动保留：

- 保留 `data/models/{model_id}.json`
- 保留 `data/models/{model_id}.pkl`
- 保留 `backtest_results` 中对应回测记录
- 如有策略快照，保留对应 `strategy_daily_snapshots`

### 7.2 自动删除

不满足筛选规则的候选模型自动删除：

- 删除候选模型文件。
- 删除对应 ML 回测记录。
- 删除对应策略快照。

清理时只清理目标产品范围内的 ML 策略，不碰无关产品、不碰非 ML 策略、不碰 GP 表达式。

### 7.3 例外保留

如果用户明确要求保留某个不满足规则的模型，可以作为例外保留。

例外保留时必须在最终说明中标明：

- 该模型不满足哪一条规则。
- 保留原因是用户指定例外。

示例：`sh563570` 曾因训练数据短导致交易次数不足，但用户指定保留过一个例外模型。

---

## 8. 数据覆盖注意事项

训练与回测都依赖本地 `daily_quotes` 数据。

执行前应先检查：

```sql
SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
FROM daily_quotes
WHERE symbol = ?;
```

并分别检查训练区间和回测区间：

```sql
-- 训练区间
SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
FROM daily_quotes
WHERE symbol = ?
  AND trade_date BETWEEN '2024-01-01' AND '2025-08-31';

-- 回测区间
SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
FROM daily_quotes
WHERE symbol = ?
  AND trade_date BETWEEN '2025-09-01' AND '2026-05-22';
```

如果训练区间没有数据，则不能训练模型。  
如果回测区间数据不足，回测指标可能不稳定，尤其是交易次数和夏普比率。

---

## 9. 当前已验证的执行结论示例

### 9.1 11 个自选 ETF 新规则重选

使用新版规则重选 11 个 ETF 后，保留了 13 个模型。

有模型保留的产品：

```text
sh510300
sh516090
sh588080
sz159526
sz159813
sz159915
```

没有模型保留的产品：

```text
sh510050
sh512570
sh513180
sh518880
sh563570
```

其中 `sh563570` 在训练区间无数据，无法按新版规则训练。

完整报告：

```text
data/backtest/model_reselection_etf11_20260522_224924.json
```

### 9.2 比亚迪 `002594`

使用同样规则对比亚迪训练和回测后，没有模型通过筛选。

补充测试 `label_dir_7` 和 `label_dir_8` 后，仍没有通过模型。

完整报告：

```text
data/backtest/model_reselection_002594_20260522_230915.json
data/backtest/model_reselection_002594_extra_7_8_20260522_231116.json
```

---

## 10. 复用时的推荐步骤

1. 明确产品列表。
2. 检查每个产品训练区间和回测区间的数据覆盖。
3. 对每个产品跑候选组合：

```text
model_type in [lasso, lightgbm]
forward_period in [1, 2, 3, 5, 7, 8, 10]
```

4. 训练时使用：

```text
start = 2024-01-01
end = 2025-08-31
train_ratio = 0.8
```

5. 回测时使用：

```text
start = 2025-09-01
end = 2026-05-22
threshold = 0.5
```

6. 按规则筛选：

```text
trade_count > 10
sharpe_ratio > 2.5
win_rate > 0.48
```

7. 保留达标模型，删除未达标候选。
8. 生成 JSON 报告放入：

```text
data/backtest/
```

---

## 11. 解释结果时必须说明的事项

汇报模型筛选结果时，应至少说明：

- 训练区间。
- 模型回测区间。
- 候选模型类型。
- 候选 `label_dir_N` 范围。
- 筛选规则。
- 每个产品保留多少模型。
- 哪些产品没有模型通过，以及主要原因。
- 是否存在用户指定的例外保留模型。

不要只报“收益最高”的模型。  
在当前流程中，是否保留模型由回测阶段的交易次数、夏普和胜率共同决定。
