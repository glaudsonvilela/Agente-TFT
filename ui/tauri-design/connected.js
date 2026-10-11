'use strict';
// Runs only in the installed local studio. The design preview remains
// independently navigable and keeps its illustrative labels.
if (new URLSearchParams(location.search).has('connected')) {
  document.body.classList.add('connected-app');
  const originalRender = render;
  let sourceRows = [], selected = null, state = null, starting = false, profilePrompted = false, sourceLoadRevision = 0;
  const ratedTips = new Set();
  let terminalMode = true;
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
  const FAST_ITEM_MAX_LAG_MS = 1250;
  let displayedSourceMs = null;
  function fastItemsForFrame(frameSourceMs) {
    const history = state?.fast_items_history || [];
    for (let index = history.length - 1; index >= 0; --index) {
      const reading = history[index];
      const lag = frameSourceMs - reading?.source_ms;
      if (reading?.status === 'observed' && Number.isFinite(lag) &&
          lag >= 0 && lag <= FAST_ITEM_MAX_LAG_MS) return reading;
    }
    return null;
  }
  function drawSpatialLayer(context, canvas, frameSourceMs, sx, sy) {
    const spatial = state?.spatial_map;
    const spatialAge = frameSourceMs - spatial?.source_ms;
    if (!Number.isFinite(spatialAge) || spatialAge < 0 || spatialAge > 3000) return;
    const circle = (point, color, label, bench=false) => {
      if (!Array.isArray(point.center)) return;
      const x = point.center[0] * sx, y = point.center[1] * sy;
      context.strokeStyle = color;
      context.lineWidth = Math.max(1, canvas.width / 900);
      context.beginPath();
      context.arc(x, y, Math.max(5, canvas.width / 130), 0, Math.PI * 2);
      context.stroke();
      context.fillStyle = color;
      context.fillText(label, x + 7, y + (bench ? 18 : -5));
    };
    if (['reference_candidate', 'arena_candidate', 'standard_screen_geometry'].includes(spatial.own_geometry_status)) {
      for (const point of spatial.own_cells || []) {
        circle(point, '#74d8ff', `P${point.id}${point.champion_id ? ' '+point.champion_id : ''}`);
      }
    }
    if (['arena_candidate', 'standard_screen_geometry'].includes(spatial.enemy_geometry_status)) {
      for (const point of spatial.enemy_cells || []) {
        circle(point, '#ff8068', `E${point.id}${point.champion_id ? ' '+point.champion_id : ''}`);
      }
    }
    if (spatial.own_bench_geometry_status !== 'not_calibrated') {
      for (const point of spatial.own_bench || []) circle(point, '#ffda80', 'P'+point.id, true);
    }
    if (['arena_candidate', 'standard_screen_geometry'].includes(spatial.enemy_bench_geometry_status)) {
      const fast = state?.fast_diagnostic;
      const lag = frameSourceMs - fast?.source_ms;
      const upperBars = fast?.status === 'observed' && Number.isFinite(lag) && lag >= 0 && lag <= 900 ?
        (fast.markers || []).filter(row => row.color === 'red' &&
          row.scan_zone === 'upper_reserve' && Array.isArray(row.box)) : [];
      for (const point of spatial.enemy_bench || []) {
        circle(point, '#ffb0a0', 'E'+point.id, true);
        const anchored = Array.isArray(point.center) && upperBars.find(row => {
          const barX = (row.box[0] + row.box[2]) / 2;
          return Math.abs(barX - point.center[0]) <= 44 &&
            Math.abs(row.box[1] - point.center[1]) <= 60;
        });
        if (anchored) {
          const x = point.center[0] * sx, y = point.center[1] * sy;
          context.strokeStyle = '#ff597d';
          context.lineWidth = Math.max(2, canvas.width / 450);
          context.setLineDash([5, 3]);
          context.strokeRect(x - 30 * sx, y - 48 * sy, 60 * sx, 62 * sy);
          context.setLineDash([]);
          context.fillStyle = '#ff597d';
          context.fillText(`E${point.id} barra?`, x - 30 * sx, y - 51 * sy);
        }
        const candidate = point.visual_candidate;
        const box = candidate?.box;
        if (!Array.isArray(box) || box.length !== 4) continue;
        context.strokeStyle = '#ffb0a0';
        context.setLineDash([5, 4]);
        context.strokeRect(box[0] * sx, box[1] * sy,
          (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
        context.setLineDash([]);
        context.fillStyle = '#ffb0a0';
        context.fillText(`E${point.id}?`, box[0] * sx, box[1] * sy - 4);
      }
    }
  }

  function drawObservedRegionsLayer(context, canvas, frameSourceMs, sx, sy) {
    context.save();
    context.font = `${Math.max(11, canvas.width / 92)}px sans-serif`;
    for (const diagnostic of [state?.hud_diagnostic, state?.hub_diagnostic]) {
      const delta = frameSourceMs - diagnostic?.source_ms;
      if (!Number.isFinite(delta) || delta < 0 || delta > 3000) continue;
      for (const row of diagnostic.boxes || []) {
        const box = row.observed_box || row.box;
        if (!Array.isArray(box) || box.length !== 4) continue;
        context.strokeStyle = row.id?.startsWith('hub.') ? '#69e4ae' : '#f6c778';
        context.lineWidth = Math.max(1, canvas.width / 800);
        context.strokeRect(box[0] * sx, box[1] * sy,
          (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
        if ((row.id?.startsWith('hub.inventory.') || row.id?.startsWith('hub.equipped.')) &&
            row.label && row.label !== 'item não identificado') {
          const label = `${row.label}?`;
          const x = Math.min(canvas.width - context.measureText(label).width - 6,
            box[2] * sx + 3);
          const y = Math.max(14, box[1] * sy + 13);
          context.fillStyle = 'rgba(8, 24, 18, .86)';
          context.fillRect(x - 2, y - 12, context.measureText(label).width + 5, 15);
          context.fillStyle = '#69e4ae';
          context.fillText(label, x, y);
        }
      }
    }
    context.restore();
  }

  function drawFastInventoryLayer(context, canvas, sx, sy, reading) {
    if (!reading) return;
    context.save();
    context.font = `${Math.max(11, canvas.width / 92)}px sans-serif`;
    for (const slot of reading.slots || []) {
      if (slot.status !== 'visual_candidate' || !slot.name) continue;
      const rect = slot.rect;
      if (!rect) continue;
      const x = rect.x * sx, y = rect.y * sy;
      context.strokeStyle = '#88ffb3';
      context.lineWidth = Math.max(2, canvas.width / 500);
      context.strokeRect(x, y, rect.width * sx, rect.height * sy);
      const label = `item ${slot.slot}: ${slot.name}?`;
      const width = context.measureText(label).width;
      context.fillStyle = 'rgba(8, 24, 18, .88)';
      context.fillRect(x + rect.width * sx + 2, y, width + 8, 17);
      context.fillStyle = '#88ffb3';
      context.fillText(label, x + rect.width * sx + 6, y + 13);
    }
    context.restore();
  }

  function drawTrackedBarsLayer(context, canvas, frameSourceMs, sx, sy) {
    const fast = state?.fast_diagnostic;
    const lag = frameSourceMs - fast?.source_ms;
    if (fast?.status !== 'observed' || !Number.isFinite(lag) || lag < 0 || lag > 1500) return;
    context.save();
    if (lag > 900) context.globalAlpha = .5;
    for (const marker of fast.markers || []) {
      const box = marker.box;
      if (!Array.isArray(box) || box.length !== 4) continue;
      const color = marker.color === 'red' ? '#ff597d' :
        marker.color === 'purple' ? '#bd83ff' : '#35f2cc';
      context.strokeStyle = '#111521';
      context.lineWidth = Math.max(4, canvas.width / 320);
      context.strokeRect(box[0] * sx, box[1] * sy,
        (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
      context.strokeStyle = color;
      context.lineWidth = Math.max(2.5, canvas.width / 550);
      context.strokeRect(box[0] * sx, box[1] * sy,
        (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
      context.fillStyle = color;
      context.fillText(`#${marker.track_id}`, box[0] * sx, box[1] * sy - 5);
      if (marker.color === 'red' && marker.scan_zone === 'arena') {
        const middle = (box[0] + box[2]) / 2;
        const width = Math.max(28, Math.min(74, (box[2] - box[0]) * 1.4));
        const height = Math.max(34, Math.min(78, width * 1.2));
        context.setLineDash([5, 4]);
        context.strokeRect((middle - width / 2) * sx, (box[3] + 4) * sy,
          width * sx, height * sy);
        context.setLineDash([]);
        context.fillText(`unidade? #${marker.track_id}`,
          (middle - width / 2) * sx, (box[3] + 17) * sy);
      }
      if (marker.color === 'red' && marker.scan_zone === 'upper_reserve') {
        const middle = (box[0] + box[2]) / 2;
        const width = Math.max(36, Math.min(80, (box[2] - box[0]) * 1.3));
        context.setLineDash([5, 4]);
        context.strokeRect((middle - width / 2) * sx, (box[3] + 4) * sy,
          width * sx, 70 * sy);
        context.setLineDash([]);
        context.fillText(`reserva? #${marker.track_id}`,
          (middle - width / 2) * sx, (box[3] + 17) * sy);
      }
      if (marker.color === 'purple' && Array.isArray(marker.avatar_box)) {
        const avatar = marker.avatar_box;
        context.setLineDash([5, 4]);
        context.strokeRect(avatar[0] * sx, avatar[1] * sy,
          (avatar[2] - avatar[0]) * sx, (avatar[3] - avatar[1]) * sy);
        context.setLineDash([]);
      }
    }
    const streak = fast.streak;
    if (streak?.status === 'icon_color_candidate' && Array.isArray(streak.box)) {
      const box = streak.box;
      context.strokeStyle = streak.kind === 'win' ? '#ff9e4a' : '#58b9ff';
      context.lineWidth = Math.max(2, canvas.width / 600);
      context.strokeRect(box[0] * sx, box[1] * sy,
        (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
      context.fillStyle = context.strokeStyle;
      context.fillText(streak.kind === 'win' ? 'sequência vitória?' : 'sequência derrota?',
        box[0] * sx, box[1] * sy - 5);
    }
    context.restore();
  }

  function drawTraitTooltipLayer(context, canvas, frameSourceMs, sx, sy) {
    const reading = state?.trait_tooltip;
    const lag = frameSourceMs - reading?.source_ms;
    if (reading?.status !== 'active_portraits_named' ||
        !Number.isFinite(lag) || lag < 0 || lag > 850) return;
    context.save();
    context.lineWidth = Math.max(2, canvas.width / 650);
    context.font = `${Math.max(12, canvas.width / 95)}px sans-serif`;
    for (const slot of reading.active_slots || []) {
      const box = slot.box;
      if (!Array.isArray(box) || box.length !== 4 || !slot.name) continue;
      const x = box[0] * sx, y = box[1] * sy;
      const width = (box[2] - box[0]) * sx, height = (box[3] - box[1]) * sy;
      context.strokeStyle = '#e4ff81';
      context.strokeRect(x, y, width, height);
      const label = `${slot.name}?`;
      const labelWidth = context.measureText(label).width;
      context.fillStyle = 'rgba(7, 20, 20, .9)';
      context.fillRect(x, Math.max(0, y - 23), labelWidth + 8, 20);
      context.fillStyle = '#e4ff81';
      context.fillText(label, x + 4, Math.max(16, y - 7));
    }
    context.restore();
  }

  function drawEnemyEquippedLayer(context, canvas, sx, sy, reading) {
    if (!reading) return;
    context.save();
    context.font = `${Math.max(11, canvas.width / 110)}px sans-serif`;
    context.lineWidth = Math.max(2, canvas.width / 750);
    context.strokeStyle = '#ffd073';
    for (const item of reading.enemy_equipped || []) {
      const box = item.rect;
      if (!Array.isArray(box) || box.length !== 4) continue;
      const x = box[0] * sx, y = box[1] * sy;
      context.strokeRect(x, y, (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
      {
        const label = `#${item.track_id} item ${item.slot + 1}: `+
          (item.name ? `${item.name}?` : 'nome incerto');
        const labelY = (box[3] + 17) * sy;
        context.fillStyle = 'rgba(7, 20, 20, .9)';
        context.fillRect(x, labelY - 14, context.measureText(label).width + 6, 18);
        context.fillStyle = '#ffd073';
        context.fillText(label, x + 3, labelY);
      }
    }
    context.restore();
  }

  function drawSelectedUnitPanelLayer(context, canvas, frameSourceMs, sx, sy) {
    const selected = state?.selected_unit_panel;
    const lag = frameSourceMs - selected?.source_ms;
    if (selected?.status !== 'selected_unit_named' || !selected.champion_name ||
        !Number.isFinite(lag) || lag < 0 || lag > 900) return;
    const box = selected.portrait_box;
    if (!Array.isArray(box) || box.length !== 4) return;
    const x = box[0] * sx, y = box[1] * sy;
    context.save();
    context.strokeStyle = '#e4ff81';
    context.lineWidth = Math.max(2, canvas.width / 600);
    context.strokeRect(x, y, (box[2] - box[0]) * sx, (box[3] - box[1]) * sy);
    const label = `${selected.champion_name} · painel`;
    context.fillStyle = 'rgba(8, 24, 18, .9)';
    context.fillRect(x, y, context.measureText(label).width + 10, 21);
    context.fillStyle = '#e4ff81';
    context.fillText(label, x + 5, y + 16);
    context.restore();
  }

  function drawLiveOverlay(context, canvas, frameSourceMs, overlay) {
    displayedSourceMs = frameSourceMs;
    const source = overlay?.source_size || [1920, 1080];
    const sx = canvas.width / source[0], sy = canvas.height / source[1];
    const age = Math.max(0, (Date.now() - (overlay?.received_at_ms || Date.now())) / 1000);
    // The video keeps moving between inference results. Never pair a result
    // with a frame from before it, or retain boxes after they have gone stale.
    const lagMs = frameSourceMs - overlay?.source_ms;
    const current = Number.isFinite(lagMs) && lagMs >= 0 && lagMs <= 3000;
    const unitLabel = row => row.candidate_name ?
      (row.candidate_id ? row.candidate_name : 'possível '+row.candidate_name) :
      'campeão incerto';
    const rows = current ? [
      ...(overlay.detections || []).map(row => ({box: row.box, label: row.class_name,
        confidence: row.confidence, color: '#a879ff'})),
      ...(overlay.units || []).map(row => ({box: row.box, label: unitLabel(row),
        confidence: row.confidence_uncalibrated, color: '#64e2b2'})),
      ...(overlay.bench_units || []).map(row => ({box: row.box,
        label: 'Banco visível? '+unitLabel(row),
        confidence: row.confidence_uncalibrated, color: '#8be7ff'})),
      ...(overlay.enemy_units || []).map(row => ({box: row.box,
        label: 'Inimigo? '+unitLabel(row),
        confidence: row.confidence_uncalibrated, color: '#ff8068'})),
      ...(overlay.mascots || []).map(row => ({box: row.box,
        label: row.class_name === 'own_tactician' ? 'Mascote meu? · barra' : 'Mascote rival? · barra',
        color: '#7fd4ff'})),
      ...(overlay.items || []).map(row => ({box: row.box, label: row.name,
        confidence: row.confidence_uncalibrated, color: '#ffd073'}))
    ] : [];
    context.save();
    context.lineWidth = Math.max(1.5, canvas.width / 700);
    context.font = `${Math.max(12, canvas.width / 85)}px sans-serif`;
    // Stage 1-1 is also present during the transition into the arena. Keep
    // the fixed grid gated by the full gameplay HUD to avoid drawing it in
    // empty sky or over loading cards.
    if (state?.screen_mode === 'gameplay_hud') {
      window.BenchRuler?.draw(context, canvas, state?.spatial_map);
      window.BenchRuler?.drawBoard(context, canvas, state?.spatial_map);
      drawSpatialLayer(context, canvas, frameSourceMs, sx, sy);
      drawObservedRegionsLayer(context, canvas, frameSourceMs, sx, sy);
    }
    // These readers verify icon presence from pixels. Economy OCR is not a
    // prerequisite: a missed gold digit must not erase visible item labels.
    const frameItems = fastItemsForFrame(frameSourceMs);
    drawFastInventoryLayer(context, canvas, sx, sy, frameItems);
    drawEnemyEquippedLayer(context, canvas, sx, sy, frameItems);
    // Bars remain visible when a selected-unit panel hides gold and the shop.
    // A readable stage gates out loading screens; it does not prove ownership.
    if (state?.screen_mode === 'gameplay_hud' ||
        state?.screen_mode === 'stage_without_economy') {
      drawTrackedBarsLayer(context, canvas, frameSourceMs, sx, sy);
      drawTraitTooltipLayer(context, canvas, frameSourceMs, sx, sy);
      drawSelectedUnitPanelLayer(context, canvas, frameSourceMs, sx, sy);
    }
    for (const row of state?.screen_mode === 'gameplay_hud' ? rows : []) {
      const box = row.box;
      if (!Array.isArray(box) || box.length !== 4 || !row.label) continue;
      const x = box[0] * sx, y = box[1] * sy;
      const width = (box[2] - box[0]) * sx, height = (box[3] - box[1]) * sy;
      if (width < 2 || height < 2) continue;
      context.strokeStyle = row.color;
      context.strokeRect(x, y, width, height);
      const label = `${row.label}${Number.isFinite(row.confidence) ?
        ' '+Math.round(row.confidence * 100)+'%' : ''}`;
      const textWidth = context.measureText(label).width;
      const top = Math.max(16, y);
      context.fillStyle = 'rgba(10, 12, 20, .8)';
      context.fillRect(x, top - 16, textWidth + 8, 18);
      context.fillStyle = row.color;
      context.fillText(label, x + 4, top - 3);
    }
    const header = state?.phase === 'finished' ?
      `Replay concluído · quadro ${(frameSourceMs/1000).toFixed(1)} s · último registro salvo` :
      `Visão ${Number.isFinite(overlay?.processing_ms) ? Math.round(overlay.processing_ms)+' ms' : 'aguardando'} · `+
      `${rows.length} caixas · vídeo ${(frameSourceMs/1000).toFixed(1)} s · `+
      `atraso da leitura ${current ? (lagMs/1000).toFixed(1)+' s' : 'aguardando'} · há ${age.toFixed(1)} s`;
    context.fillStyle = 'rgba(10, 12, 20, .83)';
    context.fillRect(0, 0, context.measureText(header).width + 18, 27);
    context.fillStyle = '#fff';
    context.fillText(header, 9, 19);
    context.restore();
  }
  function startPreview() {
    ++previewGeneration;
    if (previewRequest) previewRequest.abort();
    previewDrawTimes.length = 0;
    displayedSourceMs = null;
    const canvas = document.querySelector('#live-preview-canvas');
    const overlayCanvas = document.querySelector('#live-preview-overlay');
    if (!canvas || !overlayCanvas) return;
    const generation = previewGeneration;
    const context = canvas.getContext('2d', {alpha: false, desynchronized: true});
    const overlayContext = overlayCanvas.getContext('2d', {alpha: true});
    if (!context || !overlayContext) return;
    let after = 0, errors = 0, lastOverlayKey = '', pending = null;
    (async () => {
      while (generation === previewGeneration && canvas.isConnected) {
        if (state?.phase === 'finished' && after >= Number(state?.preview_sequence || 0)) break;
        const request = pending?.request || new AbortController();
        const responsePromise = pending?.promise || fetch(
          new URL('frame.jpg?after=' + after, location.href),
          {cache: 'no-store', signal: request.signal});
        pending = null;
        previewRequest = request;
        try {
          const response = await responsePromise;
          if (response.status === 204) continue;
          if (!response.ok) throw new Error('Prévia indisponível.');
          const sequence = Number(response.headers.get('X-Frame-Sequence'));
          const frameSourceMs = Number(response.headers.get('X-Frame-Source-Ms'));
          if (!Number.isSafeInteger(sequence) || sequence <= after) throw new Error('Quadro inválido.');
          // Wait for the following frame while this one is decoded and drawn.
          // Keeping one request in flight removes a round trip from the
          // display's critical path without accumulating old frames.
          const nextRequest = new AbortController();
          pending = {request: nextRequest, promise: fetch(
            new URL('frame.jpg?after=' + sequence, location.href),
            {cache: 'no-store', signal: nextRequest.signal})};
          previewRequest = nextRequest;
          const bitmap = await createImageBitmap(await response.blob());
          try {
            if (generation !== previewGeneration || !canvas.isConnected) break;
            if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
              canvas.width = bitmap.width;
              canvas.height = bitmap.height;
              overlayCanvas.width = bitmap.width;
              overlayCanvas.height = bitmap.height;
            }
            context.drawImage(bitmap, 0, 0);
            const overlay = state?.yolo_overlay;
            const lag = frameSourceMs - overlay?.source_ms;
            const current = Number.isFinite(lag) && lag >= 0 && lag <= 3000;
            const overlayKey = `${overlay?.source_ms}:${state?.hud_diagnostic?.source_ms}:`+
              `${state?.screen_mode}:`+
              `${state?.hub_diagnostic?.source_ms}:${state?.spatial_map?.source_ms}:`+
              `${state?.fast_diagnostic?.source_ms}:`+
              `${state?.fast_items?.source_ms}:`+
              `${state?.selected_unit_panel?.source_ms}:`+
              `${state?.trait_tooltip?.source_ms}:`+
              `${current}:${Math.floor(frameSourceMs / 1000)}`;
            if (overlayKey !== lastOverlayKey) {
              overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
              drawLiveOverlay(overlayContext, overlayCanvas, frameSourceMs, overlay);
              lastOverlayKey = overlayKey;
            }
            canvas.closest('.live-preview')?.classList.add('yolo-analysis-ready');
            const waiting = canvas.closest('.live-preview')?.querySelector('.live-preview-empty');
            if (waiting) waiting.hidden = true;
            const drawnAt = performance.now();
            previewDrawTimes.push(drawnAt);
            while (previewDrawTimes.length && previewDrawTimes[0] < drawnAt - 1000)
              previewDrawTimes.shift();
            after = sequence;
            errors = 0;
          } finally { bitmap.close(); }
        } catch (error) {
          if (request.signal.aborted) break;
          if (pending) { pending.request.abort(); pending = null; }
          ++errors;
          await new Promise(resolve => setTimeout(resolve, Math.min(1000, errors * 100)));
        } finally {
          if (previewRequest === request) previewRequest = null;
        }
      }
      if (pending) {
        pending.request.abort();
        if (previewRequest === pending.request) previewRequest = null;
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
        `<small>${row.kind==='video'?'Arquivo de replay':row.candidate_tft?'Possível janela TFT':'Fonte disponível'}</small><i>✓</i></button>`).join('') :
        '<div class="source-wait">Nenhum monitor ou janela disponível nesta sessão do Windows.</div>';
      selected = rows[chosenIndex] || null;
      const replayMode = dialog.querySelector('#studio-replay-mode');
      if (replayMode) replayMode.checked = selected?.kind === 'video';
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

  function renderLiveDiagnostics() {
    const target = document.querySelector('#live-diagnostic-grid');
    if (!target) return;
    if (terminalMode && current === 'studio') {
      if (!target.querySelector('.live-terminal'))
        target.innerHTML = '<pre class="live-terminal" role="status" aria-live="off"></pre>';
      const hud = state?.hud_diagnostic || {};
      const hub = state?.hub_diagnostic || {};
      const fast = state?.fast_diagnostic || {};
      const items = state?.fast_items || {};
      const trait = state?.trait_tooltip || {};
      const selected = state?.selected_unit_panel || {};
      const spatial = state?.spatial_map || {};
      const macro = items.enemy_equipment_macro || {};
      const recipes = state?.core_recipe_catalog || {};
      const sourceSec = value => Number.isFinite(value?.source_ms) ?
        `${(value.source_ms / 1000).toFixed(1)}s` : '—';
      const fields = (hud.hud || []).map(row => `${row.field}=${row.value ?? '?'} [${row.status}]`);
      const shop = (hud.shop || []).map((row, index) =>
        `${index + 1}:${row.observed_name || '?'}${row.observed_cost == null ? '' : '/'+row.observed_cost}`);
      const rivals = (items.enemy_equipped || []).map(row =>
        `#${row.track_id} item${row.slot + 1}=${row.name ? row.name+'?' : 'ícone sem nome'}`);
      const inventory = (items.slots || []).map(row =>
        `slot${row.slot}=${row.name ? row.name+'?' : row.status}`);
      const portraits = (trait.active_slots || []).map(row => row.name + '?');
      const named = state?.trait_tooltip_last_named || {};
      const lines = [
        state?.phase === 'finished' ?
          'AGENTE TFT   replay concluído   último quadro preservado' :
          `AGENTE TFT   ${state?.phase || 'aguardando'}   preview ${state?.preview_encoded_fps ?? 0} fps`,
        `HUD ${sourceSec(hud)}  ${fields.join('  ') || 'sem leitura'}`,
        `HP ${fast.player_hp?.value ?? '?'} [${fast.player_hp?.status || 'sem leitura'}]  Rust ${hud.rust?.status || state?.decision_status || 'aguardando'}`,
        `LOJA ${shop.join(' | ') || 'sem leitura'}`,
        `BARRAS ${sourceSec(fast)}  ${(fast.markers || []).length} totais  ${(fast.markers || []).filter(row => row.color === 'red').length} vermelhas`,
        `TABULEIRO ${sourceSec(hub)}  ${hub.processing_ms ?? '?'} ms total  barras ${hub.worker_ms ?? '?'} ms  calibração ${hub.diagnostic_timings_ms?.calibration_ms ?? '?'} ms  itens/grade ${hub.diagnostic_timings_ms?.snapshot_ms ?? '?'} ms`,
        `MAPA meu ${(spatial.own_cells || []).length}/28  rival ${(spatial.enemy_cells || []).length}/28  bancos ${(spatial.own_bench || []).length}/9 + ${(spatial.enemy_bench || []).length}/9`,
        `INVENTÁRIO ${sourceSec(items)}  ${inventory.join(' | ') || 'nenhum ícone'}`,
        `RIVAL EQUIPADO ${sourceSec(items)}  ${macro.visible_item_icons ?? 0} ícone(s) em ${macro.equipped_unit_tracks ?? 0} peça(s)  ${rivals.join(' | ') || 'nenhum ícone visível'}`,
        `RECEITAS ${recipes.pair_count ?? 0}/36 combinações básicas · efeitos estratégicos avaliados à parte`,
        `SINERGIA ${sourceSec(trait)}  ${trait.status === 'active_portraits_named' ? trait.trait+': '+portraits.join(', ') : 'janela não lida neste quadro'}`,
        `ÚLTIMA SINERGIA ${named.trait ? named.trait+': '+(named.candidate_names || []).join(', ') : '—'}`,
        `SELEÇÃO ${sourceSec(selected)}  ${selected.champion_name || selected.status || 'nenhuma'}`,
        `DECISÃO ${state?.tip?.text || state?.decision_reason || 'aguardando evidência'}`,
        'Nomes com ? são candidatos visuais. Ícones contam apenas enquanto aparecem.'
      ];
      target.querySelector('.live-terminal').textContent = lines.join('\n');
      return;
    }
    const hud = state?.hud_diagnostic || {};
    const hub = state?.hub_diagnostic || {};
    const spatial = state?.spatial_map || {};
    const fast = state?.fast_diagnostic || {};
    const upperBarCount = (fast.markers || []).filter(row =>
      row.color === 'red' && row.scan_zone === 'upper_reserve').length;
    const fastItems = state?.fast_items || {};
    const tooltip = state?.trait_tooltip || {};
    const lastNamedTooltip = state?.trait_tooltip_last_named || {};
    const selectedPanelCurrent = state?.selected_unit_panel || {};
    const selectedPanel = state?.selected_unit_panel_last_named ||
      (selectedPanelCurrent.status === 'selected_unit_named' ? selectedPanelCurrent : {});
    const shopMath = state?.shop_math || {};
    const newestSourceMs = Math.max(0, ...[hud, hub, spatial, fast, fastItems, tooltip, selectedPanel, shopMath]
      .map(row => row.source_ms).filter(Number.isFinite));
    const sourceLabel = (row, maxAgeMs=3000) => {
      const sourceMs = row?.source_ms;
      if (!Number.isFinite(sourceMs)) return 'sem quadro';
      const age = newestSourceMs - sourceMs;
      return `${Math.round(sourceMs / 1000)} s · ${age > maxAgeMs ? 'antigo' : Math.round(age)+' ms atrás'}`;
    };
    const mapRows = (points, side, bench=false) => (points || []).map(point => {
      const center = point.center;
      const location = Array.isArray(center) && center.length === 2 && center.every(Number.isFinite) ?
        `${Math.round(center[0])}, ${Math.round(center[1])}` : 'sem âncora';
      const markerCount = Array.isArray(point.marker_candidates) ? point.marker_candidates.length : 0;
      const possibleName = point.visual_candidate?.candidate_name;
      const observation = possibleName ? ` · ${escapeHtml(possibleName)}?` :
        markerCount ? ` · ${markerCount} barra(s) candidata(s)` : '';
      return `${side}${escapeHtml(point.id)}: ${location}${observation}`;
    }).join(' · ');
    const mapDetails = `<details><summary>Todos os endereços e âncoras do mapa</summary>`+
      `<p><b>Meu tabuleiro</b><br>${mapRows(spatial.own_cells, 'P') || 'sem leitura'}</p>`+
      `<p><b>Meu banco</b><br>${mapRows(spatial.own_bench, 'P', true) || 'sem leitura'}</p>`+
      `<p><b>Tabuleiro rival</b><br>${mapRows(spatial.enemy_cells, 'E') || 'sem leitura'}</p>`+
      `<p><b>Banco rival</b><br>${mapRows(spatial.enemy_bench, 'E', true) || 'sem leitura'}</p>`+
      `</details>`;
    const streak = fast.streak || {};
    const streakLabel = streak.status === 'icon_color_candidate' ?
      `${streak.kind === 'win' ? 'vitórias?' : 'derrotas?'} (ícone; número pendente)` :
      'ainda não lida';
    const ownPlaced = (spatial.own_cells || []).filter(row => Array.isArray(row.center)).length;
    const enemyPlaced = (spatial.enemy_cells || []).filter(row => Array.isArray(row.center)).length;
    const ownBenchPlaced = (spatial.own_bench || []).filter(row => Array.isArray(row.center)).length;
    const enemyBenchPlaced = (spatial.enemy_bench || []).filter(row => Array.isArray(row.center)).length;
    const enemyBenchObserved = (spatial.enemy_bench || []).filter(row => row.visual_candidate).length;
    const boardNames = [...(spatial.own_cells || []), ...(spatial.enemy_cells || []),
      ...(spatial.own_bench || []), ...(spatial.enemy_bench || [])]
      .filter(row => row.champion_id).length;
    const selectedPanelLabel = selectedPanel.status === 'selected_unit_named' ?
      `${escapeHtml(selectedPanel.champion_name)} · ${selectedPanel === selectedPanelCurrent ? 'seleção atual' : 'última seleção lida'} · `+
      `${sourceLabel(selectedPanel)} · `+
      `banco/casa ainda sem vínculo` :
      selectedPanelCurrent.status === 'panel_name_unresolved' ?
        `painel visível, nome sem leitura segura · ${sourceLabel(selectedPanelCurrent)}` :
        'nenhuma seleção de peça lida';
    const selectedPortrait = selectedPanel.status === 'selected_unit_named' && selectedPanel.portrait_sha256 ?
      `<img src="${new URL('selected-unit-portrait.png?sha='+encodeURIComponent(selectedPanel.portrait_sha256), location.href).href}" `+
      `alt="Retrato da peça selecionada" width="118" height="74" style="object-fit:cover;object-position:center top;border-radius:4px">` : '';
    const enemyBoardLabel = enemyPlaced ? `${enemyPlaced}/28` : 'fora do enquadramento ou sem calibração';
    const enemyBenchLabel = enemyBenchPlaced ? `${enemyBenchPlaced}/9` : 'fora do enquadramento ou sem calibração';
    const mapState = spatial.own_geometry_status === 'standard_screen_geometry' ?
      'Grade padrão 1080p · guia visual' :
      spatial.own_geometry_status === 'arena_candidate' ?
        `Arena ${escapeHtml(spatial.reserve_calibration?.profile || 'reconhecida')} · posições candidatas` :
        'Aguardando enquadramento da partida';
    const fields = (hud.hud || []).map(row =>
      `${escapeHtml(row.field)}: <b>${escapeHtml(row.value ?? '—')}</b> <small>${escapeHtml(row.status || 'incerto')}</small>`);
    const hp = fast.player_hp || {};
    fields.push(`HP: <b>${escapeHtml(hp.value ?? '—')}</b> <small>${escapeHtml(hp.status || 'sem leitura')} `+
      `${Number.isFinite(hp.age_ms) ? '· '+Math.round(hp.age_ms)+' ms' : ''}</small>`);
    const shop = (hud.shop || []).map(row =>
      `${Number(row.slot) + 1}: ${escapeHtml(row.observed_name || 'não lido')} ${row.observed_cost == null ? '' : '· '+escapeHtml(row.observed_cost)+' ouro'}`);
    const units = (state?.temporal_candidates?.units || []).slice(0, 8).map(row => {
      const pos = row.position || [];
      const place = pos[0] === 'board' && Number.isInteger(pos[1]) && Number.isInteger(pos[2]) ?
        `${String.fromCharCode(65 + pos[1])}${pos[2] + 1}` :
        pos[0] === 'bench' && Number.isInteger(pos[2]) ? `R${pos[2] + 1}` : '?';
      return `${escapeHtml(place)}: ${escapeHtml(row.candidate_name || 'identidade incerta')}`;
    });
    const items = [
      ...(fastItems.status === 'observed' ? (fastItems.enemy_equipped || [])
        .map(row => `rival barra #${escapeHtml(row.track_id ?? '?')} item ${escapeHtml(row.slot + 1)}: `+
          `${row.name ? escapeHtml(row.name)+'?' : 'ícone visto; nome incerto'}`) : []),
      ...(fastItems.status === 'observed' ? (fastItems.slots || [])
        .filter(row => row.status === 'visual_candidate' && row.name)
        .map(row => `inventário ${escapeHtml(row.slot)}: ${escapeHtml(row.name)}?`) : []),
      ...(hub.item_candidates || []).filter(row => row.zone !== 'inventory')
        .map(row => `${escapeHtml(row.zone)} ${escapeHtml(row.slot ?? row.marker_id ?? '?')}: `+
          `${escapeHtml((row.names || [])[0] || 'incerto')}?`)
    ].slice(0, 8);
    const itemReader = hub.item_reader || {};
    const enemyItemMacro = fastItems.enemy_equipment_macro || {};
    const enemyItemLabel = fastItems.status === 'observed' ?
      `${escapeHtml(enemyItemMacro.visible_item_icons ?? 0)} ícone(s) visíveis em `+
      `${escapeHtml(enemyItemMacro.equipped_unit_tracks ?? 0)} peça(s) rastreadas; `+
      `${escapeHtml(enemyItemMacro.sampled_red_bars ?? 0)} barra(s) vermelha(s) examinadas` :
      'aguardando barras e ícones adversários';
    const itemReaderLabel = itemReader.active ?
      `${escapeHtml(itemReader.reference_artworks ?? 0)} artes carregadas · `+
      `${Number.isFinite(itemReader.matching_ms) ? itemReader.matching_ms.toFixed(1)+' ms' : 'tempo não medido'}` :
      `leitor indisponível: ${escapeHtml(itemReader.error || 'sem estado')}`;
    const rust = hud.rust || {};
    const scores = (rust.ranked || []).slice(0, 5).map(row =>
      `${escapeHtml(row.action || 'ação')} ${escapeHtml(row.target || '')}: ${Number.isFinite(row.utility) ? row.utility.toFixed(3) : '—'}`);
    const currentOpponent = state?.opponents?.current_opponent;
    const opponentRows = (state?.opponents?.players || []).filter(row => row.name).map(row =>
      `${escapeHtml(row.name)}: HP ${escapeHtml(row.hp ?? '—')} (${escapeHtml(row.status || 'sem estado')})`);
    const portraitNames = (tooltip.active_slots || []).map(row => escapeHtml(row.name)+'?');
    const traitLabel = tooltip.status === 'active_portraits_named' ?
      `${escapeHtml(tooltip.trait)} · ${portraitNames.join(', ')} · ${tooltip.active_portraits} retrato(s) ativos` :
      tooltip.status === 'insufficient_visual_evidence' ?
      `${escapeHtml(tooltip.trait || 'Sinergia')} · retratos sem leitura suficiente` :
      'Nenhuma janela de sinergia completa neste quadro';
    const lastTraitLabel = lastNamedTooltip.status === 'active_portraits_named' ?
      `${escapeHtml(lastNamedTooltip.trait)}: ${(lastNamedTooltip.candidate_names || [])
        .map(name => escapeHtml(name)+'?').join(', ') || 'sem nomes'} · ${sourceLabel(lastNamedTooltip)}` :
      'nenhuma leitura anterior';
    const mathLabel = shopMath.status ?
      `${escapeHtml(shopMath.status)} · nível ${escapeHtml(shopMath.level ?? '—')} · `+
      `patch ${escapeHtml(shopMath.patch || '—')} · chance real ${shopMath.actual_probability_known ? 'conhecida' : 'não conhecida'}` :
      'Aguardando cálculo';
    const chanceRows = Object.entries(shopMath.probabilities || {})
      .filter(([, chance]) => Number.isFinite(chance))
      .sort((a, b) => b[1] - a[1])
      .map(([champion, chance]) => `${escapeHtml(champion)}: ${(chance * 100).toFixed(2)}%`);
    target.innerHTML =
      `<section><h3>Mapa e rastreio <small>${mapState}</small></h3>`+
      `<small>Geometria: ${sourceLabel(spatial)} · rastreio: ${sourceLabel(fast, 900)}</small>`+
      `<p>Casas posicionadas: meu lado ${ownPlaced}/28 · rival ${enemyBoardLabel}<br>`+
      `Bancos posicionados: inferior ${ownBenchPlaced}/9 · rival ${enemyBenchLabel}</p>`+
      `<p>Nomes ligados a uma peça e casa: ${boardNames}. `+
      `${boardNames ? 'Somente identificações verificadas.' :
        'O leitor de retratos ainda não identifica a peça no tabuleiro.'}</p>`+
      `<p>Confronto: ${escapeHtml(currentOpponent || 'jogador ainda não identificado')} · `+
      `barras rastreadas ${fast.status === 'observed' ? (fast.markers || []).length : 0} · `+
      `sequência ${streakLabel}</p>`+
      `<p>Banco rival: ${upperBarCount} barra(s) vermelha(s) na faixa superior · `+
      `${enemyBenchObserved} retrato(s) candidato(s). `+
      `Nome e posse dependem de confirmação.</p>`+
      `<p>Peça selecionada: ${selectedPanelLabel}</p>${selectedPortrait}`+
      `<p>${units.length ? units.join('<br>') : 'Aguardando unidades rastreadas.'}</p>`+
      `<p>Adversários: ${opponentRows.join(' · ') || 'aguardando leitura da lista'}</p>`+
      `${mapDetails}`+
      `<small>P = meu lado · E = rival · R1–R9 = banco. Ocupação e nome só entram após confirmação.</small></section>`+
      `<section class="live-math-panel"><h3>Leituras e Rust <small>${escapeHtml(rust.status || 'aguardando')}</small></h3>`+
      `<small>HUD: ${sourceLabel(hud)} · cálculo: ${sourceLabel(shopMath)}</small>`+
      `<p>${fields.join(' · ') || 'HUD sem leitura recente.'}</p>`+
      `<p>Loja: ${shop.join(' · ') || 'aguardando'}</p>`+
      `<p>Probabilidades: ${mathLabel}</p>`+
      `<details><summary>Distribuição por campeão (${chanceRows.length})</summary>`+
      `<p>Chance condicional de uma casa da loja; pressuposto: ${escapeHtml(shopMath.assumption || 'não informado')}. `+
      `Fórmula: ${escapeHtml(shopMath.formula || 'não informada')}.</p>`+
      `<p>${chanceRows.join(' · ') || 'Nenhuma distribuição calculada.'}</p></details>`+
      `<p>${scores.join('<br>') || 'Nenhum cálculo disponível neste quadro.'}</p>`+
      `<p>Motor: ${escapeHtml(rust.reason || state?.decision_reason || 'sem decisão')} · índice escolhido ${escapeHtml(rust.selected_index ?? '—')}</p>`+
      `<small>Rust ${Number.isFinite(rust.native_ms) ? rust.native_ms.toFixed(1)+' ms' : '—'} · `+
      `rastreio ${Number.isFinite(fast.processing_ms) ? fast.processing_ms.toFixed(1)+' ms' : '—'} · `+
      `leitura completa ${Number.isFinite(hub.processing_ms) ? hub.processing_ms.toFixed(1)+' ms' : '—'}</small></section>`+
      `<section class="live-moves-panel"><h3>Itens e decisão</h3>`+
      `<small>Inventário: ${sourceLabel(fastItems, 900)} · equipados: ${sourceLabel(hub)} · `+
      `sinergia: ${sourceLabel(tooltip, 350)}</small>`+
      `<p>Itens candidatos: ${items.join(' · ') || 'nenhum ícone lido neste quadro'}</p>`+
      `<p>Equipamento rival no macro: ${enemyItemLabel}</p>`+
      `<p>Leitor de itens: ${itemReaderLabel}</p>`+
      `<p>Sinergia: ${traitLabel} · nomes são candidatos visuais</p>`+
      `<p>Última sinergia lida: ${lastTraitLabel}</p>`+
      `<p>Captura/gravação: ${escapeHtml(state?.preview_encoded_fps ?? 0)} quadros/s na prévia · `+
      `${escapeHtml(state?.counts?.trait_tooltip_results ?? 0)} leituras rápidas · `+
      `${escapeHtml(state?.save_diagnostic?.trait_events_saved ?? 0)} eventos salvos · `+
      `${escapeHtml(state?.save_diagnostic?.selected_panel_events_saved ?? 0)} painéis salvos · `+
      `${Number.isFinite(state?.save_diagnostic?.persist_p95_ms) ?
        state.save_diagnostic.persist_p95_ms.toFixed(1)+' ms até salvar (p95) · ' : ''}`+
      `${escapeHtml(state?.save_diagnostic?.trait_queue_replaced ?? 0)} quadros substituídos · `+
      `${escapeHtml(state?.save_diagnostic?.write_queue_dropped ?? 0)} gravações descartadas.</p>`+
      `<p>Decisão: ${escapeHtml(state?.tip?.text || state?.decision_reason || 'aguardando evidência')}</p>`+
      `<small>Catálogo de itens ativo; vínculo item → unidade ainda é candidato.</small></section>`;
  }

  function connectedPage() {
    document.body.classList.toggle('terminal-mode', terminalMode && current === 'studio');
    const presentation = document.querySelector('.presentation-bar');
    if (presentation) presentation.style.display = 'none';
    const footer = document.querySelector('.presentation-footer');
    if (footer) footer.style.display = 'none';
    document.querySelector('.sidebar-footer').innerHTML = '<span class="status-dot"></span> APLICATIVO LOCAL <span>01.0</span>';
    document.querySelector('.statusbar>span').innerHTML =
      '<span class="status-dot"></span> CAPTURA LOCAL <i>·</i> '+
      (state?.unit_model_active ? 'RECONHECIMENTO DE CAMPEÕES ATIVO' : 'RECONHECIMENTO DE CAMPEÕES INATIVO')+
      ' <i>·</i> '+(state?.trait_model_active ? 'RETRATOS DE SINERGIA ATIVOS' : 'RETRATOS DE SINERGIA INATIVOS')+
      ' <i>·</i> '+(state?.tip?.learned_ranker ? 'DICA NEURAL APLICADA' :
        state?.strategic_model_loaded ? 'MODELO ESTRATÉGICO CARREGADO · DICAS POR REGRAS' :
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
      const controls = document.querySelector('.capture-controls');
      if (controls && !controls.querySelector('#terminal-toggle'))
        controls.insertAdjacentHTML('beforeend', `<button class="text-button" id="terminal-toggle">${terminalMode ? 'Painel completo' : 'Modo leve'}</button>`);
      // Design samples must not look like observed champions in the live view.
      for (const node of document.querySelectorAll('#main > .page-enter > .section-title, #main > .page-enter > .roster, #main > .page-enter > .insight-strip'))
        node.style.display = 'none';
      const arena = document.querySelector('.panel .arena');
      if (arena) arena.outerHTML = `<div class="live-preview">${state && state.session_id ?
        `<canvas id="live-preview-canvas" width="960" height="540" role="img" aria-label="Vídeo em movimento com as marcações do tabuleiro e das leituras"></canvas>`+
        `<canvas id="live-preview-overlay" width="960" height="540" aria-hidden="true"></canvas>` : ''}`+
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
        `Captura ${state.phase} · vídeo anotado pelas camadas de leitura` : 'Captura ainda não iniciada';
      const play = document.querySelector('#preview-play');
      if (play) {
        const active = !!(state?.session_id && state.phase !== 'finished');
        play.innerHTML = icon(active ? 'pause':'play');
        play.setAttribute('aria-label', active ? 'Encerrar sessão':'Escolher fonte para iniciar');
      }
      const source = document.querySelector('#source-name');
      if (source) source.textContent = selected?.label ||
        (state?.session_id && state?.source_label) || 'Nenhuma fonte selecionada';
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

  let refreshInFlight = false;
  async function refresh() {
    if (!api() || refreshInFlight) return;
    refreshInFlight = true;
    try {
      const next = await api().state();
      if (state && state.session_id !== next.session_id) ratedTips.clear();
      // A new tip only repaints the coach. Reloading the page's <img> on every
      // observation would tear down the MJPEG stream and cause visible stalls.
      const changed = !state || state.session_id !== next.session_id ||
        (current !== 'studio' && (state.phase !== next.phase || state.error !== next.error)) ||
        (current === 'board' && (JSON.stringify(state.visual_readiness) !== JSON.stringify(next.visual_readiness) ||
          JSON.stringify(state.temporal_candidates) !== JSON.stringify(next.temporal_candidates))) ||
        (current === 'history' && (state.history?.length || 0) !== (next.history?.length || 0)) ||
        (current === 'learning' && JSON.stringify(state.counts) !== JSON.stringify(next.counts));
      state = next;
      if (changed) render(current);
      else {
        if (!terminalMode) connectedCoach();
        renderLiveDiagnostics();
        document.querySelector('#footer-context').textContent = state.session_id ?
          `Quadros ${state.counts?.source_frames || 0} · HUB ${state.counts?.hub_results || 0} · dicas ${state.counts?.replay_tips || 0}` :
          'Captura Rust · análise local · aprendizado pós partida';
        const now = performance.now();
        while (previewDrawTimes.length && previewDrawTimes[0] < now - 1000)
          previewDrawTimes.shift();
        const status = document.querySelector('.capture-controls small');
        if (status && state.session_id) status.textContent = state.phase === 'finished' ?
          `Replay concluído · último quadro visível · HUB ${state.counts?.hub_results || 0}` :
          `Captura ${state.phase} · prévia exibida ${previewDrawTimes.length} FPS · HUB ${state.counts?.hub_results || 0}`;
      }
      // The final inference can arrive after the final JPEG. Refresh its
      // annotations without decoding or repainting the video again.
      if (current === 'studio' && state.phase === 'finished' &&
          Number.isFinite(displayedSourceMs)) {
        const canvas = document.querySelector('#live-preview-overlay');
        const context = canvas?.getContext('2d');
        if (context && canvas.width && canvas.height) {
          context.clearRect(0, 0, canvas.width, canvas.height);
          drawLiveOverlay(context, canvas, displayedSourceMs, state.yolo_overlay);
        }
      }
      if (!state.profile && !profilePrompted) {
        profilePrompted = true;
        document.querySelector('#detail-content').innerHTML = profileForm(null);
        document.querySelector('#detail-dialog').showModal();
      }
    } catch (error) { toast('Não foi possível consultar o motor local: '+clean(error)); }
    finally { refreshInFlight = false; }
  }
  // Fast readers publish independently; do not make the display wait for a
  // full board pass or an extra half second before showing their snapshots.
  setInterval(refresh, 250);
  refresh();

  setInterval(() => {
    if (!state?.session_id || state.phase === 'finished') return;
    const now = performance.now();
    while (previewDrawTimes.length && previewDrawTimes[0] < now - 1000)
      previewDrawTimes.shift();
    const gaps = previewDrawTimes.slice(1).map((time, index) => time - previewDrawTimes[index]);
    const sinceLast = previewDrawTimes.length ? now - previewDrawTimes.at(-1) : 1000;
    const longestGap = Math.min(5000, Math.max(sinceLast, ...gaps, 0));
    api().report_preview_metrics(previewDrawTimes.length, longestGap).catch(() => {});
  }, 2000);

  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'terminal-toggle') {
      terminalMode = !terminalMode;
      document.body.classList.toggle('terminal-mode', terminalMode && current === 'studio');
      button.textContent = terminalMode ? 'Painel completo' : 'Modo leve';
      renderLiveDiagnostics();
      return;
    }
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
      const replayMode = document.querySelector('#studio-replay-mode');
      if (replayMode) replayMode.checked = selected?.kind === 'video';
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
