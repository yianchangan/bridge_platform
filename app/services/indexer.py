from __future__ import annotations

import json
import os
import pickle
import shutil
import sqlite3
import time
from typing import Optional

# 必须在 import sentence_transformers 之前设置
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HUGGINGFACE_HUB_URL", "https://hf-mirror.com")

import numpy as np


VECTOR_DIM = 1024  # bge-m3
CHUNK_SIZE = 2000

BRIDGE_TYPE_MAP = {
    "梁": "梁桥", "拱": "拱桥", "悬索": "悬索桥",
    "斜拉": "斜拉桥", "刚构": "刚构桥",
}
DEFAULT_BRIDGE_TYPE = "梁桥"


def _guess_bridge_type(doc_name: str) -> str:
    for keyword, bt in BRIDGE_TYPE_MAP.items():
        if keyword in doc_name:
            return bt
    return DEFAULT_BRIDGE_TYPE


class DocumentIndexer:
    """四层 FAISS 向量索引 + SQLite 元数据库, 支持增量入库和删除."""

    def __init__(self, db_path: str, faiss_dir: str, store_json_path: str):
        self.db_path = db_path
        self.faiss_dir = faiss_dir
        self.store_json_path = store_json_path
        self._model = None

    # ---- 模型懒加载 ----
    def _load_model(self):
        if self._model is not None:
            return self._model

        from sentence_transformers import SentenceTransformer

        local = os.path.join(
            os.path.expanduser("~"),
            ".cache/huggingface/hub/models--BAAI--bge-m3/snapshots/"
            "5617a9f61b028005a4858fdac845db406aefb181",
        )
        model_path = local if os.path.exists(local) else "BAAI/bge-m3"
        print(f"[索引] 加载 bge-m3 模型: {model_path}")
        self._model = SentenceTransformer(model_path)
        return self._model

    # ---- 数据库初始化 ----
    def _ensure_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS doc_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_uuid TEXT NOT NULL,
            bridge_type TEXT NOT NULL,
            doc_name TEXT NOT NULL,
            total_chapters INTEGER DEFAULT 0,
            chapter_faiss_path TEXT NOT NULL,
            assets_faiss_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # 兼容旧表: 尝试加 doc_uuid 列
        try:
            c.execute("ALTER TABLE doc_index ADD COLUMN doc_uuid TEXT")
        except sqlite3.OperationalError:
            pass

        c.execute("""CREATE TABLE IF NOT EXISTS chapter_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            chapter_title TEXT NOT NULL,
            chapter_level INTEGER DEFAULT 0,
            section_faiss_path TEXT NOT NULL,
            total_chunks INTEGER DEFAULT 0,
            FOREIGN KEY (doc_id) REFERENCES doc_index(id) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chunk_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_idx INTEGER DEFAULT 0,
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS image_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            caption TEXT NOT NULL,
            local_path TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id) ON DELETE CASCADE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS table_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            caption TEXT NOT NULL,
            page_images TEXT DEFAULT '[]',
            json_path TEXT DEFAULT '',
            data TEXT DEFAULT '',
            parse_success INTEGER DEFAULT 0,
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id) ON DELETE CASCADE
        )""")
        for idx in ["doc_index(doc_uuid)", "doc_index(bridge_type)", "chapter_index(doc_id)",
                     "chunk_index(chapter_id)", "image_index(chapter_id)",
                     "table_index(chapter_id)"]:
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{idx.replace('(', '_').replace(')', '')} ON {idx}")
        conn.commit()
        return conn

    # ---- 向量化工具 ----
    def _encode(self, texts: list[str]) -> np.ndarray:
        model = self._load_model()
        vecs = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
            batch_size=8, convert_to_numpy=True,
        )
        return np.array(vecs, dtype="float32")

    def _save_faiss(self, vectors: np.ndarray, path: str):
        import faiss
        index = faiss.IndexFlatIP(VECTOR_DIM)
        index.add(vectors)
        faiss.write_index(index, path)

    # ---- 文件序号管理 ----
    def _next_doc_seq(self) -> int:
        os.makedirs(self.faiss_dir, exist_ok=True)
        max_seq = 0
        for f in os.listdir(self.faiss_dir):
            if f.startswith("chapters_") and f.endswith(".faiss"):
                try:
                    seq = int(f.replace("chapters_", "").replace(".faiss", ""))
                    max_seq = max(max_seq, seq)
                except ValueError:
                    pass
        return max_seq + 1

    # ---- 删除一篇文档的索引 ----
    def delete_by_uuid(self, doc_uuid: str) -> bool:
        """从 SQLite 和 FAISS 中删除指定文档的所有索引数据."""
        conn = self._ensure_db()
        c = conn.cursor()
        c.execute("SELECT id, chapter_faiss_path, assets_faiss_path FROM doc_index WHERE doc_uuid = ?", (doc_uuid,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False

        doc_pk, chapter_faiss, assets_faiss = row

        # 收集要删的 FAISS 文件
        faiss_files = []
        c.execute("SELECT section_faiss_path FROM chapter_index WHERE doc_id = ?", (doc_pk,))
        for (sf,) in c.fetchall():
            faiss_files.append(sf)
            faiss_files.append(sf.replace(".faiss", "_meta.pkl"))
        if chapter_faiss:
            faiss_files.append(chapter_faiss)
            faiss_files.append(chapter_faiss.replace(".faiss", "_meta.pkl"))
        if assets_faiss:
            faiss_files.append(assets_faiss)
            faiss_files.append(assets_faiss.replace(".faiss", "_meta.pkl"))

        # 删除磁盘文件
        for fp in faiss_files:
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except OSError:
                pass

        # SQLite 级联删除 (doc → chapter → chunk/image/table)
        c.execute("DELETE FROM doc_index WHERE id = ?", (doc_pk,))
        conn.commit()
        conn.close()

        # 重建 doc_names 层
        self._rebuild_doc_names()
        return True

    def _rebuild_doc_names(self):
        """从 SQLite 中重新构建 doc_names.faiss."""
        conn = self._ensure_db()
        c = conn.cursor()
        c.execute("SELECT doc_name, id, bridge_type, doc_uuid FROM doc_index ORDER BY id")
        rows = c.fetchall()
        conn.close()

        faiss_path = os.path.join(self.faiss_dir, "doc_names.faiss")
        meta_path = os.path.join(self.faiss_dir, "doc_names_meta.pkl")

        if not rows:
            for p in [faiss_path, meta_path]:
                if os.path.exists(p):
                    os.remove(p)
            return

        names = [r[0] for r in rows]
        self._save_faiss(self._encode(names), faiss_path)
        meta_list = [
            {"doc_id": r[1], "doc_name": r[0], "bridge_type": r[2], "doc_uuid": r[3]}
            for r in rows
        ]
        with open(meta_path, "wb") as f:
            pickle.dump(meta_list, f)

    # ---- 幂等增量索引 ----
    def index_document(self, doc_id: str) -> bool:
        """从 store.json 中读取指定文档并幂等入库 (已存在则先删再建)."""
        if not os.path.exists(self.store_json_path):
            print(f"[索引] store.json 不存在: {self.store_json_path}")
            return False

        with open(self.store_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        documents = data.get("documents", {})
        parsed = data.get("parsed", {})

        if doc_id not in documents:
            print(f"[索引] 文档 {doc_id} 不在 store.json 中")
            return False

        doc_info = documents[doc_id]
        sections_data = parsed.get(doc_id, {}).get("sections", [])
        if not sections_data:
            print(f"[索引] 文档 {doc_id} 无解析结果, 跳过")
            return False

        doc_name = doc_info.get("doc_title", doc_id)
        bridge_type = _guess_bridge_type(doc_name)

        # 幂等: 如已存在则先删
        self.delete_by_uuid(doc_id)

        seq = self._next_doc_seq()
        print(f"[索引] 开始入库: {doc_name} (uuid={doc_id[:8]}..., seq={seq:04d}, {len(sections_data)} 章)")

        conn = self._ensure_db()
        t0 = time.time()

        valid = [s for s in sections_data if s.get("text", "").strip()]
        if not valid:
            print(f"[索引] 无有效章节内容, 跳过")
            conn.close()
            return False

        chapter_faiss = os.path.join(self.faiss_dir, f"chapters_{seq:04d}.faiss")
        assets_faiss = os.path.join(self.faiss_dir, f"assets_{seq:04d}.faiss")

        c = conn.cursor()
        c.execute(
            "INSERT INTO doc_index (doc_uuid, bridge_type, doc_name, total_chapters, chapter_faiss_path, assets_faiss_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, bridge_type, doc_name, len(valid), chapter_faiss, assets_faiss),
        )
        conn.commit()
        real_doc_id = c.lastrowid

        # 第2层: 章节标题索引
        titles = [s.get("title", "").strip() for s in valid]
        self._save_faiss(self._encode(titles), chapter_faiss)

        chapter_meta = []
        asset_captions: list[str] = []
        asset_meta: list[dict] = []

        for ch_idx, section in enumerate(valid, 1):
            title = section.get("title", "").strip()
            text = section.get("text", "").strip()
            chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)] if text else [""]

            section_faiss = os.path.join(self.faiss_dir, f"section_{seq:04d}_{ch_idx:04d}.faiss")
            section_meta_path = section_faiss.replace(".faiss", "_meta.pkl")

            self._save_faiss(self._encode(chunks), section_faiss)
            section_meta_list = [
                {"chunk_idx": ci, "chunk_text": chunk, "full_text": text, "title": title}
                for ci, chunk in enumerate(chunks)
            ]
            with open(section_meta_path, "wb") as f:
                pickle.dump(section_meta_list, f)

            c.execute(
                "INSERT INTO chapter_index (doc_id, chapter_title, chapter_level, section_faiss_path, total_chunks) "
                "VALUES (?, ?, ?, ?, ?)",
                (real_doc_id, title, section.get("level", 0), section_faiss, len(chunks)),
            )
            real_chapter_id = c.lastrowid

            for ci, chunk in enumerate(chunks):
                c.execute(
                    "INSERT INTO chunk_index (chapter_id, chunk_text, chunk_idx) VALUES (?, ?, ?)",
                    (real_chapter_id, chunk, ci),
                )

            for img in section.get("images", []):
                caption = img.get("caption", "").strip()
                local_path = img.get("local_path", "")
                original_name = img.get("original_name", "")
                c.execute(
                    "INSERT INTO image_index (chapter_id, caption, local_path, original_name) "
                    "VALUES (?, ?, ?, ?)",
                    (real_chapter_id, caption, local_path, original_name),
                )
                if caption:
                    asset_captions.append(caption)
                    asset_meta.append({
                        "type": "image", "chapter_id": real_chapter_id,
                        "chapter_title": title, "caption": caption,
                        "local_path": local_path, "original_name": original_name,
                    })

            for tbl in section.get("tables", []):
                caption = tbl.get("caption", "").strip()
                page_images = tbl.get("page_images", [])
                json_path = tbl.get("json_path", "")
                tbl_data = tbl.get("data", [])
                parse_success = 1 if tbl.get("parse_success", False) else 0
                data_json = json.dumps(tbl_data, ensure_ascii=False) if tbl_data else ""
                page_images_json = json.dumps(page_images, ensure_ascii=False)

                c.execute(
                    "INSERT INTO table_index (chapter_id, caption, page_images, json_path, data, parse_success) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (real_chapter_id, caption, page_images_json, json_path, data_json, parse_success),
                )
                if caption:
                    asset_captions.append(caption)
                    asset_meta.append({
                        "type": "table", "chapter_id": real_chapter_id,
                        "chapter_title": title, "caption": caption,
                        "page_images": page_images, "json_path": json_path,
                        "data": tbl_data, "parse_success": parse_success,
                    })

            chapter_meta.append({
                "chapter_id": real_chapter_id, "chapter_title": title,
                "section_faiss_path": section_faiss, "total_chunks": len(chunks),
            })

        conn.commit()

        chapter_meta_path = chapter_faiss.replace(".faiss", "_meta.pkl")
        with open(chapter_meta_path, "wb") as f:
            pickle.dump(chapter_meta, f)

        if asset_captions:
            self._save_faiss(self._encode(asset_captions), assets_faiss)
            assets_meta_path = assets_faiss.replace(".faiss", "_meta.pkl")
            with open(assets_meta_path, "wb") as f:
                pickle.dump(asset_meta, f)

        conn.close()

        # 重建共享的 doc_names 层 (增量成本低)
        self._rebuild_doc_names()

        print(f"[索引] {doc_name} 入库完成, 耗时 {time.time() - t0:.1f}s")
        return True

    # ---- 索引状态 ----
    def get_status(self) -> dict:
        """返回索引入库概览."""
        if not os.path.exists(self.db_path):
            return {"documents": 0, "chapters": 0, "chunks": 0, "images": 0, "tables": 0,
                    "faiss_disk_mb": 0, "doc_list": []}

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        n_docs = c.execute("SELECT COUNT(*) FROM doc_index").fetchone()[0]
        n_chapters = c.execute("SELECT COUNT(*) FROM chapter_index").fetchone()[0]
        n_chunks = c.execute("SELECT COUNT(*) FROM chunk_index").fetchone()[0]
        n_images = c.execute("SELECT COUNT(*) FROM image_index").fetchone()[0]
        n_tables = c.execute("SELECT COUNT(*) FROM table_index").fetchone()[0]

        docs = c.execute(
            "SELECT doc_uuid, doc_name, bridge_type, total_chapters, created_at FROM doc_index ORDER BY id"
        ).fetchall()

        conn.close()

        faiss_mb = 0
        if os.path.exists(self.faiss_dir):
            for f in os.listdir(self.faiss_dir):
                fp = os.path.join(self.faiss_dir, f)
                if os.path.isfile(fp):
                    faiss_mb += os.path.getsize(fp) / (1024 * 1024)

        return {
            "documents": n_docs,
            "chapters": n_chapters,
            "chunks": n_chunks,
            "images": n_images,
            "tables": n_tables,
            "faiss_disk_mb": round(faiss_mb, 2),
            "doc_list": [
                {"doc_uuid": r[0], "doc_name": r[1], "bridge_type": r[2],
                 "chapters": r[3], "created_at": r[4]}
                for r in docs
            ],
        }

    # ---- 全量重建 ----
    def rebuild_all(self) -> int:
        """从 store.json 全量重建所有索引, 返回已索引文档数."""
        if not os.path.exists(self.store_json_path):
            print(f"[索引] store.json 不存在, 跳过")
            return 0

        with open(self.store_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        documents = data.get("documents", {})
        parsed = data.get("parsed", {})

        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.faiss_dir):
            shutil.rmtree(self.faiss_dir)
        os.makedirs(self.faiss_dir, exist_ok=True)

        indexed = 0
        for doc_id in documents:
            if doc_id in parsed:
                try:
                    if self.index_document(doc_id):
                        indexed += 1
                except Exception as e:
                    print(f"[索引] 文档 {doc_id} 入库失败: {e}")

        print(f"[索引] 全量重建完成: {indexed} 篇文档")
        return indexed
