"""Destructive landmark actions kept small and testable."""
def clear_all_landmarks(record:dict):
    record["points"]={}
    return record
