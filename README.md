# 二项响应研究归档

仅使用 Python 3.11 标准库。产品流程是观测登记与更正、具名设计编译、冻结拟合、有序效应报告、持久重开复核。没有安装步骤。

运行完整业务回归：`python3.11 -B verify.py`。
等价完整发现入口：`python3.11 -B -m unittest discover -s tests -t . -v`。
运行登记、分离报告、更正和真实磁盘重开的演示：`python3.11 -B demo.py`。测试和演示仅在测试临时目录创建数据库；样例来自 samples.py。

## 公开调用

```python
from binomial.archive.store import ArchiveStore
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.service import fit
from binomial.reporting.service import report
from binomial.archive.fit_records import read_result

with ArchiveStore("research.sqlite") as store:
    receipt = apply_cohort(store, "study", "input-1", [
        {"row_id": "r", "values": {"x": 1}, "n": 4, "k": 2}])
    register_design(store, "d", ["x"], [ColumnDefinition("x", source="x")])
    fit_id = fit(store, "fit-1", ("study", receipt.revision_id), "d")
    report_id = report(store, "report-1", fit_id, [
        {"name": "intercept", "coefficients": {"x": 1}},
        {"name": "zero", "coefficients": {}}])
    result = read_result(store, report_id)
```

ArchiveStore 支持上下文管理及 open/close；默认路径为 :memory:。单工程、单工作者，不提供在线并发分析。所有业务标识为非空字符串，至多128字符。公用入口按上例各模块导入；binomial 使用标准命名空间包。

## 观测与设计

Observation 和字典输入等价。values 为1至4个具名整数输入，坐标绝对值不超过8；n、k必须为非布尔整数，1≤n≤20、0≤k≤n。每队列至多12行。不删除行；按 row_id 新增或更正。同批重复身份拒绝，不同身份的相同数值分别保留。批次非空，先验证全批及合并后的结果，再提交不可变修订、当前指针和回执。新请求不改变内容时引用原修订。

同队列 request_id 绑定规范批次，行排列不影响指纹。原请求在后续更正之后重放仍返回原回执，且不移动当前指针。同ID不同内容抛 RequestConflict。load_revision(store, cohort_id, revision_id=None) 可读取确切修订或当前修订。

ColumnDefinition(column_id, source=输入名) 按名字取观测值；ColumnDefinition(column_id, constant=整数) 定义常数。每条规则恰有一种来源，至多4个规则。register_design 的 column_ids 是从规则目录选取的非空、无重复顺序；同 design_id 不允许替换声明。规则顺序不影响声明；所选列顺序有意义。缺失输入、未知列、重复列、非法常数拒绝，不以零填补。冻结行按 row_id 排序，固定原修订、声明摘要、列序、矩阵与计数，复制所有输入。

## 拟合及效应

fit 的 cohort_revision 必须是 (cohort_id, revision_id)，不能以当前指针替代确切修订。返回已发布 fit_id。read_result 的拟合值含 frozen、逐行 probabilities、boundary、internal_row_ids、精确 basis、theta、information 和 diagnostics。probabilities 与 frozen.row_ids 同序。boundary 的 None 表示内部行，0/1 表示确定边界。basis 的每行为原列坐标中的 Fraction，theta 是该行基对应的有限坐标，不是原始列参数。

最大化原二项对数似然，不加惩罚。有限、完全分离、准完全分离和秩亏输入均合法。精确矩约束面识别决定哪些坐标在所有可行点固定为0或n；其余行的有限空间使用精确行基，内部有限求解采用稳定似然和带下降检查的Newton迭代。零设计行的概率为1/2。全边界时保存空有限空间，不发明有限参数。diagnostics.status 是 finite、quasi 或 complete；design_rank 与 finite_rank 单独保存，秩亏不等于分离。有限数值绝对误差契约为1e-8；数值失败抛 NumericalFitError，不发布成果。

report 接受有序字典列表，每项恰有 name、coefficients 两字段。名称唯一，不合并不同名称的重复效应。系数是原列名到 int、Fraction、有理数字符串或 [分子,分母] 的映射；不接受float或bool。未知列即使系数为零也拒绝；等值分数和省略零项规范化。空报告合法，仍检查拟合及其绑定。

设I为内部行。仅 c∈span(X_I) 可估计；求 c=wB，给出 w theta 和 w H逆 w转置，H使用 n p(1-p) 权重。其余结果为 status=not_estimable，estimate=variance=None。零效应始终可估计且数值为0。每项保留name、ordinal、规范有理声明、状态和数值。报告只消费冻结成果，不重新拟合，也不读取当前队列代替旧输入。可逆列变换 X'=X T 时，同一效应列向量运输为 c'=T转置c；transport_contrast 提供此运算。

fit 和 report 的请求ID各在本种类中全局唯一；相同规范内容重放原成果ID，内容冲突抛 RequestConflict。报告指纹保留名称、顺序、fit_id；它不会把有序请求转换为集合。

## 存档与失败

schema.py 负责版本1、规范有理编码及摘要；store.py 管理SQLite事务。cohort_snapshots.py 与 design_snapshots.py 保存不可变输入绑定；fit_records.py 与 report_records.py 校验、发布及读取完整成果。

候选计算成功并完整验证后，快照、成果、发布状态和回执在一个事务中提交。任何验证、求解、写入或提交失败均不发布部分成果，旧成果不变；失败请求可重试。不存在或未发布成果抛 ResultNotFound，版本、种类、编码、摘要或绑定损坏抛明确错误，不静默重算。每次读取返回独立嵌套值，外部修改不会改变其他读取或数据库。更正生成新修订，新拟合使用新修订；关闭重开后旧拟合与旧报告保持原绑定。

测试接缝为 ArchiveStore.arm_failure(write_number=N)（第N次实际持久写入后失败）和 arm_failure(before_commit=True)（提交前失败）；失败点一次触发。fit 的有限求解器参数允许调用者显式控制求解失败。接缝不会绕过正常验证、事务或业务计算。

## 回归范围

 tests/test_finite.py 覆盖普通有限拟合、聚合试验次数、行列身份、设计拒绝、拟合重放及数值失败。
 tests/test_boundary.py 覆盖准完全和完全分离、精确内部空间、有序重复请求、零效应、零设计及纯计数仍有有限解。
 tests/test_effects.py 覆盖重复列秩亏、有理系数、非正交列运输、信息权重和整次请求拒绝。
 tests/test_cohort.py 覆盖混合非法批次原子性、重放、历史回执、身份/整数边界与持久写入失败。
 tests/test_archive.py 覆盖输入与返回值隔离、更正后磁盘重开、损坏记录、拟合和报告的每个发布写入窗口及提交前失败重试。
 tests/test_numerics.py 使用独立Decimal高精度一维得分二分、解析聚合计数和精确秩亏核账；期望不调用生产拟合。

不包含正则化、随机效应、其他分布、预测、置信区间、模型选择、图形界面或性能专项。
