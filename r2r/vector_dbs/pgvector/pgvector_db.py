import json
import logging
import os
import uuid
from typing import Optional, Union

from sqlalchemy import text

from r2r.core import (
    DocumentInfo,
    SearchResult,
    UserStats,
    VectorDBConfig,
    VectorDBProvider,
    VectorEntry,
)
from r2r.vecs.client import Client
from r2r.vecs.collection import Collection

logger = logging.getLogger(__name__)


class PGVectorDB(VectorDBProvider):
    def __init__(self, config: VectorDBConfig) -> None:
        super().__init__(config)
        try:
            import r2r.vecs
        except ImportError:
            raise ValueError(
                f"Error, PGVectorDB requires the vecs library. Please run `poetry add vecs`."
            )
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        host = os.getenv("POSTGRES_HOST")
        port = os.getenv("POSTGRES_PORT")
        db_name = os.getenv("POSTGRES_DBNAME")
        if not all([user, password, host, port, db_name]):
            raise ValueError(
                "Error, please set the POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, and POSTGRES_DBNAME environment variables."
            )
        try:
            DB_CONNECTION = (
                f"postgresql://{user}:{password}@{host}:{port}/{db_name}"
            )
            self.vx: Client = r2r.vecs.create_client(DB_CONNECTION)
        except Exception as e:
            raise ValueError(
                f"Error {e} occurred while attempting to connect to the pgvector provider with {DB_CONNECTION}."
            )
        self.collection: Optional[Collection] = None
        self.config: VectorDBConfig = config

    def initialize_collection(self, dimension: int) -> None:
        self.collection = self.vx.get_or_create_collection(
            name=self.config.collection_name, dimension=dimension
        )
        self._create_document_info_table()

    def _create_document_info_table(self):
        with self.vx.Session() as sess:
            with sess.begin():
                query = f"""
                CREATE TABLE IF NOT EXISTS document_info_{self.config.collection_name} (
                    document_id UUID PRIMARY KEY,
                    title TEXT,
                    user_id UUID,
                    version TEXT,
                    size_in_bytes INT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    metadata JSONB
                );
                """
                sess.execute(text(query))
                sess.commit()

    def copy(self, entry: VectorEntry, commit=True) -> None:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `copy`."
            )

        serializeable_entry = entry.to_serializable()

        self.collection.copy(
            records=[
                (
                    serializeable_entry["id"],
                    serializeable_entry["vector"],
                    serializeable_entry["metadata"],
                )
            ]
        )

    def copy_entries(
        self, entries: list[VectorEntry], commit: bool = True
    ) -> None:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `copy_entries`."
            )

        self.collection.copy(
            records=[
                (
                    str(entry.id),
                    entry.vector.data,
                    entry.to_serializable()["metadata"],
                )
                for entry in entries
            ]
        )

    def upsert(self, entry: VectorEntry, commit=True) -> None:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `upsert`."
            )

        self.collection.upsert(
            records=[
                (
                    str(entry.id),
                    entry.vector.data,
                    entry.to_serializable()["metadata"],
                )
            ]
        )

    def upsert_entries(
        self, entries: list[VectorEntry], commit: bool = True
    ) -> None:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `upsert_entries`."
            )

        self.collection.upsert(
            records=[
                (
                    str(entry.id),
                    entry.vector.data,
                    entry.to_serializable()["metadata"],
                )
                for entry in entries
            ]
        )

    def search(
        self,
        query_vector: list[float],
        filters: dict[str, Union[bool, int, str]] = {},
        limit: int = 10,
        *args,
        **kwargs,
    ) -> list[SearchResult]:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `search`."
            )
        measure = kwargs.get("measure", "cosine_distance")
        mapped_filters = {
            key: {"$eq": value} for key, value in filters.items()
        }

        return [
            SearchResult(id=ele[0], score=float(1 - ele[1]), metadata=ele[2])  # type: ignore
            for ele in self.collection.query(
                data=query_vector,
                limit=limit,
                filters=mapped_filters,
                measure=measure,
                include_value=True,
                include_metadata=True,
            )
        ]

    def create_index(self, index_type, column_name, index_options):
        pass

    def delete_by_metadata(
        self, metadata_fields: str, metadata_values: Union[bool, int, str]
    ) -> list[str]:
        super().delete_by_metadata(metadata_fields, metadata_values)
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `delete_by_metadata`."
            )
        return self.collection.delete(
            filters={
                k: {"$eq": v} for k, v in zip(metadata_fields, metadata_values)
            }
        )

    def get_metadatas(
        self,
        metadata_fields: list[str],
        filter_field: Optional[str] = None,
        filter_value: Optional[Union[bool, int, str]] = None,
    ) -> list[dict]:
        if self.collection is None:
            raise ValueError(
                "Please call `initialize_collection` before attempting to run `get_metadatas`."
            )

        results = {tuple(metadata_fields): {}}
        for field in metadata_fields:
            unique_values = self.collection.get_unique_metadata_values(
                field=field,
                filter_field=filter_field,
                filter_value=filter_value,
            )
            for value in unique_values:
                if value not in results:
                    results[value] = {}
                results[value][field] = value

        return [
            results[key] for key in results if key != tuple(metadata_fields)
        ]

    def upsert_documents_info(
        self, documents_info: list[DocumentInfo]
    ) -> None:
        for document_info in documents_info:
            db_entry = document_info.convert_to_db_entry()
            query = text(
                f"""
                INSERT INTO document_info_{self.config.collection_name} (document_id, title, user_id, version, created_at, updated_at, size_in_bytes, metadata)
                VALUES (:document_id, :title, :user_id, :version, :created_at, :updated_at, :size_in_bytes, :metadata)
                ON CONFLICT (document_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    user_id = EXCLUDED.user_id,
                    version = EXCLUDED.version,
                    updated_at = EXCLUDED.updated_at,
                    size_in_bytes = EXCLUDED.size_in_bytes,
                    metadata = EXCLUDED.metadata;
            """
            )
        with self.vx.Session() as sess:
            sess.execute(query, db_entry)
            sess.commit()

    def delete_documents_info(self, document_ids: list[str]) -> None:
        placeholders = ", ".join(
            f":doc_id_{i}" for i in range(len(document_ids))
        )
        query = text(
            f"""
            DELETE FROM document_info_{self.config.collection_name} WHERE document_id IN ({placeholders});
            """
        )
        params = {
            f"doc_id_{i}": document_id
            for i, document_id in enumerate(document_ids)
        }

        with self.vx.Session() as sess:
            with sess.begin():
                sess.execute(query, params)
            sess.commit()

    def get_documents_info(
        self,
        filter_document_ids: Optional[list[str]] = None,
        filter_user_ids: Optional[list[str]] = None,
    ):
        conditions = []
        params = {}

        if filter_document_ids:
            placeholders = ", ".join(
                f":doc_id_{i}" for i in range(len(filter_document_ids))
            )
            conditions.append(f"document_id IN ({placeholders})")
            params.update(
                {
                    f"doc_id_{i}": str(document_id)
                    for i, document_id in enumerate(filter_document_ids)
                }
            )
        if filter_user_ids:
            placeholders = ", ".join(
                f":user_id_{i}" for i in range(len(filter_user_ids))
            )
            conditions.append(f"user_id IN ({placeholders})")
            params.update(
                {
                    f"user_id_{i}": str(user_id)
                    for i, user_id in enumerate(filter_user_ids)
                }
            )

        query = f"""
            SELECT document_id, title, user_id, version, size_in_bytes, created_at, updated_at, metadata
            FROM document_info_{self.config.collection_name}
        """
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        with self.vx.Session() as sess:
            results = sess.execute(text(query), params).fetchall()
            return [
                DocumentInfo(
                    document_id=row[0],
                    title=row[1],
                    user_id=row[2],
                    version=row[3],
                    size_in_bytes=row[4],
                    created_at=row[5],
                    updated_at=row[6],
                    metadata=row[7],
                )
                for row in results
            ]

    def get_document_chunks(self, document_id: str) -> list[dict]:
        if not self.collection:
            raise ValueError("Collection is not initialized.")

        table_name = self.collection.table.name
        query = text(
            f"""
            SELECT metadata
            FROM vecs."{table_name}"
            WHERE metadata->>'document_id' = :document_id
            ORDER BY CAST(metadata->>'chunk_order' AS INTEGER)
        """
        )

        params = {"document_id": document_id}

        with self.vx.Session() as sess:
            results = sess.execute(query, params).fetchall()
            return [result[0] for result in results]

    def get_users_stats(self, user_ids: Optional[list[str]] = None):
        user_ids_condition = ""
        params = {}
        if user_ids:
            user_ids_condition = "WHERE user_id IN :user_ids"
            params["user_ids"] = tuple(
                map(str, user_ids)
            )  # Convert UUIDs to strings

        query = f"""
            SELECT user_id, COUNT(document_id) AS num_files, SUM(size_in_bytes) AS total_size_in_bytes, ARRAY_AGG(document_id) AS document_ids
            FROM document_info_{self.config.collection_name}
            {user_ids_condition}
            GROUP BY user_id
        """

        with self.vx.Session() as sess:
            results = sess.execute(text(query), params).fetchall()

        return [
            UserStats(
                user_id=row[0],
                num_files=row[1],
                total_size_in_bytes=row[2],
                document_ids=[uuid.UUID(doc_id) for doc_id in row[3]],
            )
            for row in results
        ]
