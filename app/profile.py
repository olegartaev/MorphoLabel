import csv
import io,json
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Landmark:
 number:int
 code:str
 name:str
 instruction:str=""
 required:bool=True
 gm_included:bool=False
 measurement_only:bool=False
 role:str="BOTH"
@dataclass(frozen=True)
class Profile:
 profile_id:str
 version:str
 landmarks:tuple[Landmark,...]
 def by_id(self,identifier):
  return next(point for point in self.landmarks if point.number==identifier)

def read_schema_csv(path: Path):
 """Read a small schema with comments and one of the supported delimiters."""
 text=Path(path).read_text(encoding="utf-8-sig")
 lines=[line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
 if not lines: raise ValueError("landmark schema is empty")
 sample="\n".join(lines[:10]);allowed=",;\t|"
 try: delimiter=csv.Sniffer().sniff(sample,delimiters=allowed).delimiter
 except csv.Error:
  header=lines[0];delimiter=max(allowed,key=lambda d: header.count(d))
  if header.count(delimiter)==0: raise ValueError("cannot determine landmark schema delimiter")
 reader=csv.DictReader(io.StringIO("\n".join(lines)),delimiter=delimiter)
 if not reader.fieldnames: raise ValueError("landmark schema is missing a header")
 reader.fieldnames=[(name or "").strip() for name in reader.fieldnames]
 return delimiter,reader.fieldnames,[{(key or "").strip():(value or "").strip() for key,value in row.items()} for row in reader]

def load_schema_profile(path:Path,profile_id="project_schema",version="1"):
 delimiter,fieldnames,raw_rows=read_schema_csv(path)
 required={"id","abbr","name","role"} if "role" in fieldnames else {"id","abbr","name"}
 if not required.issubset(fieldnames): raise ValueError("landmark schema requires columns: id, abbr, name, role")
 rows=[];ids=set();codes=set();allowed_roles={"CLASSICAL","GM","BOTH"}
 for line_number,row in enumerate(raw_rows,start=2):
  try:number=int(row.get("id", ""))
  except ValueError as exc: raise ValueError(f"landmark schema row {line_number}: id must be a positive integer") from exc
  code=row.get("abbr", "").strip();name=row.get("name", "").strip();role=row.get("role", "BOTH").strip().upper()
  if number<=0 or not code or not name: raise ValueError(f"landmark schema row {line_number}: id, abbr and name must be non-empty")
  if number in ids or code in codes: raise ValueError(f"duplicate landmark id or abbreviation at schema row {line_number}")
  if role not in allowed_roles: raise ValueError(f"landmark schema row {line_number}: invalid role {role!r}; expected CLASSICAL, GM or BOTH")
  ids.add(number);codes.add(code);rows.append(Landmark(number,code,name,row.get("instruction",name).strip(),role=role))
 if not rows: raise ValueError("landmark schema must contain at least one landmark")
 return Profile(profile_id,version,tuple(sorted(rows,key=lambda point:point.number)))

def load_profile(path:Path)->Profile:
 data=json.loads(Path(path).read_text(encoding="utf-8"));points=tuple(Landmark(**point) for point in data["landmarks"])
 if len({point.number for point in points})!=len(points):raise ValueError("Landmark IDs must be unique")
 return Profile(data["profile_id"],data["version"],tuple(sorted(points,key=lambda x:x.number)))


def get_landmarks_for_classical(schema):
 """Return schema landmarks used by classical morphometrics (CLASSICAL+BOTH)."""
 profile=schema if hasattr(schema,"landmarks") else load_schema_profile(Path(schema))
 return tuple(point for point in profile.landmarks if point.role in {"CLASSICAL","BOTH"})

def get_landmarks_for_gm(schema):
 """Return schema landmarks used by geometric morphometrics (GM+BOTH)."""
 profile=schema if hasattr(schema,"landmarks") else load_schema_profile(Path(schema))
 return tuple(point for point in profile.landmarks if point.role in {"GM","BOTH"})

def save_schema(path, landmarks):
 """Write schema CSV with normalized uppercase roles."""
 with Path(path).open("w",newline="",encoding="utf-8") as stream:
  writer=csv.DictWriter(stream,fieldnames=["id","abbr","name","role"]);writer.writeheader()
  for point in landmarks:
   role=str(getattr(point,"role","BOTH") or "BOTH").upper()
   if role not in {"CLASSICAL","GM","BOTH"}: raise ValueError(f"invalid role {role!r}")
   writer.writerow({"id":point.number,"abbr":point.code,"name":point.name,"role":role})
