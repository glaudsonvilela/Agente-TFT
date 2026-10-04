"""Operator-only credential setup. Run interactively on BigBANANA, never in CI."""
import getpass
import os
from pathlib import Path
import re
import tempfile
from hm.voice_api import validate_voice_id


def main():
    path=Path.home()/'.config/agente-tft/voice.env'
    key=getpass.getpass('Chave ElevenLabs (oculta): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,4096}',key):
        raise SystemExit('Formato de chave inválido; nenhum arquivo salvo.')
    voice=validate_voice_id(input('Voice ID escolhido na ElevenLabs: ').strip())
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False,encoding='utf-8') as temp:
        os.chmod(temp.name,0o600)
        temp.write(f'ELEVENLABS_API_KEY={key}\nELEVENLABS_VOICE_ID={voice}\n')
        temp.flush();os.fsync(temp.fileno())
        temporary=Path(temp.name)
    temporary.replace(path)
    print('Configuração privada salva em '+str(path))
    print('Nenhuma chamada paga feita. Configure o serviço HTTPS antes de distribuir o aplicativo.')


if __name__=='__main__':main()
