"""ElevenLabs text-only TTS. No local synthesis, image upload or model download."""
from collections import OrderedDict
import http.client
import io
import json
import re
import time
import wave

MODEL='eleven_flash_v2_5'
LANGUAGE='pt'
OUTPUT_FORMAT='pcm_22050'
MAX_AUDIO=2*1024*1024


class SpeechError(RuntimeError):pass


def validate_voice_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):
        raise SpeechError('Informe um Voice ID válido da ElevenLabs.')
    return value


class ElevenLabsSpeech:
    def __init__(self,api_key,voice_id,*,connection_factory=http.client.HTTPSConnection):
        if not api_key or not isinstance(api_key,str) or '\n' in api_key or '\r' in api_key:
            raise SpeechError('Credencial da ElevenLabs não configurada no serviço.')
        self._key=api_key;self.voice_id=validate_voice_id(voice_id)
        self.connection_factory=connection_factory;self.cache=OrderedDict()
        self.closed=False;self.connection=None;self.last_metrics={}

    def cache_identity(self):
        # Bump revision when pronunciation dictionaries or voice settings change.
        return dict(provider='elevenlabs',voice_id=self.voice_id,model=MODEL,
                    language=LANGUAGE,output_format=OUTPUT_FORMAT,revision=1)

    def synthesize(self,text):
        if self.closed:raise SpeechError('Cliente de voz encerrado.')
        if not isinstance(text,str) or not 1<=len(text)<=500:raise SpeechError('Texto da dica fora do limite de voz.')
        started=time.monotonic()
        if text in self.cache:
            self.cache.move_to_end(text);self.last_metrics=dict(cache_hit=True,request_ms=0)
            return self.cache[text]
        # Endpoint fixed: API keys never follow a redirect or a user-provided URL.
        connection=None
        try:
            connection=self.open_request(text)
            response=connection.getresponse()
            if response.status!=200:
                raise SpeechError(self.http_error(response.status))
            media=response.getheader('Content-Type','').split(';')[0].lower()
            if media not in ('audio/pcm','audio/x-pcm','audio/raw','application/octet-stream'):
                raise SpeechError('A API não devolveu áudio PCM compatível.')
            pcm=bytearray()
            while True:
                if self.closed or time.monotonic()-started>4:raise SpeechError('A voz excedeu o prazo da solicitação.')
                chunk=response.read1(16384)
                if not chunk:break
                pcm.extend(chunk)
                if len(pcm)>MAX_AUDIO:raise SpeechError('Áudio excedeu o limite de memória.')
            if not pcm or len(pcm)%2:raise SpeechError('A API devolveu áudio vazio ou incompleto.')
            output=io.BytesIO()
            with wave.open(output,'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(pcm)
            result=output.getvalue();self.cache[text]=result
            while len(self.cache)>16 or sum(map(len,self.cache.values()))>4*1024*1024:self.cache.popitem(last=False)
            self.last_metrics=dict(cache_hit=False,request_ms=(time.monotonic()-started)*1000,audio_bytes=len(result))
            return result
        except SpeechError:raise
        except Exception:
            # Never forward provider bodies, headers, tokens or request text into logs.
            raise SpeechError('Falha de conexão ou tempo limite da ElevenLabs.') from None
        finally:
            if self.connection:self.connection.close()
            self.connection=None

    def http_error(self,status):
        messages={401:'Chave da ElevenLabs recusada.',403:'A conta não tem acesso a esta voz ou formato.',
                  404:'Voice ID não encontrado.',429:'Limite ou créditos da ElevenLabs indisponíveis.'}
        return messages.get(status,f'ElevenLabs indisponível (HTTP {status}).')

    def open_request(self,text):
        connection=self.connection_factory('api.elevenlabs.io',timeout=2)
        self.connection=connection
        body=json.dumps(dict(text=text,model_id=MODEL,language_code=LANGUAGE)).encode('utf-8')
        connection.request('POST',f'/v1/text-to-speech/{self.voice_id}?output_format={OUTPUT_FORMAT}',body,
                           {'xi-api-key':self._key,'Content-Type':'application/json','Accept':'audio/pcm'})
        return connection

    def close(self):
        self.closed=True;self.cache.clear()
        if self.connection:self.connection.close()
