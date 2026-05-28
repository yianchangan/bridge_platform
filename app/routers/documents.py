from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.db.memory_store import store
from app.models.document import DocStatus, DocumentResponse, DocumentListItem
from app.models.section import SectionData, SectionUpdate, ParsedResult, TableInfo
from app.services.parser import WordParser, compute_md5, scan_styles
from app.services.storage import save_upload_file
from app.services import converter
from app.config import settings

router = APIRouter(prefix="/api/documents", tags=["文档管理"])


# ---- 上传 (仅保存 + 自动扫描样式) ----

@router.post("/upload", response_model=DocumentResponse, summary="上传 Word 文档 (仅保存并扫描样式, 不解析)")
async def upload_document(
    file: UploadFile = File(..., description="Word 文件 (.docx)"),
    bridge_type: str = Form(..., description="桥型: 斜拉桥/悬索桥/拱桥/连续梁/连续刚构/综合工程/其它"),
    doc_type: str = Form(..., description="方案类型: 招投标方案/实施性施工组织方案/专项方案/作业指导书/技术交底书"),
    doc_title: str = Form(..., description="方案名称"),
    uploaded_by: Optional[str] = Form(default=None, description="上传人"),
):
    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 格式的 Word 文件")

    valid_bridge_types = {"斜拉桥", "悬索桥", "拱桥", "连续梁", "连续刚构", "综合工程", "其它"}
    valid_doc_types = {"招投标方案", "实施性施工组织方案", "专项方案", "作业指导书", "技术交底书"}
    if bridge_type not in valid_bridge_types:
        raise HTTPException(status_code=400, detail=f"无效的桥型: {bridge_type}")
    if doc_type not in valid_doc_types:
        raise HTTPException(status_code=400, detail=f"无效的方案类型: {doc_type}")

    # 保存到临时目录
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    md5 = compute_md5(tmp_path)
    doc = store.create_document(
        doc_title=doc_title,
        bridge_type=bridge_type,
        doc_type=doc_type,
        md5=md5,
        uploaded_by=uploaded_by,
    )

    # 移至正式目录
    doc_file_path = save_upload_file(tmp_path, doc.id)
    os.unlink(tmp_path)

    # 自动扫描样式
    try:
        styles_result = scan_styles(doc_file_path)
        store.update_scanned_styles(doc.id, styles_result)
        doc.scanned_styles = styles_result
    except Exception as e:
        print(f"[警告] 样式扫描失败: {e}")

    return doc


# ---- 配置并启动解析 ----

@router.post("/{doc_id}/parse", response_model=DocumentResponse, summary="配置解析参数并启动解析流水线")
async def parse_document(
    doc_id: str,
    max_heading_level: int = Form(default=5, ge=1, le=5, description="最大标题层级 1-5, 超出不拆分"),
    regex_level1: Optional[str] = Form(default=None, description="一级标题正则(可选)"),
    regex_level2: Optional[str] = Form(default=None, description="二级标题正则(可选)"),
    regex_level3: Optional[str] = Form(default=None, description="三级标题正则(可选)"),
    regex_level4: Optional[str] = Form(default=None, description="四级标题正则(可选)"),
    regex_level5: Optional[str] = Form(default=None, description="五级标题正则(可选)"),
    body_styles: str = Form(default="Normal", description="纳入正文的段落样式, 逗号分隔, 如 'Normal,List Paragraph,Quote'"),
    image_caption_style: str = Form(default="图标题", description="图标题样式名"),
    table_caption_style: str = Form(default="表标题", description="表标题样式名"),
):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    docx_path = os.path.join(settings.storage_path, doc_id, "raw.docx")
    if not os.path.exists(docx_path):
        raise HTTPException(status_code=404, detail="原始文档文件不存在, 请先上传")

    regex_config = {}
    if regex_level1:
        regex_config["level1"] = regex_level1
    if regex_level2:
        regex_config["level2"] = regex_level2
    if regex_level3:
        regex_config["level3"] = regex_level3
    if regex_level4:
        regex_config["level4"] = regex_level4
    if regex_level5:
        regex_config["level5"] = regex_level5

    body_styles_list = [s.strip() for s in body_styles.split(",") if s.strip()]

    updated = store.configure_parsing(
        doc_id=doc_id,
        regex_config=regex_config if regex_config else None,
        max_heading_level=max_heading_level,
        body_styles=body_styles_list,
        image_caption_style=image_caption_style.strip(),
        table_caption_style=table_caption_style.strip(),
    )

    _process_document_background(doc_id)
    return updated


def _process_document_background(doc_id: str):
    """后台处理: Word → PDF → 解析 → 截图"""
    import threading

    def worker():
        try:
            docx_path = os.path.join(settings.storage_path, doc_id, "raw.docx")

            # 阶段1: Word 转 PDF
            store.update_document_status(doc_id, status=DocStatus.converting, progress=10)

            doc_dir = os.path.join(settings.storage_path, doc_id)
            pdf_path = converter.word_to_pdf(docx_path, doc_dir)

            if pdf_path:
                store.update_document_status(
                    doc_id, status=DocStatus.converting, progress=30, pdf_path=pdf_path
                )
            else:
                print(f"[警告] 文档 {doc_id} PDF 转换失败, 继续解析 Word")

            # 阶段2: 解析 Word
            store.update_document_status(doc_id, status=DocStatus.parsing, progress=40)

            doc_record = store.get_document(doc_id)
            regex_config = doc_record.regex_config if doc_record else None
            max_level = doc_record.max_heading_level if doc_record else 5
            body_styles = getattr(doc_record, 'body_styles', None) or ["Normal"]
            img_cap = getattr(doc_record, 'image_caption_style', None) or "图标题"
            tbl_cap = getattr(doc_record, 'table_caption_style', None) or "表标题"

            parser = WordParser(docx_path, doc_id, settings.storage_path,
                               regex_config=regex_config, max_heading_level=max_level,
                               body_styles=body_styles,
                               image_caption_style=img_cap,
                               table_caption_style=tbl_cap)
            sections = parser.parse()

            store.update_document_status(doc_id, progress=70)

            # 阶段3: 表格截图 (如有 PDF)
            if pdf_path:
                _screenshot_tables(doc_id, pdf_path, sections)

            store.update_document_status(doc_id, progress=90)

            # 阶段4: 保存解析结果
            store.save_parsed_result(doc_id, sections)

        except Exception as e:
            store.update_document_status(
                doc_id, status=DocStatus.failed, error_message=str(e)
            )
            print(f"[错误] 文档 {doc_id} 处理失败: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def _screenshot_tables(doc_id: str, pdf_path: str, sections: list[SectionData]):
    """全页渲染 + 表格→页码映射, 不再裁剪单表截图"""
    pages_dir = os.path.join(settings.storage_path, doc_id, "pages")
    rel_prefix = f"/storage/doc_assets/{doc_id}"

    # 1. 渲染所有 PDF 页面为高清图片
    page_paths = converter.render_pages(pdf_path, pages_dir, dpi=200)

    # 2. 检测哪些页包含表格
    table_page_nums = converter.detect_table_pages(pdf_path)

    # 3. 统计所有 docx 表格 (按解析顺序)
    all_tables: list[TableInfo] = []
    for sec in sections:
        all_tables.extend(sec.tables)

    n_docx = len(all_tables)
    n_pdf_pages = len(table_page_nums)

    if n_docx == 0:
        return

    # 4. 将 docx 表格映射到 PDF 页面
    #    每个 docx 表至少分配一页, 如果 pdfplumber 漏检则兜底为全部分配页面
    if n_pdf_pages == 0:
        # 完全检测不到表格 → 把所有页面都给每个表 (兜底, 大模型自己找)
        all_page_rel = [f"{rel_prefix}/pages/page_{i + 1}.png" for i in range(len(page_paths))]
        for tbl in all_tables:
            tbl.page_images = all_page_rel
    else:
        for i, tbl in enumerate(all_tables):
            if i < n_pdf_pages:
                page_num = table_page_nums[i]
            else:
                page_num = table_page_nums[-1]
            tbl.page_images = [f"{rel_prefix}/pages/page_{page_num}.png"]


# ---- 样式扫描 ----

@router.get("/{doc_id}/styles", summary="扫描文档中所有使用的段落样式")
async def get_document_styles(doc_id: str):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    doc_dir = os.path.join(settings.storage_path, doc_id)
    docx_path = os.path.join(doc_dir, "raw.docx")
    if not os.path.exists(docx_path):
        raise HTTPException(status_code=404, detail="原始文档文件不存在, 请先上传")

    return scan_styles(docx_path)


# ---- 文档列表 ----

@router.get("", response_model=list[DocumentListItem], summary="获取文档列表")
async def list_documents():
    return store.list_documents()


# ---- 文档状态 ----

@router.get("/{doc_id}/status", summary="查询文档解析状态和进度")
async def get_document_status(doc_id: str):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {
        "id": doc.id,
        "status": doc.status,
        "progress": doc.progress,
        "sections_count": doc.sections_count,
        "error_message": doc.error_message,
    }


# ---- 获取解析结果 ----

@router.get("/{doc_id}/parsed", response_model=ParsedResult, summary="获取文档解析结果")
async def get_parsed_result(doc_id: str):
    result = store.get_parsed_result(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return result


# ---- 保存审核草稿 ----

@router.put("/{doc_id}/draft", summary="保存审核草稿")
async def save_draft(doc_id: str, sections: list[SectionData]):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    store.save_draft(doc_id, sections)
    return {"success": True}


# ---- 确认提交入库 ----

@router.post("/{doc_id}/commit", summary="确认审核并提交入库")
async def commit_document(
    doc_id: str,
    reviewed_by: Optional[str] = Form(default=None, description="审核人"),
):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status not in (DocStatus.pending_review, DocStatus.completed):
        raise HTTPException(status_code=400, detail="文档状态不允许入库")
    store.commit_document(doc_id, reviewed_by=reviewed_by)

    # 后台触发向量索引入库
    _index_document_background(doc_id)

    return {"success": True, "doc_id": doc_id}


def _index_document_background(doc_id: str):
    """后台向量索引入库"""
    import threading

    def worker():
        try:
            from app.services.indexer import DocumentIndexer
            indexer = DocumentIndexer(
                settings.index_db_path, settings.faiss_dir, settings.db_path
            )
            indexer.index_document(doc_id)
        except Exception as e:
            print(f"[索引] 文档 {doc_id} 后台入库失败: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


@router.post("/{doc_id}/index", summary="手动触发向量索引入库")
async def manual_index(doc_id: str):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status != DocStatus.completed:
        raise HTTPException(status_code=400, detail="文档未完成审核, 无法入库索引")

    _index_document_background(doc_id)
    return {"success": True, "doc_id": doc_id, "message": "已触发后台索引入库"}


# ---- 删除文档 ----

@router.delete("/{doc_id}", summary="删除文档及所有资源")
async def delete_document(doc_id: str):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 删除资源目录
    doc_dir = os.path.join(settings.storage_path, doc_id)
    if os.path.exists(doc_dir):
        shutil.rmtree(doc_dir)

    store.delete_document(doc_id)
    return {"success": True}


# ---- 章节操作 ----

@router.put("/{doc_id}/sections/{section_id}", response_model=SectionData, summary="更新章节")
async def update_section(doc_id: str, section_id: str, update: SectionUpdate):
    result = store.update_section(doc_id, section_id, update)
    if not result:
        raise HTTPException(status_code=404, detail="章节不存在")
    return result


@router.delete("/{doc_id}/sections/{section_id}", summary="删除章节")
async def delete_section(doc_id: str, section_id: str):
    if not store.delete_section(doc_id, section_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"success": True}


@router.post("/{doc_id}/sections", response_model=ParsedResult, summary="新增章节")
async def add_section(doc_id: str, section: SectionData):
    if not section.id:
        section.id = str(uuid.uuid4())
    result = store.add_section(doc_id, section)
    if not result:
        raise HTTPException(status_code=404, detail="文档不存在")
    return result
