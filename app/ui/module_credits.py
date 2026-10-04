"""Presentation metadata; module authors are independent of the core author."""
BUILTIN_CREDITS={
    'landmarks':('Oleg Artaev','Crop, landmarks, measurements and export'),
    'xray_counts':('Oleg Artaev','X-ray crops, structures and calculated traits'),
}

def module_credit_rows(registry):
    rows=[]
    for spec in registry.available():
        author,scope=BUILTIN_CREDITS.get(spec.module_id,('See module documentation',spec.description)) if spec.source=='builtin' else ('See module documentation',spec.description)
        rows.append((spec.display_name,author,scope))
    return tuple(rows)
