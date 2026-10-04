"""Windows preview from the Rust BGRA buffer, without PIL/Tk photo copies."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os

class NativePreview:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows DIB renderer only')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.user.GetDC.argtypes = [wintypes.HWND]
        self.user.GetDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi.StretchDIBits.argtypes = [wintypes.HDC] + [ctypes.c_int]*8 + [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]
        self.gdi.StretchDIBits.restype = ctypes.c_int
        self.gdi.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        self.gdi.PatBlt.argtypes = [wintypes.HDC] + [ctypes.c_int]*4 + [wintypes.DWORD]
        self.last_size = None

    def draw(self, canvas, width, height, pixels):
        if len(pixels) != width*height*4:
            raise ValueError('Invalid BGRA preview length')
        import struct
        cw,ch=canvas.winfo_width(),canvas.winfo_height()
        scale=min(1.0,max(1,cw-8)/width,max(1,ch-8)/height)
        w,h=max(1,int(width*scale)),max(1,int(height*scale))
        # BITMAPINFOHEADER, negative height = top-down rows; no channel conversion.
        info=struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,len(pixels),0,0,0,0)
        hwnd=canvas.winfo_id();dc=self.user.GetDC(hwnd)
        if not dc:raise OSError('Preview GetDC failed')
        try:
            if self.last_size != (cw,ch,w,h):
                self.gdi.PatBlt(dc,0,0,cw,ch,0x00000042)
                self.last_size = (cw,ch,w,h)
            self.gdi.SetStretchBltMode(dc,3)
            result=self.gdi.StretchDIBits(dc,(cw-w)//2,(ch-h)//2,w,h,0,0,width,height,
                ctypes.c_char_p(pixels),ctypes.c_char_p(info),0,0x00CC0020)
            if result in (0,-1):raise OSError('Preview StretchDIBits failed')
        finally:
            self.user.ReleaseDC(hwnd,dc)
        return w,h
