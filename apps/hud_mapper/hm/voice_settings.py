"""Windows user-bound encrypted credentials; not part of session exports."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from .voice_api import validate_voice_id,SpeechError


def settings_path():
    base=os.environ.get('LOCALAPPDATA')
    return Path(base)/'AgenteTFT-HUD-HM4'/'elevenlabs.dpapi' if base else None


def crypt(data,*,decrypt=False):
    if os.name!='nt':raise SpeechError('A configuração protegida de voz requer Windows.')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    incoming=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    dll=ctypes.WinDLL('crypt32',use_last_error=True)
    fn=dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(out)):
        raise SpeechError('Não foi possível abrir/salvar a chave protegida neste usuário Windows.')
    try:return ctypes.string_at(out.data,out.size)
    finally:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        kernel.LocalFree(out.data)


def load():
    path=settings_path()
    if path is None or not path.exists():return None
    if path.stat().st_size>16384:raise SpeechError('Configuração de voz inválida.')
    try:
        settings=json.loads(crypt(path.read_bytes(),decrypt=True))
        validate_voice_id(settings['voice_id'])
        if not isinstance(settings['api_key'],str) or not settings['api_key']:raise ValueError()
        return settings
    except SpeechError:raise
    except Exception:raise SpeechError('Não foi possível ler a configuração de voz.') from None


def save(api_key,voice_id):
    validate_voice_id(voice_id)
    if not api_key or len(api_key)>4096 or '\n' in api_key or '\r' in api_key:
        raise SpeechError('Informe uma chave de API válida.')
    path=settings_path()
    if path is None:raise SpeechError('Pasta do usuário Windows indisponível.')
    encrypted=crypt(json.dumps(dict(api_key=api_key,voice_id=voice_id)).encode())
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_bytes(encrypted);temp.replace(path)
