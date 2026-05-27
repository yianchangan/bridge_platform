from __future__ import annotations

import os
import shutil
from typing import Optional

from app.config import settings


def save_upload_file(src_path: str, doc_id: str) -> str:
    """
    将上传的 Word 文件保存到文档资源目录。

    Returns:
        保存后的文件路径
    """
    doc_dir = os.path.join(settings.storage_path, doc_id)
    os.makedirs(doc_dir, exist_ok=True)

    dest = os.path.join(doc_dir, "raw.docx")
    shutil.copy2(src_path, dest)
    return dest


def get_doc_dir(doc_id: str) -> str:
    """获取文档资源目录"""
    return os.path.join(settings.storage_path, doc_id)


def get_raw_docx(doc_id: str) -> Optional[str]:
    """获取原始 Word 文件路径"""
    path = os.path.join(settings.storage_path, doc_id, "raw.docx")
    return path if os.path.exists(path) else None


def get_preview_pdf(doc_id: str) -> Optional[str]:
    """获取预览 PDF 路径"""
    doc_dir = os.path.join(settings.storage_path, doc_id)
    for f in os.listdir(doc_dir):
        if f.endswith(".pdf"):
            return os.path.join(doc_dir, f)
    return None


def get_images_dir(doc_id: str) -> str:
    """获取图片目录"""
    path = os.path.join(settings.storage_path, doc_id, "images")
    os.makedirs(path, exist_ok=True)
    return path


def get_tables_dir(doc_id: str) -> str:
    """获取表格目录"""
    path = os.path.join(settings.storage_path, doc_id, "tables")
    os.makedirs(path, exist_ok=True)
    return path
