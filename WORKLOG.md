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
