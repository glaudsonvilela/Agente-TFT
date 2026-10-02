"""Actual Tk layout/crop check with explicitly synthetic pixels; no neural claim."""
import tkinter as tk
import time,json
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
def check(size):
    app.repaint();app.freeze=True;app.table.selection_set('0');app.selected();root.update_idletasks()
    geometry=dict(window=[root.winfo_width(),root.winfo_height()],crop=app.crop_label.winfo_height(),
        crop_image=app.zoom_photo.height(),details=app.details.winfo_height(),table=app.table.winfo_height())
    print('HUD_LAYOUT='+json.dumps(geometry),flush=True)
    assert app.current['frame'].id==72
    assert geometry['crop']>=geometry['crop_image'], 'crop image clipped by table'
    assert geometry['details']>=70, 'detail inspector not usable'
    assert app.details.winfo_y()+app.details.winfo_height()<=app.details.master.winfo_height(), 'details outside parent'
    outcome.append(size)
def compact():
    try:check('compact')
    finally:root.destroy()
def normal():
    try:
        check('default');root.geometry('1100x750');root.after(500,compact)
    except Exception:
        root.destroy();raise
root.after(500,normal);root.mainloop()
if outcome!=['default','compact']:raise SystemExit('HUD layout failed')
print('HUD_LAYOUT_CROP_OK')
