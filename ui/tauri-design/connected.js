'use strict';
// Runs only inside the installed WebView2 shell. The design preview remains
// independently navigable and keeps its illustrative labels.
if (new URLSearchParams(location.search).has('connected')) {
  const originalRender = render;
  let sourceRows = [], selected = null, state = null, starting = false, profilePrompted = false;
  const api = () => window.pywebview && window.pywebview.api;
  const clean = value => String(value == null ? '' : value);
  const escapeHtml = value => clean(value).replace(/[&<>"']/g, ch =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const livePath = new URL('preview.mjpg', location.href).pathname;
  const regions = ['BR','NA','LAN','LAS','EUW','EUNE','KR','JP','OCE','TR','RU','SEA','TW','VN'];
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
    const actionable = !!(tip && tip.actionable && (tip.age_ms == null || tip.age_ms <= 3000));
    const label = actionable ? 'DICA AGORA' : 'LEITURA EM ANDAMENTO';
    document.querySelector('.coach-label').innerHTML = `<span>AGORA</span><span class="pill mini">${label}</span>`;
    const title = actionable ? tip.text :
      (tip && tip.text && tip.age_ms <= 3000 ? tip.text : 'Aguardando uma leitura confiável.');
    const recommendations = actionable ? (tip.recommendations || []) : [];
    card.innerHTML = `<div class="advice-type">${icon(actionable?'growth':'eye')} ${label}</div>`+
      `<h2>${escapeHtml(title)}</h2>`+
      `<p>${actionable ? 'Decisão baseada na observação recente da sua tela.' :
                     'O Agente só orienta quando há evidência suficiente.'}</p>`+
      `<div class="advice-explanation" style="display:block">`+
      `Patch dos dados: ${escapeHtml(tip && tip.data_patch || 'a confirmar')}`+
      `${tip && tip.data_patch_basis==='bundled_catalog_patch_lab' ? ' (catálogo local de laboratório)' : ''} · `+
      `Idade da leitura: ${tip && Number.isFinite(tip.age_ms) ? Math.round(tip.age_ms)+' ms' : '—'}`+
      `${recommendations.length ? '<br>'+recommendations.map(x => escapeHtml(x.text)).join('<br>') : ''}`+
      `</div>`;
    document.querySelector('.coach-footnote').textContent =
      state && state.error ? 'Erro: '+state.error :
      state && state.session_id ? 'Sessão '+state.session_id.slice(0,8)+' · '+state.phase :
      'Escolha a tela para iniciar a captura local.';
    const voice = state && state.voice;
    document.querySelector('#voice-label').textContent =
      voice && voice.error ? 'Voz indisponível' : voice && voice.enabled ?
      'ElevenLabs · voz conectada' : 'Voz aguardando conexão';
    document.querySelector('.voice-strip small').textContent = 'ElevenLabs · português BR';
    document.querySelector('#play-voice').setAttribute('aria-label', 'Estado da voz');
    const audio = document.querySelector('#voice-audio');
    if (audio) audio.removeAttribute('src');
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
      ' <i>·</i> '+(state?.strategic_model_loaded ? 'ESTRATÉGIA NEURAL' : 'ESTRATÉGIA POR REGRAS');
    document.querySelector('#footer-context').textContent =
      state && state.session_id ? `Quadros ${state.counts?.source_frames || 0} · HUB ${state.counts?.hub_results || 0} · dicas ${state.counts?.replay_tips || 0}` :
      'Captura Rust · análise local · aprendizado pós partida';
    document.querySelector('.workspace-pill').innerHTML =
      '<span class="status-dot"></span> '+(state?.replay_review ? 'Revisão de replay':'Estúdio ao vivo')+
      ' <span class="dim">/</span> <b>Laboratório</b>';
    const installerLink = document.querySelector('.sidebar-bottom button[data-route="installer"]');
    if (installerLink) installerLink.style.display = 'none';
    if (current === 'studio') {
      const arena = document.querySelector('.panel .arena');
      if (arena) arena.outerHTML = `<div class="live-preview">${state && state.preview_sequence > 0 ?
        `<img src="${livePath}" alt="Prévia da fonte selecionada" />` : ''}`+
        `<div class="live-preview-empty">${state && state.session_id ? 'Aguardando o primeiro quadro da captura…' : 'Selecione um monitor ou janela para acompanhar.'}</div></div>`;
      const status = document.querySelector('.capture-controls small');
      if (status) status.textContent = state && state.session_id ?
        `Captura ${state.phase} · prévia local até 720p` : 'Captura ainda não iniciada';
      const play = document.querySelector('#preview-play');
      if (play) {
        play.innerHTML = icon(state && state.session_id ? 'pause':'play');
        play.setAttribute('aria-label', state && state.session_id ? 'Encerrar sessão':'Escolher fonte para iniciar');
      }
      const source = document.querySelector('#source-name');
      if (source) source.textContent = selected ? selected.label : 'Nenhuma fonte selecionada';
    }
    if (current === 'board') {
      const arena = document.querySelector('.board-detail .arena');
      const readiness = state?.visual_readiness;
      const boardStatus = readiness ?
        `${readiness.observed_unit_regions || 0} regiões observadas · ${readiness.candidate_units || 0} candidatos · ${readiness.verified_units || 0} unidades confirmadas` :
        'Aguardando a primeira leitura do tabuleiro.';
      if (arena) arena.outerHTML = `<div class="live-board-empty"><div>Posições e campeões ainda não confirmados nesta sessão.<br><small>${escapeHtml(boardStatus)}</small></div></div>`;
      const inventory = document.querySelector('.board-detail .inventory');
      if (inventory) inventory.innerHTML = '<span>Inventário · aguardando identificação confiável</span>';
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
      if (description) description.textContent = 'Dicas atuais por ElevenLabs, reproduzidas no Windows.';
    }
    connectedCoach();
  }

  render = function(route) { originalRender(route); connectedPage(); };
  render(current);

  async function refresh() {
    if (!api()) return;
    try {
      const next = await api().state();
      // A new tip only repaints the coach. Reloading the page's <img> on every
      // observation would tear down the MJPEG stream and cause visible stalls.
      const changed = !state || state.session_id !== next.session_id ||
        state.phase !== next.phase || state.error !== next.error ||
        ((state.preview_sequence || 0) === 0 && next.preview_sequence > 0) ||
        (current === 'board' && JSON.stringify(state.visual_readiness) !== JSON.stringify(next.visual_readiness)) ||
        (current === 'history' && (state.history?.length || 0) !== (next.history?.length || 0)) ||
        (current === 'learning' && JSON.stringify(state.counts) !== JSON.stringify(next.counts));
      state = next;
      if (changed) render(current);
      else {
        connectedCoach();
        const status = document.querySelector('.capture-controls small');
        if (status && state.session_id) status.textContent =
          `Captura ${state.phase} · prévia codificada ${state.preview_encoded_fps || 0} FPS · HUB ${state.counts?.hub_results || 0}`;
      }
      if (!state.profile && !profilePrompted) {
        profilePrompted = true;
        document.querySelector('#detail-content').innerHTML = profileForm(null);
        document.querySelector('#detail-dialog').showModal();
      }
    } catch (error) { toast('Não foi possível consultar o motor local: '+clean(error)); }
  }
  setInterval(refresh, 900);
  refresh();

  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'choose-source') {
      event.stopImmediatePropagation();
      try { sourceRows = await api().list_sources(); }
      catch (error) { toast('Falha ao listar fontes: '+clean(error)); return; }
      const dialog = document.querySelector('#source-dialog');
      dialog.querySelector('p').textContent =
        'Ao iniciar, você autoriza a captura local desta fonte. Partidas ao vivo podem ser enviadas para aprendizado após o encerramento; replays não são enviados.';
      dialog.querySelector('.source-options').innerHTML = sourceRows.map((row, index) =>
        `<button class="source-option ${index===0?'selected':''}" data-source-index="${index}" aria-pressed="${index===0}">`+
        `<span data-icon="${row.kind==='monitor'?'monitor':'window'}"></span><b>${escapeHtml(row.label)}</b>`+
        `<small>${row.candidate_tft?'Possível janela TFT':'Fonte disponível'}</small><i>✓</i></button>`).join('');
      selected = sourceRows[0] || null;
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
      return;
    }
    if (button.dataset.sourceIndex != null) {
      event.stopImmediatePropagation();
      selected = sourceRows[Number(button.dataset.sourceIndex)];
      document.querySelectorAll('.source-option').forEach(el => {
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
      } catch (error) { toast('Captura não iniciada: '+clean(error)); }
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
      toast(state?.voice?.error || 'A voz narra apenas dicas atuais confirmadas.');
      return;
    }
    if (button.dataset.pref === 'voice') {
      event.stopImmediatePropagation();
      const enabled = button.getAttribute('aria-checked') !== 'true';
      const response = await api().set_voice(enabled);
      preferences.voice = response.enabled;
      button.setAttribute('aria-checked', String(response.enabled));
      toast(response.enabled ? 'Voz ativada.' : 'Voz desativada.');
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
