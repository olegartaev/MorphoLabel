"""Batch local worker: cached development, localization, masks, QC contact sheet."""
from pathlib import Path
import sys,random,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from app.paths import ORIGINALS,REPORTS
from app.normalization_pipeline import normalize

if __name__=="__main__":
 files=[]
 for folder in sorted(p for p in ORIGINALS.iterdir() if p.is_dir()):
  photos=sorted(folder.glob("*.nef"));
  if photos: files.append(photos[len(photos)//2])
 random.Random(20260815).shuffle(files);files=files[:30];rows=[];thumbs=[]
 for source in files:
  meta=normalize(source);rows.append({"source":meta["source_relpath"],"crop":meta["crop_bounds"],"status":meta["normalization_status"],"qc":meta["qc"]});image=Image.open(Path(meta["standardized_relpath"])).convert("RGB");image.thumbnail((280,180));thumbs.append((source.name,image,meta["normalization_status"]))
 REPORTS.mkdir(exist_ok=True);sheet=Image.new("RGB",(4*300,((len(thumbs)+3)//4)*220),"white");draw=ImageDraw.Draw(sheet)
 for n,(name,image,status) in enumerate(thumbs):
  x=(n%4)*300;y=(n//4)*220;sheet.paste(image,(x,y));draw.text((x,y+184),f"{name}\n{status}",fill="black")
 sheet.save(REPORTS/"normalization_acceptance_contact_sheet.png");(REPORTS/"normalization_acceptance_review.json").write_text(json.dumps(rows,indent=2),encoding="utf-8");print(json.dumps({"examples":len(rows),"review":str(REPORTS/'normalization_acceptance_review.json'),"sheet":str(REPORTS/'normalization_acceptance_contact_sheet.png')}))
