from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BridgeType(str, Enum):
    cable_stayed = "斜拉桥"
    suspension = "悬索桥"
    arch = "拱桥"
    continuous_beam = "连续梁"
    rigid_frame = "连续刚构"
    comprehensive = "综合工程"
    other = "其它"


class DocType(str, Enum):
    bidding = "招投标方案"
    construction_org = "实施性施工组织方案"
    special = "专项方案"
    work_instruction = "作业指导书"
    technical_briefing = "技术交底书"


class DocStatus(str, Enum):
    uploaded = "UPLOADED"
    uploading = "UPLOADING"
    converting = "CONVERTING"
    parsing = "PARSING"
    pending_review = "PENDING_REVIEW"
    completed = "COMPLETED"
    failed = "FAILED"


class DocumentCreate(BaseModel):
    doc_title: str = Field(..., description="方案名称")
    bridge_type: BridgeType = Field(..., description="桥型归类")
    doc_type: DocType = Field(..., description="方案类型归类")
    regex_config: Optional[dict] = Field(
        default=None,
        description="自定义正则拆分配置, 如 {'level1': '^一、', 'level2': '^[0-9]+\\.[0-9]+'}",
    )


class DocumentBrief(BaseModel):
    id: str
    doc_title: str
    bridge_type: str
    doc_type: str
    status: DocStatus
    upload_time: str
    sections_count: int = 0
    progress: int = 0


class DocumentResponse(BaseModel):
    id: str
    doc_title: str
    bridge_type: str
    doc_type: str
    status: DocStatus
    upload_time: str
    file_path: Optional[str] = None
    pdf_path: Optional[str] = None
    md5: Optional[str] = None
    sections_count: int = 0
    progress: int = 0
    regex_config: Optional[dict] = None
    max_heading_level: int = 5
    body_styles: list[str] = ["Normal"]
    image_caption_style: str = "图标题"
    table_caption_style: str = "表标题"
    scanned_styles: Optional[dict] = None
    error_message: Optional[str] = None


class DocumentStatus(BaseModel):
    id: str
    status: DocStatus
    progress: int = 0
    sections_count: int = 0
    error_message: Optional[str] = None


class DocumentListItem(BaseModel):
    id: str
    doc_title: str
    bridge_type: str
    doc_type: str
    status: DocStatus
    upload_time: str
    sections_count: int = 0
    progress: int = 0


def new_doc_id() -> str:
    return str(uuid.uuid4())


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
