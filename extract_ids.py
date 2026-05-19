import json

with open("study_material.json") as f:
    data = json.load(f)

unique_ids = sorted({
    course["study_material_id"]
    for course in data["courses"]
    if course["study_material_id"] is not None
})

with open("unique_study_material_ids.json", "w") as f:
    json.dump(unique_ids, f, indent=2)

print(f"Extracted {len(unique_ids)} unique study_material_id values")
