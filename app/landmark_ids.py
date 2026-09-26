"""Single canonical landmark identity mapping."""
def landmark_id(number:int)->str:
 return str(int(number))
def number_from_id(value)->int:
 value=str(value)
 return int(value[1:]) if value.upper().startswith("P") else int(value)
def storage_key(number:int)->str:
 return str(int(number))
def record_key(points:dict, number:int)->str:
 canonical=landmark_id(number)
 return canonical if canonical in points else storage_key(number)
def list_index_to_number(index:int)->int:
 return int(index)+1
def number_to_list_index(number:int)->int:
 return int(number)-1

