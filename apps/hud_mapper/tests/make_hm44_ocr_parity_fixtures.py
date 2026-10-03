from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT=Path("hm44-parity-fixtures")
OUT.mkdir(exist_ok=False)
fonts=[
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
]
font_path=next((p for p in fonts if p.is_file()),None)
if font_path is None:
    raise SystemExit("No approved Windows system font fixture source found")
font=ImageFont.truetype(str(font_path),68)
cases={"gold":"50","level":"8","stage":"4-2","xp":"20/68"}
for name,text in cases.items():
    im=Image.new("L",(360,120),255)
    draw=ImageDraw.Draw(im)
    box=draw.textbbox((0,0),text,font=font)
    tw,th=box[2]-box[0],box[3]-box[1]
    x=(im.width-tw)//2
    y=(im.height-th)//2-box[1]
    draw.text((x,y),text,font=font,fill=0)
    raw=im.tobytes()
    (OUT/f"{name}.pgm").write_bytes(f"P5\n{im.width} {im.height}\n255\n".encode("ascii")+raw)
print("HM44_PARITY_FIXTURES="+str(OUT))
