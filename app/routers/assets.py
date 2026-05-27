from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter(prefix="/storage/doc_assets", tags=["静态资源"])


@router.get("/{doc_id}/images/{filename}", summary="获取提取的图片")
async def get_image(doc_id: str, filename: str):
    path = os.path.join(settings.storage_path, doc_id, "images", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="图片不存在")
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


@router.get("/{doc_id}/preview.pdf", summary="获取 PDF 预览文件")
async def get_preview_pdf(doc_id: str):
    doc_dir = os.path.join(settings.storage_path, doc_id)
    if not os.path.exists(doc_dir):
        raise HTTPException(status_code=404, detail="文档目录不存在")

    for f in os.listdir(doc_dir):
        if f.endswith(".pdf"):
            return FileResponse(
                os.path.join(doc_dir, f),
                media_type="application/pdf",
                filename=f"{doc_id}_preview.pdf",
            )

    raise HTTPException(status_code=404, detail="PDF 预览文件不存在")


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
