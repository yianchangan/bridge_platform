from __future__ import annotations

import os
import subprocess
import tempfile
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

        # 找到生成的 PDF
        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        if os.path.exists(pdf_path):
            return pdf_path

        # 尝试在输出目录中找任意 PDF
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


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 200) -> list[str]:
    """
    将 PDF 转换为图片列表 (每页一张), 用于预览。

    Args:
        pdf_path: PDF 文件路径
        output_dir: 图片输出目录
        dpi: 图片分辨率

    Returns:
        生成的图片路径列表
    """
    try:
        from pdf2image import convert_from_path

        os.makedirs(output_dir, exist_ok=True)
        images = convert_from_path(pdf_path, dpi=dpi)
        image_paths = []

        for i, img in enumerate(images):
            img_path = os.path.join(output_dir, f"page_{i + 1}.png")
            img.save(img_path, "PNG")
            image_paths.append(img_path)

        return image_paths

    except ImportError:
        print("[警告] pdf2image 未安装, PDF 转图片功能不可用")
        return []
    except Exception as e:
        print(f"[警告] PDF 转图片失败: {e}")
        return []


def screenshot_table_from_pdf(
    pdf_path: str,
    table_caption: str,
    output_dir: str,
    table_index: int = 0,
) -> Optional[str]:
    """
    从 PDF 中截取表格的截图。

    使用 pdfplumber 定位表格边界, 然后从 PDF 页面图片中裁剪。

    Args:
        pdf_path: PDF 文件路径
        table_caption: 表标题, 用于命名输出文件
        output_dir: 截图输出目录
        table_index: 文档中第几个表格 (0-based)

    Returns:
        截图文件路径, 失败返回 None
    """
    try:
        import pdfplumber
        from PIL import Image as PILImage

        os.makedirs(output_dir, exist_ok=True)

        current_table = 0
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                tables = page.find_tables()
                for tbl in tables:
                    if current_table == table_index:
                        bbox = tbl.bbox  # (x0, top, x1, bottom)
                        # 获取该页图片并裁剪
                        page_img = page.to_image(resolution=300)
                        pil_img = page_img.original

                        # 添加表标题区域 (向上扩展一些)
                        x0, top, x1, bottom = bbox
                        crop_box = (
                            max(0, x0 - 10),
                            max(0, top - 30),
                            min(pil_img.width, x1 + 10),
                            min(pil_img.height, bottom + 10),
                        )
                        cropped = pil_img.crop(crop_box)

                        safe_name = _safe_filename(table_caption)
                        out_path = os.path.join(output_dir, f"{safe_name}.png")
                        cropped.save(out_path, "PNG")
                        return out_path

                    current_table += 1

        return None

    except ImportError:
        print("[警告] pdfplumber 未安装, 表格截图功能不可用")
        return None
    except Exception as e:
        print(f"[警告] 表格截图失败: {e}")
        return None


def _safe_filename(text: str) -> str:
    import re
    return re.sub(r'[\/:*?"<>|]', '_', text).strip()
