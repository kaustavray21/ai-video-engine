"""
VectorStore manager — load, query, and test FAISS vectorstores.

Extracted from: api/live_video_services.py (LiveVideoQuestionService, lines 14-300)
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    success: bool
    answer: str = ''
    source_chunks: int = 0
    error: str = ''


QA_PROMPT = PromptTemplate(
    template="""You are an AI tutor helping students understand content from a video lecture.

Course: {course_title}
Video: {video_title}

Use the following context from the video transcript to answer the question.
If you don't know the answer based on the provided context, say that you don't have
enough information from the video to answer. Don't make up information.

Context from video:
{context}

Question: {question}

Helpful Answer (be concise and clear):""",
    input_variables=['context', 'question', 'course_title', 'video_title'],
)


class VectorStoreManager:
    """Load, query, and test FAISS vectorstores."""

    def __init__(self, openai_api_key: str):
        self.embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
        self.llm = ChatOpenAI(
            model_name='gpt-4o-mini',
            temperature=0.3,
            max_tokens=1000,
            openai_api_key=openai_api_key,
        )

    def load(self, path: str) -> Optional[FAISS]:
        """Load a FAISS index from disk."""
        if not os.path.exists(path):
            logger.error(f'Vectorstore path does not exist: {path}')
            return None
        try:
            vs = FAISS.load_local(
                path, self.embeddings,
                allow_dangerous_deserialization=True,
            )
            logger.info(f'Vectorstore loaded: {path}')
            return vs
        except Exception as e:
            logger.exception(f'Failed to load vectorstore: {e}')
            return None

    def query(
        self,
        vectorstore_path: str,
        question: str,
        course_title: str = 'Course',
        video_title: str = 'Video',
        k: int = 5,
    ) -> QueryResult:
        """
        Retrieve relevant chunks and generate an answer with GPT-4o-mini.

        Args:
            vectorstore_path: Absolute path to the FAISS index directory.
            question: User's question.
            course_title: Course name for prompt context.
            video_title: Video name for prompt context.
            k: Number of chunks to retrieve.

        Returns:
            QueryResult with the generated answer.
        """
        vectorstore = self.load(vectorstore_path)
        if vectorstore is None:
            return QueryResult(
                success=False,
                error=f'Vectorstore not found at: {vectorstore_path}',
            )

        try:
            # Retrieve relevant chunks
            docs = vectorstore.similarity_search(question, k=k)
            if not docs:
                return QueryResult(
                    success=False,
                    error='No relevant chunks found in vectorstore',
                )

            context = '\n\n'.join(doc.page_content for doc in docs)

            # Generate answer
            prompt_text = QA_PROMPT.format(
                context=context,
                question=question,
                course_title=course_title,
                video_title=video_title,
            )
            response = self.llm.invoke(prompt_text)
            answer = response.content

            logger.info(
                f'Answer generated using {len(docs)} chunks '
                f'({len(answer)} chars)'
            )

            return QueryResult(
                success=True,
                answer=answer,
                source_chunks=len(docs),
            )

        except Exception as e:
            logger.exception(f'Query failed: {e}')
            return QueryResult(success=False, error=str(e))

    def test(self, path: str, test_query: str = 'What is this video about?') -> Dict[str, Any]:
        """Quick smoke-test for a vectorstore."""
        vs = self.load(path)
        if vs is None:
            return {'status': 'error', 'message': 'Failed to load vectorstore'}

        try:
            docs = vs.similarity_search(test_query, k=3)
            if not docs:
                return {'status': 'warning', 'message': 'Loaded but no documents found'}

            return {
                'status': 'ok',
                'document_count': len(docs),
                'avg_chunk_length': int(
                    sum(len(d.page_content) for d in docs) / len(docs)
                ),
                'sample': docs[0].page_content[:200],
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
