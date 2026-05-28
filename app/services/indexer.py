from __future__ import annotations

import json
import os
import pickle
import sqlite3
import time
from typing import Optional

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
    """四层 FAISS 向量索引 + SQLite 元数据库, 支持增量入库."""

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

    # ---- 数据库初始化 (不删已有数据) ----
    def _ensure_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS doc_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bridge_type TEXT NOT NULL,
            doc_name TEXT NOT NULL,
            total_chapters INTEGER DEFAULT 0,
            chapter_faiss_path TEXT NOT NULL,
            assets_faiss_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chapter_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            chapter_title TEXT NOT NULL,
            chapter_level INTEGER DEFAULT 0,
            section_faiss_path TEXT NOT NULL,
            total_chunks INTEGER DEFAULT 0,
            FOREIGN KEY (doc_id) REFERENCES doc_index(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS chunk_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_idx INTEGER DEFAULT 0,
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS image_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            caption TEXT NOT NULL,
            local_path TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS table_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL,
            caption TEXT NOT NULL,
            page_images TEXT DEFAULT '[]',
            json_path TEXT DEFAULT '',
            data TEXT DEFAULT '',
            parse_success INTEGER DEFAULT 0,
            FOREIGN KEY (chapter_id) REFERENCES chapter_index(id)
        )""")
        for idx in ["doc_index(bridge_type)", "chapter_index(doc_id)",
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

    # ---- 获取下一个文件序号 ----
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

    # ---- 增量索引单篇文档 ----
    def index_document(self, doc_id: str) -> bool:
        """从 store.json 中读取指定文档并增量入库. 返回是否成功."""
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
        seq = self._next_doc_seq()

        print(f"[索引] 开始入库: {doc_name} (seq={seq:04d}, {len(sections_data)} 章)")

        conn = self._ensure_db()
        t0 = time.time()

        # 过滤无正文的纯父标题
        valid = [s for s in sections_data if s.get("text", "").strip()]
        if not valid:
            print(f"[索引] 无有效章节内容, 跳过")
            conn.close()
            return False

        chapter_faiss = os.path.join(self.faiss_dir, f"chapters_{seq:04d}.faiss")
        assets_faiss = os.path.join(self.faiss_dir, f"assets_{seq:04d}.faiss")

        c = conn.cursor()
        c.execute(
            "INSERT INTO doc_index (bridge_type, doc_name, total_chapters, chapter_faiss_path, assets_faiss_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (bridge_type, doc_name, len(valid), chapter_faiss, assets_faiss),
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

            # 正文切 chunk
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

            # 图片
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

            # 表格
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

        # 章节 meta
        chapter_meta_path = chapter_faiss.replace(".faiss", "_meta.pkl")
        with open(chapter_meta_path, "wb") as f:
            pickle.dump(chapter_meta, f)

        # 第4层: 图表标题索引
        if asset_captions:
            self._save_faiss(self._encode(asset_captions), assets_faiss)
            assets_meta_path = assets_faiss.replace(".faiss", "_meta.pkl")
            with open(assets_meta_path, "wb") as f:
                pickle.dump(asset_meta, f)

        # ---- 第1层: doc_names 增量更新 ----
        self._upsert_doc_name(doc_name, real_doc_id, bridge_type)

        conn.close()
        print(f"[索引] {doc_name} 入库完成, 耗时 {time.time() - t0:.1f}s")
        return True

    def _upsert_doc_name(self, doc_name: str, doc_id: int, bridge_type: str):
        """增量更新全局文档名 FAISS 索引."""
        import faiss

        faiss_path = os.path.join(self.faiss_dir, "doc_names.faiss")
        meta_path = os.path.join(self.faiss_dir, "doc_names_meta.pkl")

        new_vec = self._encode([doc_name])
        new_meta = {"doc_id": doc_id, "doc_name": doc_name, "bridge_type": bridge_type}

        if os.path.exists(faiss_path) and os.path.exists(meta_path):
            index = faiss.read_index(faiss_path)
            index.add(new_vec)
            faiss.write_index(index, faiss_path)
            with open(meta_path, "rb") as f:
                meta_list = pickle.load(f)
            meta_list.append(new_meta)
            with open(meta_path, "wb") as f:
                pickle.dump(meta_list, f)
        else:
            self._save_faiss(new_vec, faiss_path)
            with open(meta_path, "wb") as f:
                pickle.dump([new_meta], f)

    # ---- 全量重建 (用于初始化或修复) ----
    def rebuild_all(self) -> int:
        """从 store.json 全量重建所有索引, 返回已索引文档数."""
        import shutil

        if not os.path.exists(self.store_json_path):
            print(f"[索引] store.json 不存在, 跳过")
            return 0

        with open(self.store_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        documents = data.get("documents", {})
        parsed = data.get("parsed", {})

        # 清空旧数据
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
