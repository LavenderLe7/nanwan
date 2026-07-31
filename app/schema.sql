-- 南湾街道政企供需匹配系统 数据库结构
-- 说明：政府采购中标记录（文件6）本期不纳入，后续如需可在 enterprises 上挂新表。

CREATE TABLE IF NOT EXISTS enterprises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                 -- 展示名（保留原始写法）
  name_norm TEXT NOT NULL UNIQUE,     -- 归一化名（去括号后缀/空白），跨表 join key
  category_bucket TEXT,               -- 标准桶：类别串去圈码后首段，如 人工智能/无人机/节能环保
  category_raw TEXT,                  -- 原始类别串，如 ②人工智能、智能终端
  intro TEXT,                         -- 企业与产品简介（文件2）
  capability TEXT,                    -- 场景能力（文件2）
  applicable_scenes TEXT,             -- 可应用落地场景（文件2）
  qualifications TEXT,                -- 资质（文件2 企业资质 + 文件5 资质与荣誉 合并去重）
  positioning TEXT,                   -- 核心定位（文件5）
  main_business TEXT,                 -- 主营业务（文件5）
  core_products TEXT,                 -- 核心产品（文件5）
  core_tech TEXT,                     -- 核心技术（文件5）
  clients_cases TEXT,                 -- 典型客户/案例（文件5）
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS scenarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  domain TEXT,                        -- 应用领域
  intro TEXT,                         -- 场景简介
  landing_area TEXT,                  -- 拟落地应用区域（文件3）
  lead_dept TEXT,                     -- 牵头部门（文件3）
  main_tech TEXT,                     -- 主要技术（文件4）
  ref_case TEXT,                      -- 参考案例（文件4）
  potential_enterprises TEXT,         -- 潜在企业及产品（文件4，人工标注，可作匹配校验）
  source TEXT NOT NULL DEFAULT '储备库',   -- 南湾25 / 储备库
  status TEXT NOT NULL DEFAULT '储备',     -- 储备 / 在推 / 已落地
  linked_scenario_id INTEGER REFERENCES scenarios(id),  -- 与另一来源的重名场景互链
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(name, source)
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enterprise_id INTEGER NOT NULL REFERENCES enterprises(id),
  scenario_id INTEGER REFERENCES scenarios(id),   -- 可空：责任清单场景未必入场景库
  title TEXT,                         -- 场景项目介绍（文件1）/ 项目名
  planned_scene TEXT,                 -- 街道计划落地应用场景（文件1）
  dock_dept TEXT,                     -- 建议对接部门（文件1）
  followers TEXT,                     -- 跟进人（文件1）
  progress TEXT,                      -- 推进情况（最新摘要）
  status TEXT NOT NULL DEFAULT '对接中',  -- 对接中 / 推进中 / 已落地 / 搁置
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS progress_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  note TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  enterprise_id INTEGER NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
  semantic_score REAL,                -- 语义分（模型未安装时为 NULL）
  rule_score REAL,
  total_score REAL,
  reason TEXT,                        -- 可解释理由：类别映射/关键词命中/相似度
  status TEXT NOT NULL DEFAULT '候选',   -- 候选 / 已对接 / 已排除
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(scenario_id, enterprise_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
  owner_type TEXT NOT NULL,           -- enterprise / scenario
  owner_id INTEGER NOT NULL,
  vector BLOB NOT NULL,               -- float32 序列化向量
  model_ver TEXT NOT NULL,
  PRIMARY KEY (owner_type, owner_id)
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL DEFAULT 'gov',   -- admin / gov / enterprise
  enterprise_id INTEGER REFERENCES enterprises(id),  -- 企业用户挂靠企业
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enterprise_id INTEGER NOT NULL REFERENCES enterprises(id),
  user_id INTEGER REFERENCES users(id),
  type TEXT NOT NULL,                 -- 资料修改 / 能力自荐 / 合作意向
  payload TEXT,                       -- JSON 字符串
  status TEXT NOT NULL DEFAULT '待审核',  -- 待审核 / 已通过 / 已驳回
  review_note TEXT,
  reviewed_by TEXT,
  reviewed_at TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 领域词库（管理页在线编辑；为空表时 rules.py 内置词库兜底）
CREATE TABLE IF NOT EXISTS lexicon_terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  domain TEXT NOT NULL,
  term TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(domain, term)
);

-- 政策轨：政策主表
CREATE TABLE IF NOT EXISTS policies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT '区级',           -- 国家级/省级/市级/区级/街道级
  category TEXT NOT NULL DEFAULT '产业扶持',    -- 产业扶持/科技创新/财税金融/资质认定
  support_type TEXT NOT NULL DEFAULT '资金奖励', -- 资金奖励/税收优惠/贷款贴息/租金补贴/保费补贴/担保费补贴
  amount_text TEXT,                             -- 扶持金额文本
  deadline TEXT,                                -- 申报截止日期
  source_url TEXT,                              -- 政策原文链接
  status TEXT NOT NULL DEFAULT '已发布',         -- 已发布/已过期
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime'))
);

-- 政策轨：申报条件条款
CREATE TABLE IF NOT EXISTS policy_clauses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  clause_type TEXT NOT NULL,                    -- 资质/规模/行业/地域/信用
  content TEXT NOT NULL,                        -- 条款内容原文
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_policy_clauses_policy ON policy_clauses(policy_id);

-- 政策轨：匹配结果（镜像 matches 表风格）
CREATE TABLE IF NOT EXISTS policy_matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  policy_id INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  enterprise_id INTEGER NOT NULL REFERENCES enterprises(id) ON DELETE CASCADE,
  reason TEXT,                                  -- 逐条条款判定结果文本
  status TEXT NOT NULL DEFAULT '候选',           -- 候选/已对接/已排除
  created_at TEXT DEFAULT (datetime('now','localtime')),
  updated_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(policy_id, enterprise_id)
);

CREATE INDEX IF NOT EXISTS idx_policy_matches_policy ON policy_matches(policy_id);
CREATE INDEX IF NOT EXISTS idx_policy_matches_enterprise ON policy_matches(enterprise_id);

-- 外迁预警
CREATE TABLE IF NOT EXISTS relocation_warnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enterprise_id INTEGER REFERENCES enterprises(id),
  enterprise_name TEXT NOT NULL,
  warning_type TEXT NOT NULL,        -- 异地投资/租赁临期/限制高消费/...
  warning_info TEXT,                 -- 预警详情文本
  warning_time TEXT,                 -- 预警时间
  risk_level_original TEXT,          -- 原始风险等级（数据源标注的高/中/低）
  flow_province TEXT,                -- 产能流向-省
  flow_city TEXT,                    -- 产能流向-市
  flow_district TEXT,                -- 产能流向-区
  app_scene TEXT,                    -- 外迁监控/经营监控
  industry TEXT,                     -- 所属行业
  street TEXT,                       -- 所在街道
  tags TEXT,                         -- 重点企业标签
  warning_score REAL DEFAULT 0,      -- 系统打分
  created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ALTER TABLE enterprises ADD COLUMN relocation_risk TEXT;          -- 见 db.py init_db()
-- ALTER TABLE enterprises ADD COLUMN relocation_score REAL DEFAULT 0;  -- 见 db.py init_db()

CREATE INDEX IF NOT EXISTS idx_matches_scenario ON matches(scenario_id, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_matches_enterprise ON matches(enterprise_id, total_score DESC);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
