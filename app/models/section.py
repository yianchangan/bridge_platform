from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ImageInfo(BaseModel):
    caption: str = Field(..., description="图标题, 如 '图2.2-1项目地理位置示意图'")
    local_path: str = Field(..., description="图片存储相对路径")
    original_name: Optional[str] = Field(default=None, description="原始提取文件名")


class TableInfo(BaseModel):
    caption: str = Field(..., description="表标题")
    page_images: list[str] = Field(default_factory=list, description="包含该表格的页面图片路径列表")
    json_path: Optional[str] = None
    data: Optional[list[list[str]]] = None
    parse_success: bool = True


class TagInfo(BaseModel):
    tag_id: Optional[str] = None
    tag_name: str
    tag_type: Optional[str] = None
    confidence: Optional[float] = None


class SectionData(BaseModel):
    id: str = Field(..., description="章节唯一ID")
    level: int = Field(..., description="标题层级 1/2/3")
    title: str = Field(..., description="章节标题")
    text: str = Field(default="", description="正文, 含【图/表】占位符")
    images: list[ImageInfo] = Field(default_factory=list)
    tables: list[TableInfo] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="标签名称列表")
    parent_id: Optional[str] = Field(default=None, description="上级章节ID")
    section_order: int = Field(default=0, description="文档中物理顺序")


class SectionUpdate(BaseModel):
    title: Optional[str] = None
    level: Optional[int] = None
    text: Optional[str] = None
    images: Optional[list[ImageInfo]] = None
    tables: Optional[list[TableInfo]] = None
    tags: Optional[list[str]] = None
    parent_id: Optional[str] = None


class ParsedResult(BaseModel):
    doc_id: str
    sections: list[SectionData] = Field(default_factory=list)
