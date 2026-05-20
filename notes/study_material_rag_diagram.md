# Study Material RAG Architecture

This document diagrams the Retrieval-Augmented Generation (RAG) data flow for both whole Study Materials and individual Study Material Files.

## RAG Flow Diagram

```mermaid
graph TD
    %% Define styles
    classDef client fill:#3b82f6,stroke:#1e3a8a,stroke-width:2px,color:#fff
    classDef api fill:#10b981,stroke:#047857,stroke-width:2px,color:#fff
    classDef vsManager fill:#f59e0b,stroke:#b45309,stroke-width:2px,color:#fff
    classDef search fill:#8b5cf6,stroke:#4c1d95,stroke-width:2px,color:#fff
    classDef data fill:#64748b,stroke:#334155,stroke-width:2px,color:#fff
    classDef llm fill:#ec4899,stroke:#be185d,stroke-width:2px,color:#fff

    Client[Client Application]:::client

    %% Endpoints
    SM_API[POST /api/study-materials/&lt;id&gt;/query/]:::api
    File_API[POST /api/study-materials/files/&lt;id&gt;/query/]:::api

    Client -->|Full Material Query| SM_API
    Client -->|Single File Query| File_API

    %% Vectorstores
    MergedVS[(Merged Vectorstore<br>FAISS + BM25)]:::data
    SingleVS[(Single File Vectorstore<br>FAISS + BM25)]:::data

    SM_API -->|Points to| MergedVS
    File_API -->|Points to| SingleVS

    %% VectorStoreManager Pipeline
    subgraph VectorStoreManager [VectorStoreManager Query Pipeline]
        Router[Query Router & Rewriter<br>Extract metadata filters]:::vsManager
        
        subgraph Retrieval [Retrieval Phase]
            Dense[Dense FAISS Retrieval<br>Cosine Similarity]:::search
            Sparse[Sparse BM25 Retrieval<br>Keyword Match]:::search
        end
        
        RRF[Reciprocal Rank Fusion<br>Merge Dense & Sparse]:::vsManager
        
        FilterCap[Per-File Capping<br>Max Dense/BM25 chunks per file]:::vsManager
        
        Overview[Overview Strategy<br>Guarantee 1 chunk per file<br>for topic queries]:::vsManager
        
        Reorder[Context Reordering<br>Push high BM25 scores to top]:::vsManager
        
        ParentChild[Parent-Child Expansion<br>Fetch larger parent chunks]:::vsManager
        
        PromptBuild[Context Assembly<br>Add file metadata/annotations]:::vsManager
    end

    MergedVS --> Router
    SingleVS --> Router

    Router --> Dense
    Router --> Sparse

    Dense --> FilterCap
    Sparse --> FilterCap

    FilterCap --> RRF
    RRF --> Overview
    Overview --> Reorder
    Reorder --> ParentChild
    ParentChild --> PromptBuild

    %% LLM Generation
    LLM_API[OpenAI GPT-4o-mini<br>Generate Answer]:::llm
    PromptBuild --> LLM_API

    %% Response
    Response[JSON Response<br>Answer + Source Annotations]:::client
    LLM_API --> Response
```

## Key Differences

1. **Target Vectorstore**:
   - The **Whole Study Material** endpoint queries the merged vectorstore located at `sm.vectorstore_location` which contains embeddings from all files in the zip.
   - The **Single File** endpoint queries the specific file's vectorstore located at `smf.vectorstore_path`, completely isolating its results from the rest of the material.
   
2. **Overview Strategy Impact**:
   - During a whole study material query, if the user asks an "overview" question (e.g. "what topics are covered?"), the `VectorStoreManager` will boost `k` and inject a guaranteed 1 chunk from each small file to ensure all topics are represented.
   - For a single file query, this overview logic is still executed but applies only to the chunks within that single file, naturally resulting in broad coverage of that specific document.

3. **Context Length Constraints**:
   - The whole study material query actively utilizes the `MAX_DENSE_PER_FILE` and `MAX_BM25_PER_FILE` caps (currently 2 chunks per file) to prevent a single large document (like a massive CSV) from starving smaller documents in the RAG context.
   - The single file query hits these same caps, but since only one file is present in the vectorstore, the total context returned to the LLM is more focused on deep extraction from that single document.
