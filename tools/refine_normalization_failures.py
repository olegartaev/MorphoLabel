from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from app.paths import REPORTS
from app.normalization_pipeline_v2 import normalize

if __name__=="__main__":
 rows=json.loads((REPORTS/"normalization_acceptance_review.json").read_text(encoding="utf-8"));out=[];thumbs=[]
 for row in rows:
  source=Path(row["source"]);m=normalize(source,force=True);out.append({"source":m["source_relpath"],"crop":m["crop_bounds"],"status":m["normalization_status"],"qc":m["qc"]});im=Image.open(Path(m["standardized_relpath"])).convert("RGB");im.thumbnail((280,180));thumbs.append((source.name,im,m["qc"]["reason"]))
 sheet=Image.new("RGB",(1200,((len(thumbs)+3)//4)*220),"white");d=ImageDraw.Draw(sheet)
 for n,(name,im,qc) in enumerate(thumbs):
  x=n%4*300;y=n//4*220;sheet.paste(im,(x,y));d.text((x,y+184),f"{name}\n{qc}",fill="black")
 sheet.save(REPORTS/"normalization_acceptance_contact_sheet.png");(REPORTS/"normalization_acceptance_review.json").write_text(json.dumps(out,indent=2),encoding="utf-8");print(json.dumps({"examples":len(out)}))
