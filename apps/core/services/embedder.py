"""
Embedder service — text chunking + FAISS vectorstore creation.

Extracted from: api/live_video_processor.py (_create_vector_store)
               yt_transcribe/src/llm_context_helper.py (get_vector_store_transcript_v2)
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

logger = logging.getLogger(__name__)


@dataclass
class EmbedResult:
    success: bool
    vectorstore_path: str = ''
    chunk_count: int = 0
    error: str = ''


class Embedder:
    """
    Chunk transcript text and create a FAISS vectorstore using OpenAI embeddings.
    """

    def __init__(
        self,
        openai_api_key: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        self.embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=['\n\n', '\n', '. ', ' ', ''],
        )

    def create_vectorstore(
        self,
        transcript_text: str,
        save_path: str,
        metadata: Optional[dict] = None,
    ) -> EmbedResult:
        """
        Chunk the transcript, embed with OpenAI, and save as a FAISS index.

        Args:
            transcript_text: Full transcript text.
            save_path: Absolute directory path to save the FAISS index.
            metadata: Optional metadata to attach to each chunk document.

        Returns:
            EmbedResult with the saved path and chunk count.
        """
        if not transcript_text or not transcript_text.strip():
            return EmbedResult(success=False, error='Empty transcript text')

        try:
            # 1. Chunk
            chunks = self.text_splitter.split_text(transcript_text)
            if not chunks:
                return EmbedResult(success=False, error='Text splitter produced no chunks')

            logger.info(f'Split transcript into {len(chunks)} chunks')

            # 2. Attach metadata to each chunk
            metadatas = None
            if metadata:
                metadatas = [metadata.copy() for _ in chunks]

            # 3. Create FAISS vectorstore
            logger.info('Creating FAISS vectorstore from chunks...')
            vectorstore = FAISS.from_texts(
                texts=chunks,
                embedding=self.embeddings,
                metadatas=metadatas,
            )

            # 4. Save to disk
            os.makedirs(save_path, exist_ok=True)
            vectorstore.save_local(save_path)
            logger.info(f'Vectorstore saved: {save_path} ({len(chunks)} chunks)')

            return EmbedResult(
                success=True,
                vectorstore_path=save_path,
                chunk_count=len(chunks),
            )

        except Exception as e:
            logger.exception(f'Vectorstore creation failed: {e}')
            return EmbedResult(success=False, error=str(e))
