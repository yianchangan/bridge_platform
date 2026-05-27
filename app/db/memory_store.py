from __future__ import annotations

import json
import os
import threading
from typing import Optional

from app.models.document import (
    DocStatus,
    DocumentResponse,
    DocumentListItem,
    DocumentBrief,
    new_doc_id,
    now_str,
)
from app.models.section import SectionData, SectionUpdate, ParsedResult


class MemoryStore:
    """
    临时内存存储, 后续替换为 PostgreSQL。

    线程安全: 使用 threading.Lock 保护并发写入。
    启动时从 JSON 文件恢复, 关闭时持久化。
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._documents: dict[str, dict] = {}
        self._parsed: dict[str, dict] = {}

    def configure(self, persist_path: str) -> None:
        """配置持久化路径并从文件恢复数据(如果存在)"""
        with self._lock:
            self._persist_path = persist_path
            if os.path.exists(persist_path):
                self._load()

    # ---- 文档操作 ----

    def create_document(
        self,
        doc_title: str,
        bridge_type: str,
        doc_type: str,
        file_path: Optional[str] = None,
        md5: Optional[str] = None,
        scanned_styles: Optional[dict] = None,
    ) -> DocumentResponse:
        doc_id = new_doc_id()
        doc = {
            "id": doc_id,
            "doc_title": doc_title,
            "bridge_type": bridge_type,
            "doc_type": doc_type,
            "status": DocStatus.uploaded.value,
            "upload_time": now_str(),
            "file_path": file_path,
            "pdf_path": None,
            "md5": md5,
            "sections_count": 0,
            "progress": 0,
            "regex_config": None,
            "max_heading_level": 5,
            "body_styles": ["Normal"],
            "image_caption_style": "图标题",
            "table_caption_style": "表标题",
            "scanned_styles": scanned_styles,
            "error_message": None,
        }
        with self._lock:
            self._documents[doc_id] = doc
            self._persist()
        return DocumentResponse(**doc)

    def configure_parsing(
        self,
        doc_id: str,
        regex_config: Optional[dict] = None,
        max_heading_level: int = 5,
        body_styles: Optional[list[str]] = None,
        image_caption_style: str = "图标题",
        table_caption_style: str = "表标题",
    ) -> Optional[DocumentResponse]:
        """配置解析参数并更新文档状态为 converting"""
        with self._lock:
            doc = self._documents.get(doc_id)
            if not doc:
                return None
            if regex_config is not None:
                doc["regex_config"] = regex_config
            doc["max_heading_level"] = max_heading_level
            if body_styles is not None:
                doc["body_styles"] = body_styles
            doc["image_caption_style"] = image_caption_style
            doc["table_caption_style"] = table_caption_style
            doc["status"] = DocStatus.converting.value
            doc["progress"] = 0
            doc["error_message"] = None
            self._persist()
        return DocumentResponse(**doc)

    def get_document(self, doc_id: str) -> Optional[DocumentResponse]:
        with self._lock:
            doc = self._documents.get(doc_id)
        return DocumentResponse(**doc) if doc else None

    def list_documents(self) -> list[DocumentListItem]:
        with self._lock:
            docs = list(self._documents.values())
        return [
            DocumentListItem(
                id=d["id"],
                doc_title=d["doc_title"],
                bridge_type=d["bridge_type"],
                doc_type=d["doc_type"],
                status=d["status"],
                upload_time=d["upload_time"],
                sections_count=d["sections_count"],
                progress=d["progress"],
            )
            for d in docs
        ]

    def update_document_status(
        self,
        doc_id: str,
        status: Optional[DocStatus] = None,
        progress: Optional[int] = None,
        sections_count: Optional[int] = None,
        pdf_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[DocumentResponse]:
        with self._lock:
            doc = self._documents.get(doc_id)
            if not doc:
                return None
            if status is not None:
                doc["status"] = status.value
            if progress is not None:
                doc["progress"] = progress
            if sections_count is not None:
                doc["sections_count"] = sections_count
            if pdf_path is not None:
                doc["pdf_path"] = pdf_path
            if error_message is not None:
                doc["error_message"] = error_message
            self._persist()
        return DocumentResponse(**doc)

    def update_scanned_styles(self, doc_id: str, styles_result: dict) -> bool:
        """更新文档的样式扫描结果"""
        with self._lock:
            doc = self._documents.get(doc_id)
            if not doc:
                return False
            doc["scanned_styles"] = styles_result
            self._persist()
        return True

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id not in self._documents:
                return False
            del self._documents[doc_id]
            self._parsed.pop(doc_id, None)
            self._persist()
        return True

    # ---- 解析结果操作 ----

    def save_parsed_result(self, doc_id: str, sections: list[SectionData]) -> ParsedResult:
        result = ParsedResult(doc_id=doc_id, sections=sections)
        with self._lock:
            self._parsed[doc_id] = result.model_dump()
            # 更新文档信息
            doc = self._documents.get(doc_id)
            if doc:
                doc["sections_count"] = len(sections)
                doc["status"] = DocStatus.pending_review.value
                doc["progress"] = 100
            self._persist()
        return result

    def get_parsed_result(self, doc_id: str) -> Optional[ParsedResult]:
        with self._lock:
            data = self._parsed.get(doc_id)
        return ParsedResult(**data) if data else None

    def update_section(
        self, doc_id: str, section_id: str, update: SectionUpdate
    ) -> Optional[SectionData]:
        with self._lock:
            data = self._parsed.get(doc_id)
            if not data:
                return None
            for i, sec in enumerate(data["sections"]):
                if sec["id"] == section_id:
                    for key, val in update.model_dump(exclude_unset=True).items():
                        if val is not None:
                            sec[key] = val
                    self._persist()
                    return SectionData(**sec)
        return None

    def delete_section(self, doc_id: str, section_id: str) -> bool:
        with self._lock:
            data = self._parsed.get(doc_id)
            if not data:
                return False
            before = len(data["sections"])
            data["sections"] = [s for s in data["sections"] if s["id"] != section_id]
            if len(data["sections"]) < before:
                doc = self._documents.get(doc_id)
                if doc:
                    doc["sections_count"] = len(data["sections"])
                self._persist()
                return True
        return False

    def add_section(self, doc_id: str, section: SectionData) -> Optional[ParsedResult]:
        with self._lock:
            data = self._parsed.get(doc_id)
            if not data:
                return None
            data["sections"].append(section.model_dump())
            doc = self._documents.get(doc_id)
            if doc:
                doc["sections_count"] = len(data["sections"])
            self._persist()
        return ParsedResult(**data)

    def save_draft(self, doc_id: str, sections: list[SectionData]) -> bool:
        """保存审核草稿"""
        with self._lock:
            self._parsed[doc_id] = {
                "doc_id": doc_id,
                "sections": [s.model_dump() for s in sections],
            }
            doc = self._documents.get(doc_id)
            if doc:
                doc["sections_count"] = len(sections)
            self._persist()
        return True

    def commit_document(self, doc_id: str) -> bool:
        """标记文档为已入库"""
        with self._lock:
            doc = self._documents.get(doc_id)
            if not doc:
                return False
            doc["status"] = DocStatus.completed.value
            self._persist()
        return True

    # ---- 持久化 ----

    def _persist(self):
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"documents": self._documents, "parsed": self._parsed},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"[警告] 持久化失败: {e}")

    def _load(self):
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._documents = data.get("documents", {})
            self._parsed = data.get("parsed", {})
        except Exception as e:
            print(f"[警告] 加载持久化数据失败: {e}")


# 全局单例
store = MemoryStore()
