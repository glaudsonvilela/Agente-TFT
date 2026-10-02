"""Actual Tk layout/crop check with explicitly synthetic pixels; no neural claim."""
import tkinter as tk
import time
from types import SimpleNamespace as N
from PIL import Image,ImageDraw
from hm.app import App
from hm.core import region
root=tk.Tk();app=App(root)
im=Image.new('RGB',(1920,1080),(26,36,45));d=ImageDraw.Draw(im)
d.rectangle((345,915,1565,1075),fill=(60,70,80),outline=(240,250,255),width=4)
f=N(id=72,pts_ms=72000.,width=1920,height=1080,rgb=im.tobytes(),due_ns=time.perf_counter_ns())
rows=[region('control.refresh_price',[380,956,420,996],status='unknown')]
app.session=N(registry=N(fixed=lambda *a:[]),finished=True)
app.last={'reader':{'frame':f,'record':{'regions':rows},'view_kind':'reader'}}
app.which.set('reader');outcome=[]
def check():
    try:
        app.repaint();app.freeze=True;app.table.selection_set('0');app.selected();root.update_idletasks()
        assert app.current['frame'].id==72
        assert app.crop_label.winfo_height()>=app.zoom_photo.height(), 'crop image clipped by table'
        assert app.details.winfo_height()>=70, 'detail inspector not usable'
        outcome.append(True)
    finally:root.destroy()
root.after(500,check);root.mainloop()
if not outcome:raise SystemExit('HUD layout failed')
print('HUD_LAYOUT_CROP_OK')
