# 冻结队列上的仿射零假设

README.md、samples.py、原 tests/ 和现有运行清单描述完整V1。V1已有观测修订、具名设计、无约束扩展拟合、效应报告和SQLite成果归档。本轮尚无约束拟合或似然比较；null_examples.py只提供固定输入、解析期望和V1样例检查，不提供V2求解器。

## 新调用和输入

在 binomial.fitting.service 提供 fit_null(store, request_id, fit_id, equations)，返回约束成果ID；在 binomial.reporting.service 提供 compare_null(store, request_id, null_id)，返回比较报告ID。两者均通过 binomial.archive.fit_records.read_result 读取。fit_id仅接受原无约束fit，null_id仅接受新约束成果；其他种类或不存在的引用明确拒绝。

equations必须为长度0至4的list，每项为恰含coefficients、rhs两个字段的dict。coefficients是原拟合 frozen.column_ids 中列名到有理数的映射，省略列系数为零，表示Aβ=b；未知列即使系数为零也拒绝。系数与rhs沿用 design.contrasts.rational 的 int、Fraction、字符串或整数二元组/列表格式，不接受bool或float；约分后的分子绝对值及分母均不超过8。非法方程抛ValueError，零分母也允许沿用ZeroDivisionError。

规范方程保留列表顺序和冗余项，系数按原列名保存为Fraction，省略零项，rhs也为Fraction。等值有理编码等价；不要求不同排列或代数等价的方程组共用回执。允许空约束、相容冗余、秩亏及零维可行空间；矛盾方程整次拒绝。约束在原列参数上解释，不能先任意固定不可识别参数再施加假设；零设计与对不可识别方向的合法约束仍须接纳。

## 统计含义

全部计算使用fit_id的完整冻结设计及全部原观测，不读取当前队列。对满足Aβ=b的有限参数及其概率极限，最大化原二项对数似然，采用V1口径：各行贡献为k*log(p)+(n-k)*log(1-p)，不含组合常数，零乘对数项计零。

约束可能阻断原分离方向，使原边界行重新参与有限求解。重新判定受约束模型的全部边界，保留非零右端偏置；不得继承原内部行集、用Wald近似代替拟合、加惩罚或用参数截断近似边界。空约束与原拟合相同；允许约束后仍然分离。边界表示数学上的确定0/1，而非浮点舍入判断；极端有限预测可发生概率舍入，但仍须稳定计算有限原似然。

比较消费约束成果及它绑定的原拟合，报告原模型与零假设的两个对数似然和D=2*(原似然-约束似然)，不计算p值、置信区间或自由度。概率、对数似然及D绝对误差均不超过1e-8，确定边界明确为0或1。不能对任意负D取绝对值或用截零掩盖超出误差的求解错误。

允许全量重算、有限顶点枚举和复用已有精确线性代数；内部参数、商空间及持久表示由实现选择。保持已有拟合、归档和报告的职责边界：拟合交付完整行语义，归档负责发布及绑定校验，报告消费已发布成果。

## 可观察成果与持久边界

read_result对约束成果至少返回：
- result_id、kind="null_fit"、fit_id、equations；
- frozen：与原拟合完全相同的完整冻结输入；
- probabilities、boundary：与frozen.row_ids同序，boundary用None表示非确定边界；
- log_likelihood：全部原行的约束最优似然值。

read_result对比较至少返回result_id、kind="null_comparison"、fit_id、null_id、original_log_likelihood、null_log_likelihood、statistic。statistic即D。允许附加用于校验的内部字段，不要求把原参数报成唯一有限解。

约束成果的发布、读取校验和比较消费必须共同支持改变后的边界；重开读取不得重新拟合。读取须校验规范方程、冻结身份、原fit_id绑定以及边界和数值成果的一致性；版本、种类、编码或绑定损坏明确拒绝，不静默修复。可重算校验量，但不能运行优化求解器重建成果。

request_id在null_fit、null_comparison各自种类中全局唯一。约束请求绑定fit_id及规范方程，比较请求绑定null_id；规范内容重放原成果ID，不同内容抛RequestConflict。新种类不占用原fit/report的请求范围。

候选验证成功后，成果、发布状态和成功回执同事务提交；验证、求解、写入或提交失败均不发布部分成果，旧成果不变，失败请求可重试。沿用ArchiveStore.arm_failure(write_number=N)和arm_failure(before_commit=True)实际写入接缝；不规定实现的写入次数。更正队列、修改调用输入或读取返回值、关闭重开均不得改变旧约束及比较，也不得让旧比较消费当前修订。不存在成果沿用ResultNotFound；损坏成果沿用ArchiveFormatError。

## 样例和交付验证

null_examples.py的cases()给出独立可变输入。prepare_original只建立V1原拟合。执行 python3.11 -B null_examples.py 只检查V1及固定期望值自洽，不能作为V2验收通过证据。

三行样例X=[(1,0),(0,1),(0,-1)]，n=[1,2,2]、k=[1,1,1]，原概率为[1,1/2,1/2]，原似然为-4log(2)。βu=0时全部概率为1/2，约束似然为-5log(2)，D=2log(2)。βu=1时首行概率为expit(1)，D=2log(1+exp(-1))。βu+βv=1的固定高精度期望及等价列变换见coupled和coupled_transformed；重复列下βu-βv=1不限制可识别的两列和，unidentified_difference的D为0。

交付须独立核账上述边界恢复、非零偏置、耦合约束、等价列变换、秩亏及仍有分离方向的情形，并核对空约束、相容重复方程、全约束、零设计和矛盾方程。原三行样例同时提交βu=0与βu=1应拒绝且不留下成果或回执；全部参数固定为零时三行概率均为1/2。未知列零系数和非法有理数仍须拒绝。

在新成果发布后更正观测，关闭并重开数据库，再创建旧null_id的比较；与更正前比较的两似然和D一致。覆盖输入及返回值隔离、规范请求重放和冲突；分别在新成果及比较的实际写入窗口和提交前失败时，核对旧成果不变、无半成品及相同请求重试成功。

提供简短交接不变量说明和独立数值核账，不以生产求解器自身输出作为期望。保留全部原接口及原测试字节。沿现有.pointwise-runtime.json接通联合验证和演示：verify执行全部原回归及新增业务核账，失败保持非零退出；demo保留原演示并展示约束解除边界、更正后磁盘重开及旧约束的真实比较结果。清单现有version=1、kind=cli、setup为argv数组列表、verify/demo为实际命令argv数组的格式继续有效。
