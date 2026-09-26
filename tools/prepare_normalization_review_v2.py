from pathlib import Path
import sys,random,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw
from app.paths import ORIGINALS,REPORTS
from app.normalization_pipeline import normalize

if __name__=="__main__":
 groups=[]
 for folder in sorted(p for p in ORIGINALS.iterdir() if p.is_dir()):
  photos=sorted(folder.glob("*.nef"));groups.append(photos)
 rng=random.Random(20260815);chosen=[]
 for round_no in range(2):
  for photos in groups:
   if photos:chosen.append(photos[(round_no*len(photos)//2+len(photos)//3)%len(photos)])
 rng.shuffle(chosen);chosen=chosen[:30];rows=[];thumbs=[]
 for source in chosen:
  meta=normalize(source);rows.append({"source":meta["source_relpath"],"crop":meta["crop_bounds"],"status":meta["normalization_status"],"qc":meta["qc"]});im=Image.open(Path(meta["standardized_relpath"])).convert("RGB");im.thumbnail((280,180));thumbs.append((source.name,im,meta["normalization_status"]))
 REPORTS.mkdir(exist_ok=True);sheet=Image.new("RGB",(1200,((len(thumbs)+3)//4)*220),"white");d=ImageDraw.Draw(sheet)
 for n,(name,im,status) in enumerate(thumbs):
  x=n%4*300;y=n//4*220;sheet.paste(im,(x,y));d.text((x,y+184),f"{name}\n{status}",fill="black")
 sheet.save(REPORTS/"normalization_acceptance_contact_sheet.png");(REPORTS/"normalization_acceptance_review.json").write_text(json.dumps(rows,indent=2),encoding="utf-8");print(json.dumps({"examples":len(rows),"sheet":"reports/normalization_acceptance_contact_sheet.png","review":"reports/normalization_acceptance_review.json"}))
