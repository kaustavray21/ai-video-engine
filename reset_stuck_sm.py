#!/usr/bin/env python
import os
import sys
import argparse
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
try:
    django.setup()
except Exception as e:
    print(f"Error initializing Django: {e}")
    sys.exit(1)

from apps.core.models.study_material import StudyMaterial
from apps.core.models.study_material_file import StudyMaterialFile

def main():
    parser = argparse.ArgumentParser(description="Reset stuck processing study material status to failed")
    parser.add_argument('-i', '--id', type=int, required=True, help="ID of the study material to reset")
    args = parser.parse_args()

    sm_id = args.id

    try:
        sm = StudyMaterial.objects.get(pk=sm_id)
    except StudyMaterial.DoesNotExist:
        print(f"Error: StudyMaterial with ID {sm_id} does not exist.")
        sys.exit(1)

    print(f"Found StudyMaterial '{sm.name}' (ID={sm.id}) with status='{sm.status}'.")
    
    # 1. Update StudyMaterial status
    sm.status = StudyMaterial.STATUS_FAILED
    sm.save(update_fields=['status'])
    print(f"-> Updated StudyMaterial status to 'failed'.")

    # 2. Update stuck StudyMaterialFile status
    stuck_files = StudyMaterialFile.objects.filter(
        study_material=sm,
        status=StudyMaterialFile.STATUS_PROCESSING
    )
    count = stuck_files.count()
    if count > 0:
        stuck_files.update(status=StudyMaterialFile.STATUS_FAILED)
        print(f"-> Reset {count} processing files to 'failed'.")
    else:
        print("-> No files were stuck in 'processing' state.")

    print("\nSuccess! You can now retry this study material.")

if __name__ == '__main__':
    main()
