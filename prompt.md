
# Study Material Pipeline

## 1. Data Model: StudyMaterial
Fields:
- id (auto-generated)
- name (string, unique)
- description (text)
- file_path (str) — uploaded text location
- status (enum: pending | processing | completed | failed)
- files_count (int)
- vectorstore_location (str)
- created_at (datetime)
- attached_to_courses (list[Course.id]) — courses this material is merged into

## 2. Upload & Process Pipeline

### POST /api/study-materials/upload/
Input: multipart/form-data { name, description, zip_file }
Steps:
  1. Save zip -> media/study_materials/{name}/
  2. Set status = processing
  3. Unzip all files
  4. Build metadata list for each file (original_name, type, size)
  5. Convert each file -> text -> media/study_materials/{name}/text/{file_name}.txt
     Support: .pdf .doc .docx .txt .md .rtf .ppt .pptx .odp .xls .xlsx .csv .ods
              .py .js .ts .html .css .java .go .rs .cpp .h .json .yaml .yml .xml
  6. Build FAISS vectorstore -> study_materials_vectorstore/{name}.vectorstore/index.faiss
  7. Save index.pkl with metadata (chunks, embeddings, file_metadata: original_name, type, size, chunk_index)
  8. Set status = completed, files_count, vectorstore_location
  9. Delete original zip + extracted files (keep text/ folder)

### GET /api/study-materials/{id}/status/
Returns: { id, name, status, files_count, vectorstore_location, created_at, attached_to_courses }

## 3. Merge API

### POST /api/study-materials/{id}/merge-to-course/{course_id}/
- If course's study_material field is null: merge vectorstore, set study_material = {id, name, description}
- If same study_material already attached: return { message: "Already added" }
- If different study_material attached: overwrite with new one (merge new vectorstore), return { study_material: { id, name, description }, replaced: { id, name, description } }
- Update course details to show attached study material info

## 4. Query API

### POST /api/study-materials/{id}/query/
Input: { question }
Steps:
  1. Load vectorstore from vectorstore_location
  2. Perform similarity search for the question
  3. Generate answer using RAG (LLM + retrieved chunks)
  4. Return: { answer, sources: [ { file_name, chunk_index, text } ] }

### POST /api/courses/{id}/query/ (Updated)
Input: { question, include_study_materials: bool (default: true) }
Steps:
  1. Use course-level vectorstore (which now contains merged study material if attached)
  2. Return answer incorporating both video transcripts and study materials

## 5. Study Materials List

### GET /api/study-materials/
Returns all study materials with count of courses each is attached to.

## 6. Course Model Update
Add to Course model:
- study_material: { id, name, description } | null
- study_materials_history: list (optional, for tracking overwrites)
