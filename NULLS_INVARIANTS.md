# 仿射零假设扩展：交接不变量说明

本文件列出 V2（fit_null / compare_null）必须保持的可观察不变量，供后续维护者核对。业务口径见 NULLS.md，V1 口径见 README.md。

## 约束语义

1. 方程 Aβ=b 在原列坐标解释。实现用精确有理数求特解 β0 与零空间基 F，把问题化为带逐行偏置 o=X·β0 和自由设计 A=XF 的无约束问题；从不先固定不可识别参数再施加假设。
2. 规范方程保留请求列表顺序与冗余项；系数按 frozen.column_ids 存 Fraction、省略零项；rhs 为 Fraction。等值有理编码（"2/4"、"1/2"、[1,2]）规范后相同，共用回执。分子绝对值与分母（约分后）均不超过 8；零分母沿用 ZeroDivisionError，其余非法输入抛 ValueError。
3. 空约束（0 方程）与原无约束拟合完全同解；相容冗余、秩亏约束、零维可行空间（d=0）均接纳；矛盾方程（含 0=非零）整次 ValueError 拒绝，不留成果与回执。

## 边界与似然

4. 受约束边界在约束后设计 A=XF 上重新做精确矩约束面枚举（identify_moment_face），不继承原拟合的内部行集；约束可解除原分离（restore_boundary），也可保留分离（still_separated）。边界是数学确定的 0/1，与浮点舍入无关。
5. 非零右端产生的偏置 o 精确保留（Fraction），逐行进入线性预测；不做参数截断、不加惩罚、不用 Wald 近似代替拟合。
6. 对数似然口径与 V1 相同：Σ k·log p + (n−k)·log(1−p)，无组合常数，零乘对数项计零。确定边界行贡献恒为 0；内部行用稳定 softplus 公式按 η 求值，极端有限预测（p 浮点舍入到 0/1）仍给出有限似然。
7. 内部行求解是带偏置的 Newton（下降检查 + 线搜索），偏置非零时沿 λ·o 同伦推进以保证从饱和区可达；收敛判据与 V1 相同（步长 ≤2e-12，读取校验容差 correction ≤2e-9）。

## 比较

8. compare_null 消费已发布的约束成果及其绑定的原拟合：original_log_likelihood 取自原 fit 的 diagnostics，null_log_likelihood 取自约束成果，D=2(ℓ原−ℓ约束)。两似然同源同修订，不输出 p 值、置信区间或自由度。
9. D 数学上非负；实现不取绝对值、不截零。负 D 超出 1e-6 视为求解缺陷并抛 NumericalFitError。概率、两似然与 D 的绝对误差契约 ≤1e-8。

## 持久化与请求

10. null_fit 与 null_comparison 各自种类内 request_id 全局唯一；规范内容重放返回原成果 ID，不同内容抛 RequestConflict；新种类不占用 fit/report 的请求范围。
11. 约束成果记录绑定 fit_id 与完整 frozen；读取时重新校验规范方程、冻结身份、原 fit 绑定、边界枚举、精确基、收敛余量与似然一致性——只重算校验量，不运行优化求解器，关闭重开不重拟合。
12. 候选验证、成果、发布状态、回执在一个事务提交；arm_failure(write_number=N)（N=1,2）与 before_commit 注入失败时不留半成品，旧成果不变，同一请求可重试成功。
13. 更正队列、修改调用输入或读取返回值、关闭重开均不改变旧约束与旧比较；更正后仍可对旧 null_id 创建比较，两似然与 D 与更正前一致。不存在成果抛 ResultNotFound，损坏成果（版本、种类、编码、摘要、绑定、边界或数值不一致）抛 ArchiveFormatError。

## 独立核账

14. tests/test_nulls.py 的期望来自三处独立来源，均不取自生产求解器：null_examples.py 的固定高精度期望；Decimal(70 位) 一维得分二分参考（restore_boundary、nonzero_rhs、coupled、unidentified_difference、offset_with_free_direction）；解析闭式（全约束 1/2、零设计、极端偏置 softplus）。
