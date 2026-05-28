# 桥梁施工数据整治平台 — 工作日志

## 2026-05-22

### 已完成

- [x] FastAPI 后端项目骨架搭建 (`app/`, `models/`, `routers/`, `services/`, `db/`)
- [x] Pydantic 数据模型：Document / Section / ImageInfo / TableInfo / Tag
- [x] 14 个 REST API 端点（上传、列表、状态、解析结果、章节增删改、入库）
- [x] Word 文档解析器 (`services/parser.py`) — 基于 `intelligent_parser.py` 升级
- [x] Word→PDF 转换 (`services/converter.py`) — 依赖 LibreOffice
- [x] 静态资源服务 (图片 / 表格JSON / PDF预览 / 原始docx)
- [x] 内存存储层 (`db/memory_store.py`) — 线程安全 + JSON 持久化, 后续替换 PostgreSQL
- [x] CORS 配置、lifespan 管理、Swagger 文档

### 修复：WinError 183 文件名冲突 (第一轮)

**现象**：解析 Word 时，`os.rename` 将临时图片重命名为标题命名，同标题图片第二次出现时目标文件已存在，Windows 上抛出 `WinError 183`。

**已修改** (`parser.py`)：
1. `_safe_filename()` 增加 `\s+` → 单空格合并
2. `os.rename` → `os.replace`
3. 新增 `_unique_filename()` 自动加 `_2`/`_3` 后缀
4. 新增 `_cleanup_temp_images()` 解析前清理上次残留的临时文件

### ✅ 修复：WinError 183 — 方案4：图片计数器命名 (2026-05-25)

**策略**：图片提取后保持 `{doc_prefix}_img{N}.png` 命名，**不再按 caption 重命名**。
标题映射通过 `ImageInfo.caption` + `ImageInfo.local_path` 记录，`ImageInfo.original_name` 存实际文件名。

**改动** (`parser.py` 第 100-109 行)：
- 移除 `_safe_filename(para_text)` + `_unique_filename()` + `os.replace()` 的重命名链
- 图标题处理直接取 `os.path.basename(last_seen_image_path)` 记录路径
- 表标题处理保持原有逻辑（有 `_unique_filename` 保护且出错率低）

**为什么这次能根除**：不再有任何基于用户输入文字的文件重命名操作，彻底消除编码/冲突/非法字符问题。

---

## 2026-05-25

### ✅ 方案4落地：图片计数器命名 — 根除 WinError 183

取消图片按 caption 重命名，保持 `{doc_prefix}_img{N}.png` 计数器命名。
`ImageInfo.caption` + `local_path` + `original_name` 三元组完整保留映射关系。
同名标题的图片不再冲突。

### ✅ 路径前缀统一：`/static` → `/storage`

`assets.py` 路由前缀和 `parser.py` 的 `rel_prefix` 统一改为 `/storage/doc_assets`，
与磁盘目录结构一致。

### ✅ 标题层级扩展 + 动态匹配

- 标题层级从 3 级扩展到 5 级（`Heading 1` ~ `Heading 5`）
- 上传接口增加 `regex_level1` ~ `regex_level5` + `max_heading_level` 参数
- 解析器实现 `_match_heading()` 方法：有正则用正则匹配段落文本，无正则回退到样式名匹配
- 增加中文样式名支持：`标题 1` / `标题1` / `heading 1` / `Heading 1`

### ✅ 样式扫描 + 可配置化

- 新增 `scan_styles()` 函数，扫描文档中所有段落样式及出现次数
- 新增 `GET /api/documents/{doc_id}/styles` 端点
- `body_styles`、`image_caption_style`、`table_caption_style` 全部可配置
- 上传接口增加对应参数，解析器不再硬编码 `"Normal"`、`"图标题"`、`"表标题"`

### ✅ 上传/解析流程重构为两步

**之前**：上传时必须一次性填好所有解析参数 → 自动解析，出错只能删了重来。

**现在**：
1. `POST /api/documents/upload` — 只传文件 + 基本元数据，自动扫描样式，返回 `scanned_styles`
2. 用户根据样式分布决定配置
3. `POST /api/documents/{doc_id}/parse` — 填入样式配置，启动后台解析

新增 `DocStatus.uploaded` 状态，新增 `store.configure_parsing()` / `store.update_scanned_styles()`。

### ✅ 标准化交底文档

编写 `STYLE_GUIDE.md`，包含标题样式设置、图/表标题命名规范、多图拆分规则、样式确认流程、自检清单。

### 📋 上线前待办 (明天)

- [ ] 补测试（至少解析器测试）
- [ ] 存储迁移：内存 JSON → PostgreSQL
- [ ] 请求体大小限制
- [ ] Docker 化 (Python + LibreOffice + PostgreSQL)
- [ ] `print()` → `logging` 日志改造

---

## 2026-05-26

### ✅ 待办优先级重新定义

与团队讨论后对后续工作重新排序：

- **测试** → 暂缓。手动验证已通过，等解析器稳定后再补自动化测试。
- **PostgreSQL** → 重新定义为"审核通过后入库通道"，不是替换 JSON。JSON 先作为审核介质，审核通过再入 PG。
- **请求体大小限制** → 内部工具阶段暂缓，对外部署时再加。
- **Docker** → 解决 Python + LibreOffice + PG 三依赖的部署痛点，多人部署时价值大。
- **logging** → 现阶段 `print()` 够用，等代码稳定不再频繁改动时再切。
- **用户认证、知识图谱、大模型标签、前端** → 未讨论，后续排期。

---

## 2026-05-27

### ✅ Git 仓库搭建 + 双远程配置

- 本地项目 `git init`，纳入版本控制
- **GitHub 仓库**：创建 https://github.com/yianchangan/bridge_platform，添加为 `origin` 远程
- **服务器裸仓库**：在 `10.84.12.74` 执行 `git init --bare /data/git/bridge_platform.git`，添加为 `server` 远程
- 初始提交 `03ff99b Feat: 桥梁方案数据整治平台 v1.0`（20 文件，1701 行），同时推送到 `origin` 和 `server`

### ✅ GIT_GUIDE.md 编写

- 针对本项目的双远程（GitHub + 服务器）架构编写的 Git 使用指南
- 覆盖：Git 基础概念、工作区/暂存区/仓库、远程仓库原理、裸仓库 vs 工作目录、push/pull 数据流、分支策略、日常命令速查
- 包含服务器部署三步走操作说明（clone 工作目录 → 安装依赖 → 启动服务）

### ✅ 部署通道建立

```
本地 Windows ──push──→ origin (GitHub, 备份)
           ──push──→ server (10.84.12.74 裸仓库, 中转站)
                         └──pull──→ /data/bridge_platform/ (运行的服务)
```

### 📋 明日待完成计划

- [ ] **服务器部署上线**：SSH 到服务器，clone 工作目录到 `/data/bridge_platform/`，安装依赖（`pip install -r requirements.txt`，`apt install libreoffice`），启动 uvicorn 服务
- [ ] **端到端验证**：在服务器上用真实桥梁施工方案 Word 文档跑通"上传 → 样式扫描 → 填写配置 → 解析"完整流程
- [ ] **WORKLOG.md 补充**：将 WORKLOG.md 也纳入 git 跟踪，之后每次工作日志也作为仓库的一部分管理
- [ ] **PostgreSQL 入库通道设计**：开始设计"审核通过后 JSON → PG"的表结构和入库逻辑
- [ ] **Docker 调研**：调研 LibreOffice + Python + PostgreSQL 三依赖的 Docker 化方案

---

## 2026-05-28

### ✅ 服务器部署上线 (systemd 持久化)

- SSH 到 `10.84.12.74`，工作目录已存在 `/data/bridge_platform/`
- 安装缺失依赖：`python-docx`, `pdfplumber`, `pdf2image`, `sentence-transformers`, `faiss-cpu`, `torch`
- 创建用户级 systemd 服务 `bridge-platform.service`，端口 **10604**
- `loginctl enable-linger` 确保 SSH 退出后服务不挂
- 崩溃自动重启 (`Restart=always`, 3s 间隔)
- 原 10608 端口的旧 uvicorn 进程已清理

### ✅ CORS 修复

- `allow_credentials=True` + `allow_origins=["*"]` 浏览器会拒绝 → 改为 `allow_credentials=False`
- 原因：公开 API 无 cookie 认证，不需要 credentials

### ✅ 表格截图方案重构 (全页渲染 + 图→表页码映射)

**问题**：pdfplumber `find_tables()` 对中文桥梁施工方案表格检测极不可靠 (合并单元格、无边框、跨页)，bbox 裁剪经常不全或直接漏检。

**新方案**：弃用单表裁剪，改全页渲染 + 页码映射：

```
Word → LibreOffice → PDF
                      ├→ render_pages() → page_1.png, page_2.png, ...
                      └→ detect_table_pages() → 页级检测 (远比 bbox 可靠)
                                                         ↓
                                  映射: docx第N个表 → page_X.png
                                  漏检兜底: 所有页面分给每个表
```

**改动**：
- `converter.py`: 删除 `screenshot_table_from_pdf`，新增 `render_pages` (pdf2image 全页渲染) + `detect_table_pages` (pdfplumber 页级存在性检测)
- `models/section.py`: `TableInfo.image_path` → `page_images: list[str]`，删除未使用的 `TableData`
- `parser.py`: 表格初始化 `page_images=[]`，后台渲染阶段填充
- `assets.py`: 新增 `GET /{doc_id}/pages/{filename}` 页面图片路由
- 设计理念：图片给多模态大模型看，JSON 结构化数据做精确检索，两者互补

### ✅ 人员追溯字段

- `DocumentResponse` / `DocumentListItem` 新增 `uploaded_by` 和 `reviewed_by`
- `POST /upload` → 前端填上传人
- `POST /{doc_id}/commit` → 前端填审核人
- Swagger UI 默认占位文字 `"string"` 过滤为 `None`

### ✅ 向量索引入库 (bge-m3 + FAISS + SQLite)

同事提供了四层 FAISS 参考代码，在此基础上适配：

**架构**：
| 层级 | 索引 | 用途 |
|------|------|------|
| 第1层 | `doc_names.faiss` | 按文档名语义检索 |
| 第2层 | `chapters_XXXX.faiss` | 按章节标题检索 |
| 第3层 | `section_XXXX_XXXX.faiss` | 按正文内容块检索 |
| 第4层 | `assets_XXXX.faiss` | 按图表标题检索 |

- **模型**：`bge-m3` (BAAI 中文优化, 1024维)，服务器 CPU 推理
- **元数据**：SQLite 五张表 (doc/chapter/chunk/image/table)，适配 `page_images` 和 `doc_uuid` 关联
- **幂等入库**：同篇文档重复调 index 自动覆盖
- **触发时机**：commit 审核通过后后台自动执行
- **HF 镜像**：`hf-mirror.com` 环境变量已配，国内可下载模型
- 服务器 `poppler-utils` 缺失导致 pdf2image 渲染失败——待安装

### ✅ PDF 预览接口重构

- `GET /{doc_id}/preview.pdf` → `StreamingResponse` + `Content-Disposition: inline` (浏览器内嵌)
- `GET /{doc_id}/download.pdf` → `FileResponse` + `Content-Disposition: attachment` (强制下载)
- 256KB 分块流式传输，支持 `Accept-Ranges: bytes`

### ✅ 向量索引管理 API

| 端点 | 用途 |
|------|------|
| `GET /api/index/status` | 索引概览 (文档数/chunk数/磁盘占用/文档列表) |
| `POST /api/index/rebuild` | 全量重建索引 (后台异步) |
| `DELETE /api/index/documents/{id}` | 从索引中删除某篇文档 |

indexer 支持：
- `delete_by_uuid` → SQLite 级联删除 + FAISS 文件清理 + doc_names 重建
- `get_status` → 统计信息 + 文档清单

### ✅ 文档生命周期管理

| 端点 | 用途 |
|------|------|
| `GET /api/documents/stats` | 按状态统计 + 磁盘占用估算 |
| `POST /api/documents/cleanup` | 批量清理死文档，body: `["UPLOADED", "FAILED"]` |
| `DELETE /api/documents/{id}` | 删除文档 → 同步清磁盘 + 向量索引 |

**保护机制**：`COMPLETED` 在 cleanup 中硬拦截，入库成品不可误删。

### 📋 待验证

- [ ] 服务器安装 `poppler-utils` (`sudo apt install -y poppler-utils`)
- [ ] 重新上传文档跑通 "上传 → 样式扫描 → 解析 → 审核 → commit → 索引" 全流程
- [ ] 全页渲染表格截图效果验证 (多模态大模型分析)
- [ ] 向量检索精度验证 (bge-m3 在桥梁领域的语义匹配效果)
