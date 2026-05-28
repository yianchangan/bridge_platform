from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.services.indexer import DocumentIndexer

router = APIRouter(prefix="/api/index", tags=["向量索引管理"])


def _get_indexer() -> DocumentIndexer:
    return DocumentIndexer(settings.index_db_path, settings.faiss_dir, settings.db_path)


@router.get("/status", summary="索引入库概览")
async def index_status():
    indexer = _get_indexer()
    return indexer.get_status()


@router.post("/rebuild", summary="全量重建索引 (从 store.json)")
async def index_rebuild():
    import threading

    def worker():
        try:
            indexer = _get_indexer()
            indexer.rebuild_all()
        except Exception as e:
            print(f"[索引] 全量重建失败: {e}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return {"success": True, "message": "已触发后台全量重建"}


@router.delete("/documents/{doc_id}", summary="从索引中删除指定文档")
async def index_delete_document(doc_id: str):
    indexer = _get_indexer()
    ok = indexer.delete_by_uuid(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不在索引中")
    return {"success": True, "doc_id": doc_id, "message": "已从索引中删除"}
