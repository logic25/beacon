"""
Vector store integration using Pinecone.
Handles document embedding, storage, and retrieval.
"""

import logging
from typing import Optional

from pinecone import Pinecone, ServerlessSpec

from config import Settings, get_settings
from document_processor import DocumentChunk

logger = logging.getLogger(__name__)


class VectorStoreError(Exception):
    """Custom exception for vector store errors."""
    pass


class VectorStore:
    """Pinecone vector store for document retrieval."""

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the vector store.

        Args:
            settings: Application settings
        """
        self.settings = settings or get_settings()

        # Initialize Pinecone
        self.pc = Pinecone(api_key=self.settings.pinecone_api_key)

        # Get or create index
        self.index_name = self.settings.pinecone_index_name
        self._ensure_index_exists()
        self.index = self.pc.Index(self.index_name)

        # Initialize embedding client
        self._init_embeddings()

    def _ensure_index_exists(self) -> None:
        """Create the index if it doesn't exist."""
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.settings.embedding_dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1",
                ),
            )
            logger.info(f"Index {self.index_name} created")

    def _init_embeddings(self) -> None:
        """Initialize the embedding client based on settings."""
        provider = self.settings.embedding_provider.lower()

        if provider == "voyage":
            try:
                import voyageai
                self.voyage_client = voyageai.Client(
                    api_key=self.settings.voyage_api_key
                )
                self._embed_func = self._embed_voyage
                logger.info("Using Voyage AI for embeddings")
            except ImportError:
                raise ImportError(
                    "voyageai is required for Voyage embeddings. "
                    "Install with: pip install voyageai"
                )
        elif provider == "openai":
            try:
                import openai
                self.openai_client = openai.OpenAI(
                    api_key=self.settings.openai_api_key
                )
                self._embed_func = self._embed_openai
                logger.info("Using OpenAI for embeddings")
            except ImportError:
                raise ImportError(
                    "openai is required for OpenAI embeddings. "
                    "Install with: pip install openai"
                )
        else:
            raise ValueError(f"Unknown embedding provider: {provider}")

    def _embed_voyage(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings using Voyage AI."""
        result = self.voyage_client.embed(
            texts,
            model=self.settings.voyage_model,
            input_type="document",
        )
        return result.embeddings

    def _embed_voyage_query(self, text: str) -> list[float]:
        """Get query embedding using Voyage AI."""
        result = self.voyage_client.embed(
            [text],
            model=self.settings.voyage_model,
            input_type="query",
        )
        return result.embeddings[0]

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings using OpenAI."""
        response = self.openai_client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _embed_openai_query(self, text: str) -> list[float]:
        """Get query embedding using OpenAI."""
        response = self.openai_client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=[text],
        )
        return response.data[0].embedding

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple document texts.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors
        """
        # Process in batches to avoid API limits
        batch_size = 32
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = self._embed_func(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a query text.

        Args:
            text: Query text to embed

        Returns:
            Embedding vector
        """
        provider = self.settings.embedding_provider.lower()
        if provider == "voyage":
            return self._embed_voyage_query(text)
        else:
            return self._embed_openai_query(text)

    def _clean_metadata(self, metadata: dict) -> dict:
        """Remove None values from metadata - Pinecone rejects nulls."""
        cleaned = {}
        for k, v in metadata.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                cleaned[k] = v
            elif isinstance(v, list):
                # Pinecone accepts lists of strings
                cleaned[k] = [str(item) for item in v]
            else:
                cleaned[k] = str(v)
        return cleaned

    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Insert or update document chunks in the vector store.

        Args:
            chunks: List of DocumentChunk objects to upsert

        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        # Get embeddings for all chunks
        texts = [chunk.text for chunk in chunks]
        embeddings = self.embed_documents(texts)

        # Prepare vectors for Pinecone
        vectors = []
        for chunk, embedding in zip(chunks, embeddings):
            # Build metadata dict, excluding None values
            meta = {
                "text": chunk.text[:1000],  # Pinecone metadata limit
                "source_file": chunk.source_file,
                "source_type": chunk.source_type,
                "chunk_index": chunk.chunk_index,
            }

            # Only add page_number if it has a value
            if chunk.page_number is not None:
                meta["page_number"] = chunk.page_number

            # Add extra metadata, filtering out None values
            for k, v in chunk.metadata.items():
                if v is not None and v != "":
                    meta[k] = str(v)

            vectors.append({
                "id": chunk.chunk_id,
                "values": embedding,
                "metadata": self._clean_metadata(meta),
            })

        # Upsert in batches
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            self.index.upsert(vectors=batch)

        logger.info(f"Upserted {len(vectors)} chunks to Pinecone")
        return len(vectors)

    def search(
        self,
        query: str,
        top_k: int = 5,
        source_type_filter: Optional[str] = None,
    ) -> list[dict]:
        """Search for relevant documents.

        Args:
            query: Search query text
            top_k: Number of results to return
            source_type_filter: Optional filter by source type

        Returns:
            List of search results with metadata
        """
        # Embed the query
        query_embedding = self.embed_query(query)

        # Build filter if specified
        filter_dict = None
        if source_type_filter:
            filter_dict = {"source_type": {"$eq": source_type_filter}}

        # Query Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            filter=filter_dict,
        )

        # Format results
        formatted_results = []
        for match in results.matches:
            formatted_results.append({
                "chunk_id": match.id,
                "score": match.score,
                "text": match.metadata.get("text", ""),
                "source_file": match.metadata.get("source_file", "Unknown"),
                "source_type": match.metadata.get("source_type", "document"),
                "page_number": match.metadata.get("page_number"),
                "metadata": match.metadata,
            })

        return formatted_results

    def delete_by_source(self, source_file: str) -> None:
        """Delete all chunks from a specific source file.

        Args:
            source_file: Name of the source file to delete
        """
        # Note: Pinecone serverless doesn't support delete by metadata filter
        # You'd need to track IDs separately or use a different approach
        logger.warning(
            f"Delete by source not fully supported in serverless. "
            f"Consider recreating the index to remove {source_file}"
        )

    def get_stats(self) -> dict:
        """Get index statistics.

        Returns:
            Dictionary with index stats
        """
        stats = self.index.describe_index_stats()
        return {
            "total_vectors": stats.total_vector_count,
            "dimension": stats.dimension,
        }
