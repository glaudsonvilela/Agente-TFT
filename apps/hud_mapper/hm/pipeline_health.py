"""Cheap local heartbeat checks; frame arrival never implies successful OCR."""

def snapshot(*, now_ns, source, reader_item, counts):
    def age(value):return max(0.,(now_ns-value)/1e6) if value is not None else None
    analysis_age=age(getattr(source,'last_analysis_received_ns',None))
    preview_age=age(getattr(source,'last_preview_received_ns',None))
    reader_age=age(reader_item.get('ready_ns')) if reader_item else None
    plan=((reader_item or {}).get('record') or {}).get('reader_input_transform') or {}
    if getattr(source,'error',None):code='CAPTURE_ERROR';message='Captura: '+str(source.error)
    elif analysis_age is None:
        code='NO_ANALYSIS_FRAMES';message='Nenhum quadro de análise recebido da captura Rust.'
    elif analysis_age>3000:
        code='ANALYSIS_FRAMES_STALLED';message='A captura deixou de entregar quadros novos para análise.'
    elif plan.get('supported') is False:
        code='READER_FORMAT_REJECTED';message='Captura recebida; leitores rejeitaram o formato da imagem.'
    elif reader_age is None or reader_age>3000:
        code='READER_NOT_RETURNING';message='Captura recebida; leitura local ainda não devolveu um resultado atual.'
    else:
        code='DELIVERY_AND_READER_ACTIVE';message='Quadros e leituras locais chegando; consulte o motivo da decisão.'
    return dict(code=code,message=message,analysis_delivery_age_ms=analysis_age,
                preview_delivery_age_ms=preview_age,reader_delivery_age_ms=reader_age,
                source_frames=counts['source_frames'],reader_results=counts['read_frames'],
                confirms_ocr_accuracy=False)
