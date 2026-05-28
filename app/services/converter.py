from __future__ import annotations

import os
import subprocess
from typing import Optional


def word_to_pdf(doc_path: str, output_dir: str) -> Optional[str]:
    """
    将 Word 文档转换为 PDF, 使用 LibreOffice headless 模式。

    Args:
        doc_path: Word 文件路径
        output_dir: PDF 输出目录

    Returns:
        生成的 PDF 文件路径, 失败返回 None
    """
    if not os.path.exists(doc_path):
        return None

    os.makedirs(output_dir, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", output_dir,
                doc_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"[转换错误] LibreOffice 转换失败: {result.stderr}")
            return None

        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            return pdf_path

        for f in os.listdir(output_dir):
            if f.endswith(".pdf"):
                return os.path.join(output_dir, f)

        return None

    except FileNotFoundError:
        print("[转换错误] 未找到 LibreOffice, 请安装: apt install libreoffice")
        return None
    except subprocess.TimeoutExpired:
        print("[转换错误] LibreOffice 转换超时")
        return None


def render_pages(pdf_path: str, output_dir: str, dpi: int = 200) -> list[str]:
    """将 PDF 每一页渲染为高清 PNG, 返回绝对路径列表."""
    from pdf2image import convert_from_path

    os.makedirs(output_dir, exist_ok=True)

    images = convert_from_path(pdf_path, dpi=dpi)
    paths = []
    for i, img in enumerate(images):
        path = os.path.join(output_dir, f"page_{i + 1}.png")
        img.save(path, "PNG")
        paths.append(path)

    return paths


def detect_table_pages(pdf_path: str) -> list[int]:
    """
    用 pdfplumber 检测 PDF 中哪些页包含表格, 返回页码列表 (1-based).

    仅做页级存在性检测, 不要求精确 bbox, 远比单表裁剪可靠.
    """
    try:
        import pdfplumber

        pages_with_tables = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                tables = page.find_tables()
                if tables:
                    pages_with_tables.append(i + 1)

        return pages_with_tables

    except ImportError:
        print("[警告] pdfplumber 未安装, 表格页检测不可用")
        return []
    except Exception as e:
        print(f"[警告] 表格页检测失败: {e}")
        return []
