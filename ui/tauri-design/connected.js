'use strict';
// Runs only in the installed local studio. The design preview remains
// independently navigable and keeps its illustrative labels.
if (new URLSearchParams(location.search).has('connected')) {
  document.body.classList.add('connected-app');
  const originalRender = render;
  let sourceRows = [], selected = null, state = null, starting = false, profilePrompted = false, sourceLoadRevision = 0;
  const ratedTips = new Set();
  const localApi = new Proxy({}, {get: (_target, method) => async (...args) => {
    const response = await fetch(new URL(`api/${method}`, location.href), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({args}), cache: 'no-store'
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || 'Motor local indisponível.');
    return payload.result;
  }});
  const api = () => localApi;
  const clean = value => String(value == null ? '' : value);
  const escapeHtml = value => clean(value).replace(/[&<>"']/g, ch =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  let diagnosticMemory = {sessionId: null, hud: new Map(), shop: new Map(), hub: null};
  let fastSnapshot = null, fastRequestBusy = false, fastFrameId = null, fastEpoch = null;
  const markerTrails = new Map();
  let previewGeneration = 0, previewRequest = null;
  const previewDrawTimes = [];
  function candidateForMarker(marker, fast) {
    if (marker.color !== 'green') return null;
    const hub = state?.hub_diagnostic;
    if (!hub || hub.epoch !== fast.epoch || fast.source_ms < hub.source_ms ||
        fast.source_ms - hub.source_ms > 3500) return null;
    const box = marker.box;
    if (!Array.isArray(box)) return null;
    const cx = (box[0]+box[2])/2, cy = (box[1]+box[3])/2;
    const nearest = (hub.boxes || []).filter(row => row.id.startsWith('hub.marker.') &&
      Array.isArray(row.observed_box)).map(row => {
        const b = row.observed_box;
        return {row, distance: Math.hypot(cx-(b[0]+b[2])/2, cy-(b[1]+b[3])/2)};
      }).sort((a,b) => a.distance-b.distance)[0];
    if (!nearest || nearest.distance >= 80) return null;
    const b = nearest.row.observed_box;
    const bx = (b[0]+b[2])/2, by = (b[1]+b[3])/2;
    const closestTrack = (fast.markers || []).filter(row => row.color === 'green' &&
      Array.isArray(row.box)).map(row => ({row, distance: Math.hypot(
        bx-(row.box[0]+row.box[2])/2, by-(row.box[1]+row.box[3])/2)}))
      .sort((a,b) => a.distance-b.distance)[0];
    return closestTrack?.row === marker && nearest.row.support_frames >= 2 &&
      nearest.row.label !== 'unidade não identificada'
      ? nearest.row.label : null;
  }
  function drawFastTracks(context, imageWidth, imageHeight, sourceMs, epoch) {
    const fast = fastSnapshot || state?.fast_diagnostic;
    if (fast?.status !== 'observed' || !Number.isFinite(sourceMs) ||
        fast.epoch !== epoch || sourceMs < fast.source_ms || sourceMs-fast.source_ms > 1400) return;
    const size = fast.image_size || [];
    if (!(size[0] > 0 && size[1] > 0)) return;
    const sx=imageWidth/size[0], sy=imageHeight/size[1];
    context.save();
    context.font='bold 12px sans-serif';
    for (const marker of fast.markers || []) {
      const box=marker.box;
      if (!Array.isArray(box) || box.length !== 4) continue;
      const [x1,y1,x2,y2]=box;
      const x=x1*sx,y=y1*sy,w=(x2-x1)*sx,h=(y2-y1)*sy;
      if (![x,y,w,h].every(Number.isFinite) || w <= 0 || h <= 0) continue;
      const color=marker.color === 'green' ? '#71f0aa' : marker.color === 'purple' ? '#b29aff' : '#ff8c8c';
      const points=markerTrails.get(marker.track_id) || [];
      if (points.length > 1) {
        context.beginPath();
        points.forEach((point,index) => index ? context.lineTo(point.x*sx,point.y*sy)
          : context.moveTo(point.x*sx,point.y*sy));
        context.strokeStyle=color+'b0';context.lineWidth=2;context.stroke();
      }
      context.strokeStyle=color;context.lineWidth=2;
      context.strokeRect(x,y,w,Math.max(4,h));
      if (marker.color === 'purple' && Array.isArray(marker.avatar_box) &&
          marker.avatar_box.length === 4) {
        const [ax1,ay1,ax2,ay2]=marker.avatar_box;
        const ax=ax1*sx,ay=ay1*sy,aw=(ax2-ax1)*sx,ah=(ay2-ay1)*sy;
        if ([ax,ay,aw,ah].every(Number.isFinite) && aw>0 && ah>0) {
          context.setLineDash([5,4]);
          context.strokeRect(ax,ay,aw,ah);
          context.setLineDash([]);
          context.beginPath();context.arc(ax+aw/2,ay+ah*.72,3,0,Math.PI*2);
          context.fillStyle=color;context.fill();
        }
      }
      const candidate=candidateForMarker(marker,fast);
      const hp=fast.player_hp;
      const hpText=marker.color === 'purple' && Number.isInteger(hp?.value)
        ? ` · ${hp.fresh ? 'HP jogador' : 'último HP'} ${hp.value}` : '';
      const label=`#${marker.track_id} ${marker.color === 'purple' ? 'avatar?'+hpText : candidate ? candidate+' ?' : marker.color}`;
      const labelWidth=Math.min(imageWidth-x,context.measureText(label).width+10);
      context.fillStyle='#090d16e8';context.fillRect(x,Math.max(0,y-20),labelWidth,18);
      context.fillStyle='#fff';context.fillText(label,x+5,Math.max(13,y-6),Math.max(0,labelWidth-10));
    }
    const hp=fast.player_hp;
    const hpBox=hp?.box;
    if (Number.isInteger(hp?.value) && Array.isArray(hpBox) && hpBox.length === 4) {
      const [x1,y1,x2,y2]=hpBox;
      const x=x1*sx,y=y1*sy,w=(x2-x1)*sx,h=(y2-y1)*sy;
      if ([x,y,w,h].every(Number.isFinite) && w>0 && h>0) {
        context.strokeStyle='#ffd276';context.lineWidth=2;context.strokeRect(x,y,w,h);
        const label=`HP jogador ${hp.value}`;
        const labelWidth=Math.min(imageWidth-x,context.measureText(label).width+10);
        context.fillStyle='#090d16e8';context.fillRect(x,Math.max(0,y-20),labelWidth,18);
        context.fillStyle='#fff';context.fillText(label,x+5,Math.max(13,y-6),Math.max(0,labelWidth-10));
      }
    }
    context.restore();
  }
  function drawObservedBoxes(context, imageWidth, imageHeight, sourceMs, epoch) {
    const read = state?.live_diagnostic;
    if (!read || !Number.isFinite(sourceMs) || !Number.isFinite(epoch) ||
        read.epoch !== epoch || sourceMs < read.source_ms || sourceMs - read.source_ms > 3000) return;
    const size = read.image_size || [];
    if (!(size[0] > 0 && size[1] > 0)) return;
    const sx = imageWidth / size[0], sy = imageHeight / size[1];
    context.save();
    context.font = 'bold 13px sans-serif';
    context.lineWidth = 2;
    for (const row of read.boxes || []) {
      if (row.value == null || row.value === '' || !Array.isArray(row.box) || row.box.length !== 4) continue;
      const observed = row.status === 'single_frame_observation' || row.status === 'observed';
      if (!observed) continue;
      const [x1,y1,x2,y2] = row.box;
      const x = x1*sx, y = y1*sy, w = (x2-x1)*sx, h = (y2-y1)*sy;
      if (![x,y,w,h].every(Number.isFinite) || w <= 0 || h <= 0) continue;
      const label = `${row.id.replace(/^hud\.|^shop\./, '')}: ${clean(row.value)}`;
      context.strokeStyle = row.id.startsWith('shop.') ? '#68e0bb' : '#f7c774';
      context.strokeRect(x, y, w, h);
      const labelWidth = Math.min(imageWidth - x, context.measureText(label).width + 10);
      context.fillStyle = '#090d16e8';
      context.fillRect(x, Math.max(0, y-20), labelWidth, 19);
      context.fillStyle = '#fff';
      context.fillText(label, x+5, Math.max(14, y-6), Math.max(0, labelWidth-10));
    }
    context.restore();
  }
  function drawHubBoxes(context, imageWidth, imageHeight, sourceMs, epoch) {
    const hub = state?.hub_diagnostic;
    if (!hub || !Number.isFinite(sourceMs) || !Number.isFinite(epoch) ||
        hub.epoch !== epoch || sourceMs < hub.source_ms || sourceMs - hub.source_ms > 3500) return;
    const size = hub.image_size || [];
    if (!(size[0] > 0 && size[1] > 0)) return;
    const sx = imageWidth / size[0], sy = imageHeight / size[1];
    context.save();
    context.font = 'bold 12px sans-serif';
    context.lineWidth = 2;
    context.setLineDash([6,4]);
    for (const row of hub.boxes || []) {
      if (!Array.isArray(row.box) || row.box.length !== 4) continue;
      const [x1,y1,x2,y2] = row.box;
      const x=x1*sx,y=y1*sy,w=(x2-x1)*sx,h=(y2-y1)*sy;
      if (![x,y,w,h].every(Number.isFinite) || w <= 0 || h <= 0) continue;
      const unit = row.id.startsWith('hub.marker.');
      if (unit && fastSnapshot?.status === 'observed' &&
          fastSnapshot.epoch === epoch && sourceMs >= fastSnapshot.source_ms &&
          sourceMs-fastSnapshot.source_ms <= 1400) continue;
      context.strokeStyle = unit ? '#cf8bff' : '#62d5e8';
      context.strokeRect(x,y,w,h);
      if (row.label === 'unidade não identificada' ||
          row.label === 'item não identificado') continue;
      context.setLineDash([]);
      const label = unit ? `${row.label} · candidato` : `${row.label} · item?`;
      const labelWidth = Math.min(imageWidth-x,context.measureText(label).width+10);
      context.fillStyle = '#090d16e8';
      context.fillRect(x,Math.max(0,y-19),labelWidth,18);
      context.fillStyle = '#fff';
      context.fillText(label,x+5,Math.max(13,y-5),Math.max(0,labelWidth-10));
      context.setLineDash([6,4]);
    }
    context.restore();
  }
  function renderLiveDiagnostics() {
    const panel = document.querySelector('#live-diagnostic-grid');
    if (!panel) return;
    const scrollPositions = Array.from(panel.children, child => child.scrollTop);
    const read = state?.live_diagnostic;
    const rust = read?.rust || {};
    if (diagnosticMemory.sessionId !== state?.session_id) {
      diagnosticMemory = {sessionId: state?.session_id, hud: new Map(), shop: new Map(), hub: null};
      markerTrails.clear(); fastSnapshot = null; fastFrameId = null; fastEpoch = null;
    }
    const currentMs = Number.isFinite(state?.preview_source_ms) ? state.preview_source_ms : read?.source_ms;
    const recent = entry => entry && entry.epoch === state?.preview_epoch &&
      Number.isFinite(currentMs) && currentMs >= entry.sourceMs && currentMs - entry.sourceMs <= 15000;
    const age = entry => `última leitura há ${((currentMs-entry.sourceMs)/1000).toFixed(1)} s`;
    const hudRows = read?.hud?.length ? read.hud :
      Array.from(diagnosticMemory.hud.keys(), field => ({field, status: 'unavailable'}));
    const hud = hudRows.map(row => {
      const seen = row.value != null && row.status === 'single_frame_observation';
      if (seen) diagnosticMemory.hud.set(row.field, {value: row.value, sourceMs: read.source_ms, epoch: read.epoch});
      const previous = diagnosticMemory.hud.get(row.field);
      const fallback = !seen && recent(previous);
      return `<div class="live-data-row"><span>${escapeHtml(row.field)}</span><b>${escapeHtml(seen ? row.value : fallback ? previous.value : '—')}</b><small>${fallback ? age(previous)+' · não atual' : escapeHtml(row.status || 'sem leitura')}${seen && Number.isFinite(row.confidence) ? ' · '+Math.round(row.confidence*100)+'%' : ''}</small></div>`;
    }).join('');
    const shopRows = read?.shop?.length ? read.shop :
      Array.from({length: 5}, (_, slot) => ({slot, status: 'unavailable'}));
    const shop = shopRows.map(row => {
      const shopAge = Number.isFinite(read?.shop_read_age_ms) ? read.shop_read_age_ms : null;
      const seen = !!row.observed_name && read?.shop_panel_status === 'located' &&
        read?.shop_read_fresh === true &&
        row.status !== 'unknown';
      if (seen) diagnosticMemory.shop.set(row.slot, {name: row.observed_name,
        catalogStatus: row.catalog_status, sourceMs: read.source_ms-(shopAge || 0), epoch: read.epoch});
      const previous = diagnosticMemory.shop.get(row.slot);
      const fallback = !seen && recent(previous);
      const name = seen ? row.observed_name : fallback ? previous.name : 'não identificado';
      const catalog = seen ? row.catalog_status : fallback ? previous.catalogStatus : null;
      const certainty = catalog === 'name_not_in_patch' ? 'OCR fora do catálogo' :
        catalog === 'unique_name_bound' ? 'nome candidato do catálogo' : 'OCR sem confirmação';
      return `<div class="live-data-row"><span>Loja ${Number(row.slot)+1}</span><b>${escapeHtml(name)}</b><small>${fallback ? age(previous)+' · não visível agora' : seen ? certainty+(shopAge ? ' · há '+(shopAge/1000).toFixed(1)+' s' : '') : escapeHtml(row.status || 'sem leitura')}${seen && row.observed_cost != null ? ' · '+escapeHtml(row.observed_cost)+' ouro' : ''}</small></div>`;
    }).join('');
    const currentHub = state?.hub_diagnostic;
    if (currentHub?.boxes?.length) diagnosticMemory.hub = currentHub;
    const hub = currentHub?.boxes?.length ? currentHub :
      recent(diagnosticMemory.hub && {sourceMs: diagnosticMemory.hub.source_ms,
        epoch: diagnosticMemory.hub.epoch}) ? diagnosticMemory.hub : currentHub;
    const hubFromMemory = hub && hub !== currentHub;
    const units = (hub?.boxes || []).filter(row => row.id.startsWith('hub.marker.'));
    const namedUnits = units.filter(row => row.label !== 'unidade não identificada' &&
      row.support_frames >= 2);
    const hubAge = hub && state?.preview_epoch === hub.epoch && Number.isFinite(state?.preview_source_ms)
      ? Math.max(0, state.preview_source_ms - hub.source_ms) : null;
    const hubAgeLabel = hubAge != null && (hubFromMemory || hubAge > 3500)
      ? ` · ${hubFromMemory ? 'última detecção' : 'atrasado'} ${(hubAge/1000).toFixed(1)} s` : '';
    const items = (hub?.boxes || []).filter(row =>
      (row.id.startsWith('hub.inventory.') || row.id.startsWith('hub.equipped.')) &&
      row.label !== 'item não identificado');
    const board = namedUnits.slice(0,12).map(row => `<div class="live-data-row"><span>Peça</span><b>${escapeHtml(row.label)}</b><small>${escapeHtml(row.status || 'candidato')} · ${Number(row.support_frames || 0)} quadros · ${row.identity_verified ? 'verificada' : 'não verificada'}</small></div>`).join('');
    const fast = fastSnapshot || state?.fast_diagnostic;
    const fastAge = fast?.status === 'observed' && fast.epoch === state?.preview_epoch &&
      Number.isFinite(currentMs) ? Math.max(0,currentMs-fast.source_ms) : null;
    const tracks = (fast?.markers || []).slice(0,16).map(marker => {
      const name=candidateForMarker(marker,fast);
      const hp=fast?.player_hp;
      const hpText=marker.color === 'purple' && Number.isInteger(hp?.value)
        ? ` · ${hp.fresh ? 'HP jogador' : 'último HP'} ${hp.value} (há ${(hp.age_ms/1000).toFixed(1)} s)` : '';
      return `<div class="live-data-row"><span>Rastro #${escapeHtml(marker.track_id)}</span><b>${escapeHtml(marker.color === 'purple' ? 'avatar provável' : name || 'nome pendente')}</b><small>barra ${escapeHtml(marker.color)}${escapeHtml(hpText)}${marker.avatar_box ? ' · região do bonequinho estimada' : ''} · vínculo com jogador não confirmado</small></div>`;
    }).join('');
    const playerHp=fast?.player_hp;
    const hpRow=Number.isInteger(playerHp?.value)
      ? `<div class="live-data-row"><span>${playerHp.fresh ? 'HP do jogador' : 'Último HP lido'}</span><b>${escapeHtml(playerHp.value)}</b><small>OCR no quadro ${escapeHtml(playerHp.source_frame_id)} · há ${(playerHp.age_ms/1000).toFixed(1)} s · avatar ainda provável</small></div>`
      : `<div class="live-data-row"><span>HP do jogador</span><b>—</b><small>${escapeHtml(playerHp?.status || 'aguardando leitura')}</small></div>`;
    const inference = hub?.unit_inference || {};
    const inferred = (inference.candidates || []).slice(0,8).map(row =>
      `<div class="live-data-row"><span>Modelo · barra #${escapeHtml(row.marker_id)}</span><b>${escapeHtml(row.candidate_name || row.top_hypothesis_name || 'incerto')}${row.candidate_name ? '' : ' ?'}</b><small>${row.candidate_name ? 'candidato aceito' : 'hipótese rejeitada'} · ${Number.isFinite(row.softmax_score_uncalibrated) ? row.softmax_score_uncalibrated.toFixed(3) : '—'} · score não calibrado · sem confirmação</small></div>`).join('');
    const itemRows = (hub?.item_candidates || []).slice(0,8).map(row =>
      `<div class="live-data-row"><span>${row.zone === 'equipped' ? 'Equipado' : 'Banco'}</span><b>${escapeHtml((row.names || []).join(' / ') || 'identidade incerta')}</b><small>${escapeHtml(row.status)} · similaridade ${Number.isFinite(row.similarity) ? row.similarity.toFixed(2) : '—'} · não confirmado</small></div>`).join('') ||
      items.slice(0,8).map(row => `<div class="live-data-row"><span>Item</span><b>${escapeHtml(row.label)}</b><small>${escapeHtml(row.status || 'candidato')} · não confirmado</small></div>`).join('');
    const opponents = (state?.opponents?.players || []).filter(row => row.name).slice(0,7).map(row =>
      `<div class="live-data-row"><span>Rival</span><b>${escapeHtml(row.name)}</b><small>${row.hp == null ? 'vida sem leitura' : 'vida '+escapeHtml(row.hp)}</small></div>`).join('');
    const ranked = (rust.ranked || []).map(row => `<div class="live-rank-row ${row.selected?'selected':''}"><span>${escapeHtml(row.action || 'ação')} ${escapeHtml(row.target || '')}</span><strong>${Number.isFinite(row.utility) ? row.utility.toFixed(3) : '—'}</strong><small>base ${Number.isFinite(row.base_utility) ? row.base_utility.toFixed(3) : '—'} · repetição −${Number.isFinite(row.novelty_penalty) ? row.novelty_penalty.toFixed(3) : '—'} · persistência +${Number.isFinite(row.persistence_bonus) ? row.persistence_bonus.toFixed(3) : '—'}</small></div>`).join('');
    const tip = state?.tip;
    const freshTip = tip?.actionable && Number.isFinite(tip.age_ms) && tip.age_ms <= 5000;
    panel.innerHTML = `<section class="live-data-panel"><h3>Leituras da imagem <small>quadro ${escapeHtml(read?.frame_id ?? '—')} · ${read ? (read.source_ms/1000).toFixed(1)+' s' : 'aguardando'}</small></h3>${hud || '<p>Aguardando primeira leitura.</p>'}<h4>Loja</h4>${shop || '<p>Nomes ainda não lidos.</p>'}<h4>Rastros rápidos · ${fast?.markers?.length || 0} barras${fastAge == null ? '' : ' · '+(fastAge/1000).toFixed(1)+' s'}</h4>${hpRow}${tracks || '<p>Sem barra localizada. Avatar e lado do jogador ainda sem confirmação.</p>'}<h4>Tabuleiro e banco · ${namedUnits.length}/${units.length} nomes candidatos${hubAgeLabel}</h4>${board || '<p>Regiões detectadas, sem nome sustentado neste quadro.</p>'}<h4>Reconhecimento de campeões</h4>${inferred || '<p>Modelo processando ou sem candidato neste quadro.</p>'}<h4>Itens</h4>${itemRows || '<p>Nenhum item nomeado neste quadro.</p>'}<h4>Adversários</h4>${opponents || '<p>Nomes ainda não lidos.</p>'}<p class="live-footnote">Rastros acompanham barras visíveis; cor não prova se a unidade é sua ou do adversário. Nomes são candidatos, não rótulos de treino.</p></section>`+
      `<section class="live-math-panel"><h3>Cálculo Rust <small>${escapeHtml(rust.status || 'aguardando')}</small></h3><p>HUD ${Number.isFinite(read?.reader_ms) ? read.reader_ms.toFixed(0)+' ms' : '—'} · tabuleiro ${Number.isFinite(hub?.processing_ms) ? hub.processing_ms.toFixed(0)+' ms' : '—'} · motor ${Number.isFinite(rust.native_ms) ? rust.native_ms.toFixed(0)+' ms' : '—'}</p>${ranked || '<p>Sem alternativas calculadas neste quadro.</p>'}<p class="live-footnote">${Number.isFinite(hub?.worker_ms) ? 'Barras '+hub.worker_ms.toFixed(0)+' ms · ' : ''}${Number.isFinite(hub?.diagnostic_timings_ms?.snapshot_ms) ? 'base visual '+hub.diagnostic_timings_ms.snapshot_ms.toFixed(0)+' ms · ' : ''}${Number.isFinite(hub?.diagnostic_timings_ms?.unit_neural_ms) ? 'nomes '+hub.diagnostic_timings_ms.unit_neural_ms.toFixed(0)+' ms · ' : ''}${Number.isFinite(hub?.diagnostic_timings_ms?.item_visual_native_ms) ? 'itens '+hub.diagnostic_timings_ms.item_visual_native_ms.toFixed(0)+' ms. ' : ''}Pontuação relativa, não probabilidade de vitória.${rust.reason ? ' Motivo: '+escapeHtml(rust.reason) : ''}</p></section>`+
      `<section class="live-moves-panel"><h3>Jogada indicada <small>${freshTip?'agora':'sem nova dica'}</small></h3><strong>${escapeHtml(freshTip ? tip.text : 'Aguardando uma ação sustentada pela leitura.')}</strong><p>${freshTip ? 'Momento '+(tip.source_ms/1000).toFixed(1)+' s · '+escapeHtml(tip.action_type || 'ação') : 'A leitura continua mesmo quando o motor não recomenda agir.'}</p><h4>Alternativas avaliadas</h4>${ranked ? (rust.ranked || []).slice(0,3).map(row => `<div class="live-move-row">${escapeHtml(row.action || 'ação')} ${escapeHtml(row.target || '')} <b>${Number.isFinite(row.utility) ? row.utility.toFixed(3) : '—'}</b></div>`).join('') : '<p>Nenhuma ainda.</p>'}</section>`;
    Array.from(panel.children, (child, index) => { child.scrollTop = scrollPositions[index] || 0; });
  }
  function startPreview() {
    ++previewGeneration;
    if (previewRequest) previewRequest.abort();
    previewDrawTimes.length = 0;
    const canvas = document.querySelector('#live-preview-canvas');
    if (!canvas) return;
    const generation = previewGeneration;
    const context = canvas.getContext('2d', {alpha: false, desynchronized: true});
    if (!context) return;
    let after = 0, errors = 0;
    (async () => {
      while (generation === previewGeneration && canvas.isConnected) {
        const request = new AbortController();
        previewRequest = request;
        try {
          const response = await fetch(new URL('frame.jpg?after=' + after, location.href),
            {cache: 'no-store', signal: request.signal});
          if (response.status === 204) continue;
          if (!response.ok) throw new Error('Prévia indisponível.');
          const sequence = Number(response.headers.get('X-Frame-Sequence'));
          const sourceMs = Number(response.headers.get('X-Source-Ms'));
          const epoch = Number(response.headers.get('X-Source-Epoch'));
          if (!Number.isSafeInteger(sequence) || sequence <= after) throw new Error('Quadro inválido.');
          const bitmap = await createImageBitmap(await response.blob());
          try {
            if (generation !== previewGeneration || !canvas.isConnected) break;
            if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
              canvas.width = bitmap.width;
              canvas.height = bitmap.height;
            }
            context.drawImage(bitmap, 0, 0);
            drawObservedBoxes(context, bitmap.width, bitmap.height, sourceMs, epoch);
            drawHubBoxes(context, bitmap.width, bitmap.height, sourceMs, epoch);
            drawFastTracks(context, bitmap.width, bitmap.height, sourceMs, epoch);
            const empty = canvas.parentElement.querySelector('.live-preview-empty');
            if (empty) empty.hidden = true;
            const drawnAt = performance.now();
            previewDrawTimes.push(drawnAt);
            while (previewDrawTimes.length && previewDrawTimes[0] < drawnAt - 1000)
              previewDrawTimes.shift();
            after = sequence;
            errors = 0;
          } finally { bitmap.close(); }
        } catch (error) {
          if (request.signal.aborted) break;
          ++errors;
          await new Promise(resolve => setTimeout(resolve, Math.min(1000, errors * 100)));
        } finally {
          if (previewRequest === request) previewRequest = null;
        }
      }
    })();
  }
  const regions = ['BR','NA','LAN','LAS','EUW','EUNE','KR','JP','OCE','TR','RU','SEA','TW','VN'];
  async function loadSources(dialog) {
    const revision = ++sourceLoadRevision;
    const preferredLabel = selected?.label || state?.source_label;
    sourceRows = [];
    selected = null;
    const options = dialog.querySelector('.source-options');
    const confirm = dialog.querySelector('#confirm-source');
    const message = dialog.querySelector('#source-message');
    options.innerHTML = '<div class="source-wait">Buscando monitores e janelas…</div>';
    message.textContent = '';
    message.hidden = true;
    confirm.disabled = true;
    try {
      const rows = await api().list_sources();
      if (revision !== sourceLoadRevision) return;
      if (!Array.isArray(rows)) throw new Error('O capturador retornou uma lista inválida.');
      const chosenIndex = Math.max(0, rows.findIndex(row => row.label === preferredLabel));
      sourceRows = rows;
      options.innerHTML = rows.length ? rows.map((row, index) =>
        `<button class="source-option ${index===chosenIndex?'selected':''}" data-source-index="${index}" aria-pressed="${index===chosenIndex}">`+
        `<span data-icon="${row.kind==='monitor'?'monitor':'window'}"></span><b>${escapeHtml(row.label)}</b>`+
        `<small>${row.candidate_tft?'Possível janela TFT':'Fonte disponível'}</small><i>✓</i></button>`).join('') :
        '<div class="source-wait">Nenhum monitor ou janela disponível nesta sessão do Windows.</div>';
      selected = rows[chosenIndex] || null;
      confirm.disabled = !selected;
      hydrate();
    } catch (error) {
      if (revision !== sourceLoadRevision) return;
      options.innerHTML = '';
      message.textContent = 'Não foi possível listar as telas: '+clean(error);
      message.hidden = false;
    }
  }
  function profileForm(profile) {
    return `<span class="eyebrow">SEU PERFIL LOCAL</span><h2>Bem-vindo ao Agente TFT</h2>`+
      `<p>Coloque seu nick e região para começar. Nenhum login na Riot é necessário.</p>`+
      `<div class="studio-profile-form"><label>Nick ou nome#tag<input id="studio-nickname" maxlength="80" value="${escapeHtml(profile?.nickname||'')}" placeholder="Seu nick"></label>`+
      `<label>Região<select id="studio-region">${regions.map(x=>`<option value="${x}" ${x===(profile?.region||'BR')?'selected':''}>${x}</option>`).join('')}</select></label>`+
      `<button class="primary" id="studio-profile-save">Salvar perfil</button></div>`+
      `<p class="note">O perfil é informado por você e salvo neste computador.</p>`;
  }

  function connectedCoach() {
    const tip = state && state.tip;
    const card = document.querySelector('.advice-card');
    if (!card) return;
    const actionable = !!(tip && tip.actionable && (tip.age_ms == null || tip.age_ms <= 5000));
    const combat = !!(tip && tip.kind === 'combat' && tip.speakable &&
      (tip.age_ms == null || tip.age_ms <= 8000));
    const previous = !actionable && !combat ? state?.history?.[0] : null;
    const label = actionable ? 'DICA AGORA' : combat ? 'COMBATE' :
      previous ? 'ÚLTIMA DICA' : 'LEITURA EM ANDAMENTO';
    document.querySelector('.coach-label').innerHTML =
      `<span>${previous ? 'SESSÃO' : 'AGORA'}</span><span class="pill mini">${label}</span>`;
    const title = actionable || combat ? tip.text : previous ? previous.text :
      state?.ubuntu_mvp && tip?.text ? 'Sem recomendação agora.' :
      state?.screen_mode === 'gameplay_hud' ? 'Tabuleiro visível. Buscando a próxima ação.' :
      state?.screen_mode === 'stage_without_economy' ? 'Partida detectada. Aguardando a loja e o ouro.' :
      state?.screen_mode === 'no_gameplay_hud' ? 'Aguardando o tabuleiro do TFT na tela selecionada.' :
      'Aguardando a primeira imagem da captura.';
    const recommendations = actionable ? (tip.recommendations || []) : [];
    const decisionInfo = state?.decision_status === 'held_duplicate' ?
      'O motor já mostrou essa ação e aguarda uma mudança na partida.' :
      state?.decision_status === 'abstained' ?
      'O motor não encontrou uma ação sustentada pelas leituras atuais.' : '';
    const canRate = actionable && tip.policy === 'partial_state_live_v1' &&
      tip.decision_key && !ratedTips.has(tip.decision_key);
    card.innerHTML = `<div class="advice-type">${icon(actionable?'growth':'eye')} ${label}</div>`+
      `<h2>${escapeHtml(title)}</h2>`+
      `<p>${actionable ? 'Decisão baseada na observação recente da sua tela.' :
                     combat ? 'Comentário após a mudança observada de vida na luta.' :
                     previous ? 'Dica anterior da sessão. A próxima orientação aparecerá quando houver nova evidência.' :
                     tip?.text ? escapeHtml(tip.text) :
                     state?.ubuntu_mvp ? 'Diagnóstico do mesmo motor usado no Windows.' :
                     'As ações aparecem aqui durante a partida.'}</p>`+
      `<div class="advice-explanation" style="display:block">`+
      `Patch dos dados: ${escapeHtml((actionable || combat ? tip : previous)?.data_patch || tip?.data_patch || 'a confirmar')}`+
      `${tip && tip.data_patch_basis==='bundled_catalog_patch_lab' ? ' (catálogo local de laboratório)' : ''} · `+
      `${previous ? 'Momento da dica: '+Math.round((previous.source_ms || 0)/1000)+' s' :
        'Idade da leitura: '+(tip && Number.isFinite(tip.age_ms) ? Math.round(tip.age_ms)+' ms' : '—')}`+
      `${previous && tip && !tip.actionable && tip.text ? '<br>Leitura atual: '+escapeHtml(tip.text) : ''}`+
      `${!actionable && decisionInfo ? '<br>'+escapeHtml(decisionInfo) : ''}`+
      `${state?.ubuntu_mvp ? '<br>HUD: '+escapeHtml((state.hud_diagnostic?.fields||[]).map(x =>
        `${x.field}=${x.value ?? '—'} (${x.cache_delivery ?
          `RAM${Number.isFinite(x.cache_delivery.last_ocr_age_ms) ? ' '+Math.round(x.cache_delivery.last_ocr_age_ms)+' ms' : ''}` :
          (x.status || 'sem leitura')})`).join(' · ') || 'sem leitura')+
        ' · decisão: '+escapeHtml(state.hud_diagnostic?.decision_reason || 'nenhuma') : ''}`+
      `${recommendations.length ? '<br>'+recommendations.map(x => escapeHtml(x.text)).join('<br>') : ''}`+
      `</div>`+
      (canRate ? '<div class="tip-feedback"><span>Esta dica ajudou?</span><button type="button" data-tip-feedback="yes">Sim</button><button type="button" data-tip-feedback="no">Não</button></div>' : '');
    document.querySelector('.coach-footnote').textContent =
      state && state.error ? 'Erro: '+state.error :
      state && state.session_id ? 'Sessão '+state.session_id.slice(0,8)+' · '+state.phase :
      'Escolha a tela para iniciar a captura local.';
    const voice = state && state.voice;
    document.querySelector('#voice-label').textContent =
      voice && voice.paused ? 'Voz pausada' : voice && voice.error ? 'Voz indisponível' : voice && voice.enabled ?
      'ElevenLabs · voz conectada' : 'Voz aguardando conexão';
    document.querySelector('.voice-strip small').textContent = voice?.paused ? 'Dicas somente em texto' : 'ElevenLabs · português BR';
    document.querySelector('#play-voice').setAttribute('aria-label', 'Estado da voz');
    const audio = document.querySelector('#voice-audio');
    if (audio) audio.removeAttribute('src');
    const strip = document.querySelector('.voice-strip');
    if (strip) {
      strip.style.display = voice?.paused ? 'none' : '';
      let highlights = document.querySelector('#coach-highlights');
      if (!highlights) {
        highlights = document.createElement('div');
        highlights.id = 'coach-highlights';
        highlights.className = 'coach-highlights';
        strip.insertAdjacentElement('afterend', highlights);
      }
      const result = state?.highlights;
      highlights.innerHTML = result?.status === 'complete' ?
        `<a href="${new URL('highlights.mp4', location.href).href}" download="melhores-momentos-agente-tft.mp4">Baixar melhores momentos com a voz do coach ↗</a>` :
        result?.status === 'rendering' ? 'Montando os melhores momentos com voz…' :
        result?.status === 'recording' ? `Falas gravadas: ${Number(result.clips || 0)}` :
        result?.status === 'no_spoken_tips' ? 'Nenhuma fala do coach foi reproduzida nesta sessão.' :
        result?.status === 'error' ? 'Não foi possível montar o vídeo desta sessão.' : '';
    }
  }

  function connectedPage() {
    const presentation = document.querySelector('.presentation-bar');
    if (presentation) presentation.style.display = 'none';
    const footer = document.querySelector('.presentation-footer');
    if (footer) footer.style.display = 'none';
    document.querySelector('.sidebar-footer').innerHTML = '<span class="status-dot"></span> APLICATIVO LOCAL <span>01.0</span>';
    document.querySelector('.statusbar>span').innerHTML =
      '<span class="status-dot"></span> CAPTURA LOCAL <i>·</i> '+
      (state?.visual_model_loaded ? 'VISÃO NEURAL DIAGNÓSTICA' : 'LEITURA NATIVA')+
      ' <i>·</i> '+(state?.tip?.learned_ranker ? 'DICA NEURAL APLICADA' :
        state?.strategic_model_loaded ? 'MODELO NEURAL CARREGADO · DICAS POR REGRAS' :
        'ESTRATÉGIA POR REGRAS');
    document.querySelector('#footer-context').textContent =
      state && state.session_id ? `Quadros ${state.counts?.source_frames || 0} · HUB ${state.counts?.hub_results || 0} · dicas ${state.counts?.replay_tips || 0}` :
      'Captura Rust · análise local · aprendizado pós partida';
    document.querySelector('.workspace-pill').innerHTML =
      '<span class="status-dot"></span> '+(state?.replay_review ? 'Revisão de replay':'Estúdio ao vivo')+
      ' <span class="dim">/</span> <b>Laboratório</b>';
    const installerLink = document.querySelector('.sidebar-bottom button[data-route="installer"]');
    if (installerLink) installerLink.style.display = 'none';
    if (current === 'studio') {
      // Design samples must not look like observed champions in the live view.
      for (const node of document.querySelectorAll('#main > .page-enter > .section-title, #main > .page-enter > .roster, #main > .page-enter > .insight-strip'))
        node.style.display = 'none';
      const arena = document.querySelector('.panel .arena');
      if (arena) arena.outerHTML = `<div class="live-preview">${state && state.preview_sequence > 0 ?
        `<canvas id="live-preview-canvas" width="1280" height="720" role="img" aria-label="Prévia da fonte selecionada"></canvas>` : ''}`+
        `<div class="live-preview-empty">${state && state.session_id ? 'Aguardando o primeiro quadro da captura…' : 'Selecione um monitor ou janela para acompanhar.'}</div></div>`;
      const previewPanel = document.querySelector('.live-preview')?.closest('.panel');
      if (previewPanel) {
        const layout = document.createElement('div');
        layout.className = 'live-inspection-layout';
        previewPanel.parentNode.insertBefore(layout, previewPanel);
        layout.appendChild(previewPanel);
        layout.insertAdjacentHTML('beforeend', '<div id="live-diagnostic-grid" class="live-diagnostic-grid"></div>');
      }
      renderLiveDiagnostics();
      const status = document.querySelector('.capture-controls small');
      if (status) status.textContent = state && state.session_id ?
        `Captura ${state.phase} · prévia local até 720p` : 'Captura ainda não iniciada';
      const play = document.querySelector('#preview-play');
      if (play) {
        play.innerHTML = icon(state && state.session_id ? 'pause':'play');
        play.setAttribute('aria-label', state && state.session_id ? 'Encerrar sessão':'Escolher fonte para iniciar');
      }
      const source = document.querySelector('#source-name');
      if (source) source.textContent = state?.session_id ?
        (state.source_label || 'Fonte em uso') :
        (selected?.label || 'Nenhuma fonte selecionada');
    }
    if (current === 'board') {
      const arena = document.querySelector('.board-detail .arena, .board-detail .live-board-empty');
      const readiness = state?.visual_readiness;
      const candidates = state?.temporal_candidates || {};
      const units = (candidates.units || []).filter(row => row.candidate_id).slice(0, 10);
      const items = (candidates.inventory || []).filter(row => row.candidate_id).slice(0, 10);
      const equipped = (candidates.equipped || []).filter(row => row.candidate_id).slice(0, 10);
      const boardStatus = readiness ?
        `${readiness.observed_unit_regions || 0} regiões observadas · ${readiness.candidate_units || 0} candidatos · ${readiness.verified_units || 0} unidades confirmadas` :
        'Aguardando a primeira leitura do tabuleiro.';
      const modelStatus = state?.unit_model_active ? 'Reconhecedor de campeões ativo' : 'Reconhecedor de campeões aguardando modelo';
      const unitText = units.length ? '<br>Possíveis campeões: '+units.map(row =>
        escapeHtml(row.candidate_name || row.candidate_id)).join(', ') : '';
      const equipmentText = equipped.length ? '<br>Itens equipados observados: '+equipped.map(row => {
        const place = row.position || [];
        const location = place[0] === 'board' && Number.isInteger(place[1]) && Number.isInteger(place[2]) ?
          ` (linha ${place[1]+1}, casa ${place[2]+1} aproximada)` : '';
        return escapeHtml(row.candidate_name || row.candidate_id)+escapeHtml(location);
      }).join(', ') : '';
      if (arena) arena.outerHTML = `<div class="live-board-empty"><div>Leitura do tabuleiro em andamento.${unitText}${equipmentText}<br><small>${escapeHtml(boardStatus)} · ${escapeHtml(modelStatus)} · nomes ainda não confirmados</small></div></div>`;
      const inventory = document.querySelector('.board-detail .inventory');
      if (inventory) inventory.innerHTML = '<span>Inventário · '+(items.length ?
        'possíveis itens: '+items.map(row => escapeHtml(row.candidate_name || row.candidate_id)).join(', ') :
        'aguardando leitura')+' · candidatos</span>';
      const boardPanel = document.querySelector('.board-detail');
      let opponentPanel = document.querySelector('.live-opponents');
      if (boardPanel && !opponentPanel) {
        opponentPanel = document.createElement('section');
        opponentPanel.className = 'panel live-opponents';
        boardPanel.insertAdjacentElement('afterend', opponentPanel);
      }
      if (opponentPanel) {
        const opponentState = state?.opponents || {};
        const rows = (opponentState.players || []).filter(row => row.name).slice(0, 7);
        opponentPanel.innerHTML = `<div class="panel-top"><span class="panel-title">Adversários observados</span>`+
          `<span class="pill">${rows.length} nomes</span></div>`+
          (rows.length ? `<div class="opponent-rows">${rows.map(row =>
            `<div class="opponent-row"><b>${escapeHtml(row.name)}</b>`+
            `<span>${row.status === 'stale_roster' ? 'Lista anterior · vida sem leitura atual' :
              row.hp == null ? 'Vida —' : 'Vida '+escapeHtml(row.hp)}`+
            `${row.losses_observed ? ' · derrotas contra ele '+escapeHtml(row.losses_observed) : ''}</span></div>`
          ).join('')}</div>` : '<p class="note">Aguardando a lista de jogadores aparecer no vídeo.</p>')+
          `<p class="opponent-note">${opponentState.current_opponent ?
            'Confronto observado: '+escapeHtml(opponentState.current_opponent)+'. ' : ''}`+
          `Composições dos adversários entram quando o tabuleiro de cada um for associado com segurança.</p>`;
      }
    }
    if (current === 'history') {
      const panelTitle = document.querySelector('.timeline')?.closest('.panel')?.querySelector('.panel-title');
      if (panelTitle) panelTitle.innerHTML = `${icon('history')} Dicas da sessão atual`;
      const rows = state?.history || [];
      const timeline = document.querySelector('.timeline');
      if (timeline) timeline.innerHTML = rows.length ? rows.map(row =>
        `<article class="timeline-entry"><span class="time">${Math.round((row.source_ms||0)/1000)}s · `+
        `PATCH ${escapeHtml(row.data_patch||'a confirmar')}</span><h3>${escapeHtml(row.text)}</h3>`+
        `<p>${(row.recommendations||[]).map(x=>escapeHtml(x.text)).join(' · ') || 'Dica registrada durante a captura.'}</p></article>`
      ).join('') : '<article class="timeline-entry"><h3>Nenhuma dica registrada nesta sessão.</h3><p>As decisões aparecerão aqui conforme forem confirmadas.</p></article>';
      const pill = document.querySelector('.page-head .pill');
      if (pill) pill.textContent = 'DADOS DA SESSÃO';
    }
    if (current === 'learning') {
      const grid = document.querySelector('.metric-grid');
      if (grid) grid.innerHTML =
        `<div class="metric"><span>Quadros recebidos</span><strong>${state?.counts?.source_frames||0}</strong><small>Captura desta sessão</small></div>`+
        `<div class="metric"><span>Leituras do tabuleiro</span><strong>${state?.counts?.hub_results||0}</strong><small>Não equivalem a rótulos verificados</small></div>`+
        `<div class="metric"><span>Dicas emitidas</span><strong>${state?.counts?.replay_tips||0}</strong><small>Orientações registradas</small></div>`;
      const table = document.querySelector('.table-panel');
      if (table) table.innerHTML = '<div class="small-heading"><h2>Aprendizado pós partida</h2></div>'+
        `<p>${escapeHtml(state?.result?.post_session_learning_job?.status ||
        'Aguardando encerramento e validação da captura para enviar ao BigBANANA.')}</p>`+
        `<p>Modelo local: ${escapeHtml(state?.model_update?.status || 'verificação ainda não concluída')}`+
        `${state?.model_update?.generation ? ` · geração ${Number(state.model_update.generation)}` : ''}</p>`+
        '<p><a href="https://tft.bigbanana.io/" target="_blank" rel="noreferrer">Abrir painel do servidor ↗</a></p>';
    }
    if (current === 'simulator') {
      const table = document.querySelector('.table-panel');
      if (table) table.innerHTML = '<div class="small-heading"><h2>Simulações no BigBANANA</h2></div>'+
        '<p>As execuções do servidor são acompanhadas no painel próprio. Este aplicativo registra a sessão e recebe os modelos aprovados após a partida.</p>'+
        '<p><a href="https://tft.bigbanana.io/" target="_blank" rel="noreferrer">Abrir painel do servidor ↗</a></p>';
    }
    if (current === 'settings') {
      document.querySelector('.page-head')?.insertAdjacentHTML('afterend',
        `<section class="panel settings-block">${profileForm(state?.profile)}</section>`);
      const rows = document.querySelectorAll('.settings-row');
      const description = rows[2]?.querySelector('p');
      if (rows[2]) rows[2].style.display = state?.voice?.paused ? 'none' : '';
      if (description) description.textContent = 'Dicas atuais por ElevenLabs, reproduzidas no Windows.';
    }
    connectedCoach();
    startPreview();
  }

  render = function(route) { originalRender(route); connectedPage(); };
  render(current);

  async function refresh() {
    if (!api()) return;
    try {
      const next = await api().state();
      if (state && state.session_id !== next.session_id) ratedTips.clear();
      // A new tip only repaints the coach. Reloading the page's <img> on every
      // observation would tear down the MJPEG stream and cause visible stalls.
      const changed = !state || state.session_id !== next.session_id ||
        state.phase !== next.phase || state.error !== next.error ||
        ((state.preview_sequence || 0) === 0 && next.preview_sequence > 0) ||
        (current === 'board' && (JSON.stringify(state.visual_readiness) !== JSON.stringify(next.visual_readiness) ||
          JSON.stringify(state.temporal_candidates) !== JSON.stringify(next.temporal_candidates))) ||
        (current === 'history' && (state.history?.length || 0) !== (next.history?.length || 0)) ||
        (current === 'learning' && JSON.stringify(state.counts) !== JSON.stringify(next.counts));
      state = next;
      if (changed) render(current);
      else {
        connectedCoach();
        if (current === 'studio') renderLiveDiagnostics();
        const now = performance.now();
        while (previewDrawTimes.length && previewDrawTimes[0] < now - 1000)
          previewDrawTimes.shift();
        const status = document.querySelector('.capture-controls small');
        if (status && state.session_id) status.textContent =
          `Captura ${state.phase} · prévia exibida ${previewDrawTimes.length} FPS · HUB ${state.counts?.hub_results || 0}`;
      }
      if (!state.profile && !profilePrompted) {
        profilePrompted = true;
        document.querySelector('#detail-content').innerHTML = profileForm(null);
        document.querySelector('#detail-dialog').showModal();
      }
    } catch (error) { toast('Não foi possível consultar o motor local: '+clean(error)); }
  }
  setInterval(refresh, 900);
  async function refreshFastMarkers() {
    if (fastRequestBusy || current !== 'studio' || !state?.session_id) return;
    fastRequestBusy = true;
    try {
      const next = await api().fast_diagnostic();
      if (!next || next.status !== 'observed') {
        fastSnapshot = next;
        return;
      }
      if (fastEpoch !== next.epoch || (fastSnapshot && next.source_ms < fastSnapshot.source_ms)) {
        markerTrails.clear();
        fastFrameId = null;
      }
      fastEpoch = next.epoch;
      if (fastFrameId !== next.frame_id) {
        fastFrameId = next.frame_id;
        for (const marker of next.markers || []) {
          const box = marker.box;
          if (!Array.isArray(box) || box.length !== 4) continue;
          const trail = markerTrails.get(marker.track_id) || [];
          trail.push({x:(box[0]+box[2])/2,y:(box[1]+box[3])/2,ms:next.source_ms});
          markerTrails.set(marker.track_id,trail.filter(point =>
            next.source_ms-point.ms <= 1500).slice(-10));
        }
        for (const [id,trail] of markerTrails) {
          if (!trail.length || next.source_ms-trail.at(-1).ms > 1500) markerTrails.delete(id);
        }
      }
      fastSnapshot = next;
    } catch (_error) {
      // The main state panel reports capture errors; this optional overlay may lag.
    } finally {
      fastRequestBusy = false;
    }
  }
  setInterval(refreshFastMarkers, 220);
  refresh();

  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.tipFeedback) {
      event.stopImmediatePropagation();
      if (!state?.tip?.decision_key) return;
      const key = state.tip.decision_key;
      const result = await api().rate_tip(key,
        button.dataset.tipFeedback === 'yes');
      if (result.accepted) {
        ratedTips.add(key);
        button.closest('.tip-feedback')?.remove();
        toast('Obrigado. Seu feedback ajusta a prioridade das próximas dicas.');
      } else toast('Esta dica já mudou ou o feedback foi registrado.');
      return;
    }
    if (button.id === 'choose-source') {
      event.stopImmediatePropagation();
      const dialog = document.querySelector('#source-dialog');
      dialog.querySelector('p').textContent =
        'Ao iniciar, você autoriza a captura local desta fonte. Partidas ao vivo podem ser enviadas para aprendizado após o encerramento; replays não são enviados.';
      let replayChoice = dialog.querySelector('#studio-replay-choice');
      if (!replayChoice) {
        replayChoice = document.createElement('label');
        replayChoice.id = 'studio-replay-choice';
        replayChoice.className = 'studio-replay-choice';
        replayChoice.innerHTML = '<input type="checkbox" id="studio-replay-mode"> Estou assistindo um replay já encerrado';
        dialog.querySelector('.source-info').after(replayChoice);
      }
      dialog.querySelector('#confirm-source').innerHTML = 'Iniciar captura <span>→</span>';
      hydrate();
      dialog.showModal();
      await loadSources(dialog);
      return;
    }
    if (button.id === 'retry-sources') {
      event.stopImmediatePropagation();
      await loadSources(document.querySelector('#source-dialog'));
      return;
    }
    if (button.dataset.sourceIndex != null) {
      event.stopImmediatePropagation();
      selected = sourceRows[Number(button.dataset.sourceIndex)];
      document.querySelectorAll('#source-dialog .source-option').forEach(el => {
        el.classList.toggle('selected', el===button);
        el.setAttribute('aria-pressed', String(el===button));
      });
      return;
    }
    if (button.id === 'confirm-source') {
      event.stopImmediatePropagation();
      if (!selected || starting) return;
      starting = true;
      try {
        const replayReview = !!document.querySelector('#studio-replay-mode')?.checked;
        await api().start_session(selected.kind, selected.id, replayReview, true);
        document.querySelector('#source-dialog').close();
        toast(replayReview ? 'Revisão iniciada. O replay não será usado para aprendizado.' :
          'Captura local iniciada. O aprendizado será enviado após a partida.');
        await refresh();
      } catch (error) {
        const message = document.querySelector('#source-message');
        message.textContent = 'Captura não iniciada: '+clean(error);
        message.hidden = false;
      }
      finally { starting = false; }
      return;
    }
    if (button.id === 'preview-play') {
      event.stopImmediatePropagation();
      if (state && state.session_id && state.phase !== 'finished') {
        await api().stop_session(); toast('Encerrando e salvando a sessão…');
      } else document.querySelector('#choose-source')?.click();
      return;
    }
    if (button.id === 'play-voice' || button.id === 'history-voice') {
      event.stopImmediatePropagation();
      toast(state?.voice?.paused ? 'Voz pausada; acompanhe as dicas em texto.' :
        state?.voice?.error || 'A voz narra apenas dicas atuais confirmadas.');
      return;
    }
    if (button.dataset.pref === 'voice') {
      event.stopImmediatePropagation();
      const enabled = button.getAttribute('aria-checked') !== 'true';
      const response = await api().set_voice(enabled);
      preferences.voice = response.enabled;
      button.setAttribute('aria-checked', String(response.enabled));
      toast(response.paused ? 'Voz pausada; acompanhe as dicas em texto.' :
        response.enabled ? 'Voz ativada.' : 'Voz desativada.');
      return;
    }
    if (button.id === 'studio-profile-save') {
      event.stopImmediatePropagation();
      try {
        const form = button.closest('.studio-profile-form');
        const profile = await api().save_profile(
          form.querySelector('#studio-nickname').value,
          form.querySelector('#studio-region').value);
        state = {...state, profile};
        const dialog = document.querySelector('#detail-dialog');
        if (dialog.open) dialog.close();
        render(current);
        toast('Perfil salvo neste computador.');
      } catch(error) { toast(clean(error)); }
    }
  }, true);
}
