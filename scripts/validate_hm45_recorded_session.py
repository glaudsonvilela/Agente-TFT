"""Run sealed replay pixels through the packaged IP core on a bounded VM budget."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import socket
import threading
import time
from PIL import Image
from hm45_core_server import AnalysisCore, CoreTCPServer
from hm45_protocol import send_packet, recv_packet, encode_rgb
from hm.replay_decision import ReplayDecisionEngine
from hm.replay_coach import coach_prompt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads((args.session/'training-manifest.json').read_text())
    if not 1<=len(manifest['samples'])<=200:raise ValueError('Bounded sealed sample set required')
    args.output.mkdir(parents=True,exist_ok=False)
    core=AnalysisCore();token=secrets.token_hex(32);server=CoreTCPServer(core,token)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    engine=ReplayDecisionEngine('/opt/agente-tft/configs');rows=[];tips=[];peak=0
    try:
        with socket.create_connection(server.server_address,timeout=20) as sock:
            sock.settimeout(30);send_packet(sock,{'op':'hello','token':token});hello,_=recv_packet(sock)
            if not hello.get('ok'):raise ValueError('Core handshake failed')
            with (args.output/'frames.jsonl').open('x') as stream:
                for index,sample in enumerate(manifest['samples']):
                    image_path=args.session/sample['image']
                    if hashlib.sha256(image_path.read_bytes()).hexdigest()!=sample['image_sha256']:
                        raise ValueError('Source sample checksum mismatch')
                    with Image.open(image_path) as image:
                        rgb=image.convert('RGB').tobytes();width,height=image.size
                    codec,payload=encode_rgb(rgb,width,height)
                    header=dict(frame_id=index,request_id=index,source_ms=sample['source_ms'],
                        width=width,height=height,codec=codec,include_shop=True)
                    start=time.perf_counter()
                    send_packet(sock,dict(header,op='reader'),payload);read,_=recv_packet(sock)
                    if not read.get('ok'):raise RuntimeError(read.get('error'))
                    reader_ms=(time.perf_counter()-start)*1000
                    answer=engine.evaluate(read['result']);tip=coach_prompt(answer)
                    if tip.get('actionable'):tips.append(dict(source_ms=sample['source_ms'],tip=tip))
                    start=time.perf_counter()
                    send_packet(sock,dict(header,op='hub',board_read=answer.get('board')),payload)
                    result,_=recv_packet(sock)
                    if not result.get('ok'):raise RuntimeError(result.get('error'))
                    hub_ms=(time.perf_counter()-start)*1000;snapshot=result['result']['snapshot']
                    neural=snapshot.get('neural_items') or {}
                    if not neural.get('active'):raise RuntimeError('Item neural model is inactive')
                    usage=int(Path('/sys/fs/cgroup/memory.current').read_text())
                    peak=max(peak,usage)
                    row=dict(frame=index,source_ms=sample['source_ms'],reader_ip_ms=reader_ms,
                        hub_ip_ms=hub_ms,item_neural_ms=neural['inference_ms'],cgroup_memory_bytes=usage,
                        arena_projection=snapshot['arena_projection_status'],tip=tip)
                    rows.append(row);stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
        def p95(key):
            values=sorted(r[key] for r in rows);return values[int((len(values)-1)*.95)]
        report=dict(complete=True,frames=len(rows),source=args.session.name,
            reader_ip_p95_ms=p95('reader_ip_ms'),hub_ip_p95_ms=p95('hub_ip_ms'),
            item_neural_p95_ms=p95('item_neural_ms'),peak_cgroup_memory_bytes=peak,tips=tips,
            transport='authenticated_loopback_tcp_inside_core_container',
            windows_wsl_field_test=False,champion_identity_accuracy_measured=False)
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)
        if not tips:raise RuntimeError('Recorded session produced no decision')
    finally:
        server.shutdown();server.server_close();thread.join(2);core.close()


if __name__=='__main__':main()
