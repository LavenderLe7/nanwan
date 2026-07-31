# 南湾街道政企供需匹配系统

本地 Web 系统（FastAPI + SQLite），核心功能：
**场景 ↔ 企业双向匹配**、**政策 ↔ 企业双向匹配**、**外迁预警**。

---

## 数据集说明

8 张 Excel 源文件放在 `app/` 上一级目录。导入时按前缀自动发现，列结构与表头顺序必须一致。

| # | 文件 | 内容 | 导入目标 | 说明 |
|---|------|------|----------|------|
| 1 | 场景搭建项目责任清单 | 17 家企业落地计划（对接部门、跟进人） | projects | WPS 旧格式，数据从第 3 行开始，公司名空行沿用上一行 |
| 2 | 场景能力清单 | 113 家企业场景能力（同一企业多业务线分多行） | enterprises | 导入时按企业名合并多行 |
| 3 | 应用场景清单 | 南湾 25 场景（应用领域、拟落地应用区域、牵头部门） | scenarios | source=南湾25 |
| 4 | 街道通用场景项目储备库 | 80 个通用场景参考库（含主要技术、参考案例） | scenarios | source=储备库；与文件 3 重名的场景自动互链 |
| 5 | 重点企业深度画像 | 115 家企业深度画像（核心定位、主营业务、资质荣誉） | enterprises | 按企业名与文件 2 合并 |
| 6 | 重点企业基础工商信息 | 115 家企业注册资本、员工人数、经营异常情况 | enterprises | UPDATE 模式，仅更新已存在的企业 |
| 7 | 惠企政策种子数据 | 20 条政策 × 56 条申报条款 | policies + policy_clauses | 同一政策多条条款时，序号只填首行，延续行留空 |
| 8 | 外迁预警清单 | 企业外迁预警（预警类型、预警信息、产能流向、风险等级等） | relocation_warnings | **全量替换**，每次导入清空旧数据后重新写入 |

---

## 功能

### 政府端

- **工作台**：在库企业 / 场景 / 政策 / 项目 / 审核统计 + 外迁预警概览
- **企业库**：115 家企业一企一档（搜索 / 类别筛选 / 编辑 / 场景匹配 / 政策匹配 / 外迁预警时间线）
- **场景库**：南湾 25 场景 + 80 储备场景，重名互链
- **政策库**：20 条政策，含申报条款管理、匹配企业列表、重算匹配
- **匹配工作台**：场景→找企业 / 企业→找机会 / 政策→找企业，三种模式
- **外迁预警**：三特征自动打分（挽留级 / 警示级 / 关注级分级展示），预警事件时间线，手动重算
- **项目跟踪**：30 个项目看板 + 进展时间线
- **审核中心**：企业提交的资料修改 / 合作意向审核
- **词库管理**：领域词库在线增删（即时生效，无需重启）
- **数据管理**：8 张 Excel 一键导入 + 自动重算，导入报告
- **用户管理**：admin / gov / enterprise 三角色

### 企业端（`config.py` 中 `ENTERPRISE_PORTAL_ENABLED=True` 开放）

- 我的资料（修改需审核）、场景机会 / 可申报政策（按本企业匹配）、我的提交

---

## 匹配引擎

| 引擎 | 文件 | 方式 | 说明 |
|------|------|------|------|
| 场景 ↔ 企业 | `engine.py` + `rules.py` + `embed.py` | 0.7 BGE 语义 + 0.3 规则 | 场景→找企业 / 企业→找场景；模型未安装时自动降级纯规则 |
| 政策 ↔ 企业 | `policy_engine.py` | 条款逐条布尔判定 | 政策→找企业 / 企业→找政策；任一不满足即排除，数据不足保留候选 |
| 外迁预警 | `relocation_rules.py` | 三特征加权打分（预警类型 × 租赁占比 × 行业） | 企业级风险分级（挽留/警示/关注），数据驱动权重 |

---

## 运行

### 环境要求

| 系统 | Python 版本 | 说明 |
|------|:--:|------|
| Windows | 3.10+ | 无特殊限制 |
| Intel Mac (x86_64) | 必须 3.11 | PyTorch 2.3+ 不再发布 Intel Mac 安装包 |
| ARM Mac (M1/M2/M3) | 3.11+ | 无特殊限制 |
| 不装语义匹配 | 3.10+ | 系统退化为纯规则模式 |

### 首次安装

**Mac / Linux**
```bash
cd app
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# （可选）下载 BGE 语义模型 ~100MB
.venv/bin/python scripts/download_model.py
```

**Windows**
```cmd
cd app
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

REM （可选）下载 BGE 语义模型 ~100MB
.venv\Scripts\python scripts\download_model.py
```

### 启动

**Mac / Linux**
```bash
.venv/bin/python run.py
```

**Windows**
```cmd
.venv\Scripts\python run.py
```

→ http://127.0.0.1:8000
→ 管理员 **admin / nanwan2026**（登录后尽快修改）

首次启动自动建库并创建管理员。进系统后进入「数据管理」→「立即导入并重算匹配」加载 8 张 Excel。

### 常用命令

| 操作 | 命令 |
|------|------|
| 命令行重导 Excel | `.venv/bin/python -m ingest.excel_import` |
| 冒烟测试 | `.venv/bin/python scripts/smoke.py` |
| 重置数据库 | 删除 `app/data/nanwan.db` 后重启 + 重导 |
| 重新下载模型 | `.venv/bin/python scripts/download_model.py` |

### 更新源数据

新快照直接放进根目录即可（前缀匹配，取文件名日期最新者）。列结构与表头顺序必须不变——导入前自动校验，版型不符的文件会被拒绝并标红。

---

## 项目结构

```
app/
├── run.py                          # FastAPI 入口 + lifespan
├── config.py                       # 全局配置
├── db.py                           # SQLite 连接 + 初始化 + 查询助手
├── auth.py                         # 密码哈希 (PBKDF2) + session + 角色守卫
├── templating.py                   # Jinja2 工具
├── schema.sql                      # 建表 DDL
├── requirements.txt                # 所有依赖（含可选语义匹配）
│
├── ingest/
│   ├── excel_import.py             # 8 张 Excel → DB 导入器
│   └── normalize.py                # 企业名归一化、类别拆分、资质合并
│
├── matching/
│   ├── embed.py                    # BGE 向量化
│   ├── rules.py                    # 场景轨规则（领域词库 + 类别映射）
│   ├── engine.py                   # 场景↔企业匹配引擎
│   ├── policy_engine.py            # 政策↔企业匹配引擎（条款判定）
│   └── relocation_rules.py         # 外迁预警打分模型
│
├── routers/
│   ├── auth.py                     # 登录/登出
│   ├── gov.py                      # 政府端全路由
│   ├── policy.py                   # 政策轨路由
│   └── ent.py                      # 企业端路由
│
├── templates/
│   ├── base.html                   # 公共骨架 + 导航
│   ├── login.html
│   ├── gov/                        # 政府端页面（15 个）
│   └── ent/                        # 企业端页面（3 个）
│
├── static/
│   ├── css/app.css
│   └── js/app.js
│
└── scripts/
    ├── smoke.py                    # 冒烟测试
    └── download_model.py           # ModelScope 下载 BGE 模型
```
