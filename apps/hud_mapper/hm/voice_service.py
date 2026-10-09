"""Anonymous app session with the TFT voice service. Provider keys stay on server."""
import http.client
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import uuid
from .voice_api import ElevenLabsSpeech, SpeechError


def service_address(value):
    url=urlsplit(value or '')
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise SpeechError('O endereço HTTPS do serviço de voz ainda não foi configurado.')
    return url.hostname,url.port or 443


def installation_id():
    base=os.environ.get('LOCALAPPDATA')
    if not base:raise SpeechError('Pasta de configuração do Windows indisponível.')
    path=Path(base)/'AgenteTFT-HUD-HM4'/'installation-id.txt'
    try:return str(uuid.UUID(path.read_text().strip()))
    except (OSError,ValueError):
        identity=str(uuid.uuid4());path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(identity,encoding='ascii');return identity


class ServiceSpeech(ElevenLabsSpeech):
    def __init__(self, service_url, token, *, connection_factory=http.client.HTTPSConnection):
        super().__init__(token,'service-managed',connection_factory=connection_factory)
        self.host,self.port=service_address(service_url)

    def http_error(self,status):
        return {401:'Sessão de voz expirada. Clique em Conectar voz.',
                429:'Serviço de voz ocupado ou limite atingido. Tente mais tarde.'}.get(status,
                'O serviço de voz está indisponível no momento.')

    def open_request(self,text,*,tone=None):
        connection=self.connection_factory(self.host,self.port,timeout=4)
        self.connection=connection
        payload={'text':text}
        if tone:payload['tone']=tone
        connection.request('POST','/v1/voice',json.dumps(payload).encode('utf-8'),
                           {'Authorization':'Bearer '+self._key,'Content-Type':'application/json','Accept':'audio/pcm'})
        return connection


def connect(service_url=None, *, connection_factory=http.client.HTTPSConnection):
    if service_url is None:
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
        try:service_url=json.loads((root/'configs/services/voice.json').read_text())['service_url']
        except (OSError,ValueError,KeyError):service_url=None
    host,port=service_address(service_url)
    connection=connection_factory(host,port,timeout=3)
    try:
        connection.request('POST','/v1/session',json.dumps({'installation_id':installation_id()}).encode(),
                           {'Content-Type':'application/json'})
        response=connection.getresponse()
        if response.status!=200:raise SpeechError('Serviço de voz indisponível. Tente novamente mais tarde.')
        raw=response.read(16385)
        if len(raw)>16384:raise SpeechError('Resposta inválida do serviço de voz.')
        token=json.loads(raw)['token']
        if not isinstance(token,str) or not 32<=len(token)<=4096:raise ValueError()
        return ServiceSpeech(service_url,token,connection_factory=connection_factory)
    except SpeechError:raise
    except Exception:raise SpeechError('Não foi possível conectar ao serviço de voz.') from None
    finally:connection.close()


def fetch_player_summary(client,profile):
    if not isinstance(client,ServiceSpeech):
        return dict(status='external_history_unavailable',summary='Histórico externo ainda não conectado.')
    connection=client.connection_factory(client.host,client.port,timeout=3)
    try:
        connection.request('POST','/v1/player-summary',json.dumps({
            'nickname':profile['nickname'],'region':profile['region']}).encode('utf-8'),
            {'Authorization':'Bearer '+client._key,'Content-Type':'application/json'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError()
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError()
        result=json.loads(raw)
        if not isinstance(result,dict) or not isinstance(result.get('summary'),str):raise ValueError()
        return result
    except Exception:
        return dict(status='external_history_unavailable',summary='Histórico indisponível. O perfil local continua salvo.')
    finally:connection.close()
