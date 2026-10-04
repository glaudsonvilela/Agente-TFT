"""Local onboarding. Declared identity is not verified ownership or fetched history."""
import json
import os
from pathlib import Path
import uuid

REGIONS=('BR','NA','LAN','LAS','EUW','EUNE','KR','JP','OCE','TR','RU','SEA','TW','VN')
WELCOME='Bem-vindo! Coloque seu nick e região para começar.'


def profile_path():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home())/'AgenteTFT-HUD-HM4'/'player-profile.json'


def load():
    try:
        path=profile_path()
        if path.stat().st_size>4096:return None
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema_version')!=1 or data.get('region') not in REGIONS:return None
        if not isinstance(data.get('nickname'),str) or not data['nickname'].strip():return None
        uuid.UUID(data['profile_id']);return data
    except (OSError,ValueError,KeyError,TypeError):return None


def save(nickname,region):
    nickname=nickname.strip()
    if not 2<=len(nickname)<=80 or any(ord(c)<32 for c in nickname):raise ValueError('Informe seu nick (nome#tag, se disponível).')
    if region not in REGIONS:raise ValueError('Escolha uma região válida.')
    existing=load()
    same=existing and existing['nickname']==nickname and existing['region']==region
    data=dict(schema_version=1,profile_id=existing['profile_id'] if same else str(uuid.uuid4()),
              nickname=nickname,region=region,identity_source='user_entered',identity_verified=False,
              history_source='local_observed_sessions',external_history_connected=False)
    path=profile_path();path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return data
