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

block_font=ImageFont.truetype(str(font_path),52)
block=Image.new("L",(720,220),255)
draw=ImageDraw.Draw(block)
draw.text((40,25),"ALPHA 1",font=block_font,fill=0)
draw.text((40,120),"BETA 2",font=block_font,fill=0)
raw=block.tobytes()
(OUT/"textblock.pgm").write_bytes(f"P5\n{block.width} {block.height}\n255\n".encode("ascii")+raw)

shop_rows=[("ALPHA","1"),("BETA","2"),("GAMMA","3"),("DELTA","4"),("OMEGA","5")]
for scale,width,height,name_w,cost_x,row_h,font_size in [
    (3,564,525,459,499,81,38),
    (4,732,660,612,652,108,50),
]:
    im=Image.new("L",(width,height),255)
    draw=ImageDraw.Draw(im)
    sf=ImageFont.truetype(str(font_path),font_size)
    for slot,(name,cost) in enumerate(shop_rows):
        y=10+slot*(row_h+20)
        draw.text((18,y+5),name,font=sf,fill=0)
        draw.text((cost_x+4,y+5),cost,font=sf,fill=0)
    raw=im.tobytes()
    (OUT/f"shop_atlas_scale{scale}.pgm").write_bytes(
        f"P5\n{im.width} {im.height}\n255\n".encode("ascii")+raw)
