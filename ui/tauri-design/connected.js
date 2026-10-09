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
  function drawYoloOverlay(context, canvas, frameSourceMs, overlay) {
    if (!overlay || !Number.isFinite(overlay.processing_ms)) return;
    const source = overlay.source_size || [1920, 1080];
    const sx = canvas.width / source[0], sy = canvas.height / source[1];
    const age = Math.max(0, (Date.now() - overlay.received_at_ms) / 1000);
    // The video keeps moving between inference results. Never pair a result
    // with a frame from before it, or retain boxes after they have gone stale.
    const lagMs = frameSourceMs - overlay.source_ms;
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
    for (const row of rows) {
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
    const header = `YOLO ${Math.round(overlay.processing_ms)} ms · `+
      `${rows.length} caixas · vídeo ${(frameSourceMs/1000).toFixed(1)} s · `+
      `leitura ${current ? (lagMs/1000).toFixed(1)+' s' : 'aguardando'} · há ${age.toFixed(1)} s`;
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
    const canvas = document.querySelector('#live-preview-canvas');
    const overlayCanvas = document.querySelector('#live-preview-overlay');
    if (!canvas || !overlayCanvas) return;
    const generation = previewGeneration;
    const context = canvas.getContext('2d', {alpha: false, desynchronized: true});
    const overlayContext = overlayCanvas.getContext('2d', {alpha: true});
    if (!context || !overlayContext) return;
    let after = 0, errors = 0, lastOverlayKey = '';
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
          const frameSourceMs = Number(response.headers.get('X-Frame-Source-Ms'));
          if (!Number.isSafeInteger(sequence) || sequence <= after) throw new Error('Quadro inválido.');
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
            const overlayKey = `${overlay?.source_ms}:${current}:${Math.floor(frameSourceMs / 1000)}`;
            if (overlayKey !== lastOverlayKey) {
              overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
              drawYoloOverlay(overlayContext, overlayCanvas, frameSourceMs, overlay);
              lastOverlayKey = overlayKey;
            }
            canvas.closest('.live-preview')?.classList.add('yolo-analysis-ready');
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
      if (arena) arena.outerHTML = `<div class="live-preview">${state && state.session_id ?
        `<canvas id="live-preview-canvas" width="960" height="540" role="img" aria-label="Vídeo em movimento com as marcações do YOLO"></canvas>`+
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
        `Captura ${state.phase} · vídeo anotado pelo YOLO` : 'Captura ainda não iniciada';
      const play = document.querySelector('#preview-play');
      if (play) {
        play.innerHTML = icon(state && state.session_id ? 'pause':'play');
        play.setAttribute('aria-label', state && state.session_id ? 'Encerrar sessão':'Escolher fonte para iniciar');
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
        connectedCoach();
        document.querySelector('#footer-context').textContent = state.session_id ?
          `Quadros ${state.counts?.source_frames || 0} · HUB ${state.counts?.hub_results || 0} · dicas ${state.counts?.replay_tips || 0}` :
          'Captura Rust · análise local · aprendizado pós partida';
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
    finally { refreshInFlight = false; }
  }
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
