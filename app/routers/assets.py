from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings

router = APIRouter(prefix="/storage/doc_assets", tags=["静态资源"])


def _find_pdf(doc_id: str) -> Path:
    """查找文档目录下的 PDF 文件, 返回完整路径."""
    doc_dir = os.path.join(settings.storage_path, doc_id)
    if not os.path.exists(doc_dir):
        return None
    for f in os.listdir(doc_dir):
        if f.endswith(".pdf"):
            return Path(doc_dir) / f
    return None


@router.get("/{doc_id}/images/{filename}", summary="获取提取的图片")
async def get_image(doc_id: str, filename: str):
    path = os.path.join(settings.storage_path, doc_id, "images", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path, media_type="image/png")


@router.get("/{doc_id}/pages/{filename}", summary="获取 PDF 页面渲染图片")
async def get_page_image(doc_id: str, filename: str):
    path = os.path.join(settings.storage_path, doc_id, "pages", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="页面图片不存在")
    return FileResponse(path, media_type="image/png")


@router.get("/{doc_id}/tables/{filename}", summary="获取表格资源 (JSON/PNG)")
async def get_table_asset(doc_id: str, filename: str):
    path = os.path.join(settings.storage_path, doc_id, "tables", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="资源不存在")

    if filename.endswith(".json"):
        return FileResponse(path, media_type="application/json")
    elif filename.endswith(".png"):
        return FileResponse(path, media_type="image/png")
    else:
        return FileResponse(path)


@router.get("/{doc_id}/preview.pdf", summary="PDF 流式预览 (浏览器内嵌显示)")
async def get_preview_pdf(doc_id: str):
    pdf_path = _find_pdf(doc_id)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="PDF 预览文件不存在")

    def file_iterator():
        chunk_size = 256 * 1024  # 256KB
        with open(pdf_path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    return StreamingResponse(
        file_iterator(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename={pdf_path.name}",
            "Accept-Ranges": "bytes",
        },
    )


@router.get("/{doc_id}/download.pdf", summary="PDF 下载 (强制另存为)")
async def download_pdf(doc_id: str):
    pdf_path = _find_pdf(doc_id)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@router.get("/{doc_id}/raw.docx", summary="获取原始 Word 文件")
async def get_raw_docx(doc_id: str):
    path = os.path.join(settings.storage_path, doc_id, "raw.docx")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="原始文件不存在")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{doc_id}_raw.docx",
    )
