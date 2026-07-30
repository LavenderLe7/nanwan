# 南湾街道政企供需匹配系统

把 5 张 Excel（企业能力清单、深度画像、25 应用场景、储备场景库、项目责任清单）整合为
一个可查询、可匹配、可跟踪的本地 Web 系统。政府采购中标记录（文件6）本期未纳入。

## 功能

**政府端**
- 工作台：企业/场景/项目/匹配覆盖率/待审核 统计
- 企业库：115 家企业一企一档（能力清单 + 深度画像合并），搜索/类别筛选/编辑/新增
- 场景库：南湾25场景 + 80 个储备场景，重名场景互链
- 匹配工作台：场景→候选企业排序（含推荐理由），企业→场景机会；可标记对接/排除、一键转项目
- 项目跟踪：责任清单 30 个项目看板（对接中/推进中/已落地/搁置）+ 进展时间线
- 审核中心：企业端提交的资料修改/合作意向审核，通过后自动写回档案并重算匹配
- 数据管理：从源 Excel 一键重导入（幂等 upsert）+ 自动重算匹配
- **词库管理**：领域词库在线增删（写库即时生效、无需改代码/重启），可一键恢复内置默认
- 用户管理：admin/gov/enterprise 三角色

**企业端**（`config.py` 中 `ENTERPRISE_PORTAL_ENABLED=False` 时入口关闭，部署后改 True 开放）
- 我的资料（修改须审核）、场景机会（按本企业匹配）、我的提交（审核进度）

## 匹配引擎

`总分 = 0.7 × BGE 语义相似度 + 0.3 × 规则分`（类别映射 + 领域词库命中），
每条推荐附可解释理由。完整设计文档见根目录 [匹配算法设计.md](../匹配算法设计.md)。模型未安装时自动降级为纯规则匹配，系统其余功能不受影响。
全量预计算（115 企业 × 105 场景，CPU 秒级），档案编辑后自动重算。
项目的「计划落地场景」自由文本用语义相似度（阈值 0.60）关联到场景库。

## 运行

```bash
cd app
# 首次：建环境（本机为 Intel Mac，必须用 python3.11 —— torch 无 x86_64 mac 新轮子）
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/bin/pip install -r requirements-matching.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/bin/python scripts/download_model.py   # 从 ModelScope 下载 BGE 模型（~100MB）

# 每次启动
.venv/bin/python run.py    # → http://127.0.0.1:8000
```

首次启动自动建库并创建管理员：**admin / nanwan2026**（登录后请尽快在用户管理中改密）。

## 常用维护

| 操作 | 命令/入口 |
|---|---|
| 冒烟测试 | `.venv/bin/python scripts/smoke.py` |
| 命令行重导 Excel | `.venv/bin/python -m ingest.excel_import` |
| 页面重导 + 重算匹配 | 数据管理 →「立即导入并重算匹配」 |
| 重置数据库 | 删除 `app/data/nanwan.db` 后重启 + 重导 |

**更新源 Excel 的注意事项**：文件按序号前缀（`2 *.xlsx`）自动发现，多版本取文件名日期最新者——
新快照直接放进目录即可，不用改代码。但**列结构与表头位置必须与现版一致**（导入前会校验，
版型不符的文件会被拒绝并在报告中标红）。企业名带括号后缀、合并单元格、单元格内换行都能自动处理。

## 结构

```
app/
├── run.py / config.py / db.py / auth.py / schema.sql / templating.py
├── ingest/excel_import.py + normalize.py   # 5 表导入、企业名归一化、类别拆分、延续行处理、同企业多行合并
├── matching/embed.py + rules.py + engine.py # BGE 向量、规则映射、融合打分、全量预计算
├── routers/auth.py / gov.py / ent.py        # 登录、政府端、企业端
├── templates/  static/                      # 服务端渲染，零外部前端依赖（政务内网可用）
└── data/nanwan.db  data/models/             # SQLite 与模型权重（.gitignore 忽略）
```

依赖注意：starlette 1.x 的 `TemplateResponse` 是 `(request, name, context)` 新签名；
文件1（WPS 伪 .xlsx）必须走 xlrd；Excel 中一企多项目时公司名只在首行（导入器做延续行填充）。
