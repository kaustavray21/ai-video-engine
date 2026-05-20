"""
patch_bm25.py — Rebuild BM25 index for existing completed SM merged vectorstores.

Usage:
    python patch_bm25.py              # patch ALL completed SMs
    python patch_bm25.py --id 10      # patch a specific SM by ID

No re-embedding — just reads the FAISS docstore and rebuilds bm25_index.pkl in-place.
"""
import os
import sys
import pickle
import django
import argparse

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from rank_bm25 import BM25Okapi

from apps.core.models.study_material import StudyMaterial


def rebuild_bm25_for_sm(sm):
    vs_rel = sm.vectorstore_location
    if not vs_rel:
        print(f'  [SKIP] SM {sm.id} "{sm.name}" — no vectorstore_location set')
        return False

    vs_abs = os.path.join(str(settings.MEDIA_ROOT), vs_rel)
    index_file = os.path.join(vs_abs, 'index.faiss')
    if not os.path.exists(index_file):
        print(f'  [SKIP] SM {sm.id} "{sm.name}" — index.faiss not found at {vs_abs}')
        return False

    bm25_path = os.path.join(vs_abs, 'bm25_index.pkl')
    print(f'  Loading FAISS for SM {sm.id} "{sm.name}" ...')

    try:
        embeddings = OpenAIEmbeddings(
            openai_api_key=settings.OPENAI_API_KEY,
            model='text-embedding-3-small',
        )
        vs = FAISS.load_local(vs_abs, embeddings, allow_dangerous_deserialization=True)
    except Exception as exc:
        print(f'  [ERROR] Failed to load FAISS: {exc}')
        return False

    all_docs = list(vs.docstore._dict.values())
    if not all_docs:
        print(f'  [SKIP] Docstore is empty')
        return False

    texts = [doc.page_content for doc in all_docs]
    metadatas = [doc.metadata or {} for doc in all_docs]
    tokenized = [t.lower().split() for t in texts]

    # Show file breakdown before writing
    from collections import Counter
    file_counts = Counter(m.get('source_file', 'unknown') for m in metadatas)
    print(f'  Corpus: {len(texts):,} docs across {len(file_counts)} files:')
    for fname, count in sorted(file_counts.items(), key=lambda x: -x[1]):
        print(f'    {fname}: {count} chunks')

    bm25 = BM25Okapi(tokenized)
    with open(bm25_path, 'wb') as f:
        pickle.dump({'bm25': bm25, 'corpus': tokenized, 'metadatas': metadatas}, f)

    size_kb = os.path.getsize(bm25_path) // 1024
    print(f'  [OK] bm25_index.pkl written — {len(texts):,} docs, {size_kb} KB')
    return True


def main():
    parser = argparse.ArgumentParser(description='Patch BM25 for SM vectorstores')
    parser.add_argument('--id', type=int, default=None, help='Specific SM ID to patch')
    args = parser.parse_args()

    if args.id:
        try:
            sms = [StudyMaterial.objects.get(id=args.id)]
        except StudyMaterial.DoesNotExist:
            print(f'SM {args.id} not found')
            sys.exit(1)
    else:
        sms = list(StudyMaterial.objects.filter(status='completed'))

    print(f'Patching BM25 for {len(sms)} SM(s)...\n')
    ok = fail = skip = 0
    for sm in sms:
        result = rebuild_bm25_for_sm(sm)
        if result is True:
            ok += 1
        elif result is False:
            # distinguish skip vs error by checking if vectorstore_location exists
            if sm.vectorstore_location:
                fail += 1
            else:
                skip += 1

    print(f'\nDone — {ok} patched, {skip} skipped, {fail} errors')


if __name__ == '__main__':
    main()
