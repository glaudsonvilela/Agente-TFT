'use strict';
// The installed VM assistant uses the exact designer artwork and structure.
// Every status below comes from the local installer; the prototype's demo
// download, restart and success controls are never shown in this mode.
if (new URLSearchParams(location.search).has('realInstaller')) {
  document.body.classList.add('real-installer');
  let actual = {phase: 'checking', messages: []};
  let headless = false;
  let busy = false;
  const safe = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const api = async (method, ...args) => {
    const response = await fetch(new URL(`api/${method}`, location.href), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({args}), cache: 'no-store'
    });
    const value = await response.json();
    if (!response.ok || !value.ok) throw new Error(value.error || 'A instalação não respondeu.');
    return value.result;
  };
  const step = () => actual.phase === 'ready' ? 5 : actual.phase === 'restart' ? 4 :
    actual.phase === 'installing' ? 3 : actual.phase === 'ready_to_install' ? 2 : 1;
  const log = () => `<div class="real-install-log" role="log" aria-label="Etapas da instalação">${
    (actual.messages || []).slice(-6).map(row => `<div>${safe(row)}</div>`).join('') ||
    '<div>Verificando o pacote incluído no instalador…</div>'}</div>`;
  function content() {
    if (actual.phase === 'ready') return `<div class="success-mark">✓</div><span class="step-label">05 / 05 · INSTALAÇÃO CONCLUÍDA</span>`+
      `<h2>Seu estúdio<br><em>está pronto.</em></h2><p>A VM passou no teste de saúde e de conexão IP local. O atalho foi criado na área de trabalho.</p>${log()}`;
    if (actual.phase === 'restart') return `<span class="step-label">04 / 05 · REINÍCIO NECESSÁRIO</span>`+
      `<h2>Falta só<br>reiniciar.</h2><p>Salve seu trabalho. Após o próximo login, o assistente retomará a instalação da VM automaticamente.</p>${log()}`;
    if (actual.phase === 'error') return `<span class="step-label">ETAPA INTERROMPIDA</span>`+
      `<h2>Vamos corrigir<br>esta etapa.</h2><p>${safe(actual.error)}</p>${log()}`+
      `<p class="note">Registro: ${safe(actual.log_path)}</p>`;
    if (actual.phase === 'installing') return `<span class="step-label">03 / 05 · INSTALANDO E TESTANDO A VM</span>`+
      `<h2>Seu estúdio<br>está tomando forma.</h2><p>Importando a VM e conferindo modelo, catálogo e conexão IP local. Esta etapa pode levar alguns minutos.</p>`+
      `<div class="real-install-busy" aria-label="Instalação em andamento"></div>${log()}`;
    if (actual.phase === 'ready_to_install') return `<span class="step-label">02 / 05 · PACOTE VERIFICADO</span>`+
      `<h2>Tudo incluído.<br>Pronto para instalar.</h2><p>O aplicativo Windows já foi extraído. A VM está dentro deste instalador e teve sua integridade verificada.</p>`+
      `<label class="real-install-option"><input id="real-headless" type="checkbox" ${headless?'checked':''}> Desativar WSLg para evitar janelas Remote Desktop. Isso também afeta outros aplicativos Linux com interface gráfica após reiniciar.</label>${log()}`;
    return `<span class="step-label">01 / 05 · VERIFICAR O COMPUTADOR</span>`+
      `<h2>Um bom começo<br>faz a diferença.</h2><p>Conferindo Windows, espaço, memória, WSL 2 e integridade da VM incluída.</p>`+
      `<div class="real-install-busy" aria-label="Verificação em andamento"></div>${log()}`;
  }
  function realInstaller() {
    const index = step();
    const names = ['Bem-vindo', 'Verificação', 'Pacote', 'Configuração', 'Reinício', 'Tudo pronto'];
    const action = actual.phase === 'ready_to_install' ? 'Instalar VM' : actual.phase === 'restart' ?
      'Reiniciar agora' : actual.phase === 'ready' ? 'Abrir Agente TFT' : actual.phase === 'error' ?
      'Tentar novamente' : 'Aguarde…';
    return `<div class="page-head"><div><span class="eyebrow">INSTALAÇÃO GUIADA · WINDOWS + VM LOCAL</span>`+
      `<h1>Pronto para <em>o próximo nível.</em></h1><p>Etapas reais de instalação com acompanhamento ao vivo.</p></div></div>`+
      `<div class="installer-stage"><aside class="installer-art"><div class="install-brand"><img src="assets/agente-pengu.png" alt=""> AGENTE TFT</div>`+
      `<div class="art-orbit"></div><img class="install-pengu" src="assets/pengu.png" alt="Pengu de Teamfight Tactics">`+
      `<h2>Aprenda com<br>cada jogada.</h2><p>Um olhar mais claro sobre o seu próprio jogo.</p>`+
      `<small>ESTÚDIO DE REPLAY · COMUNIDADE TFT</small></aside>`+
      `<div class="installer-body"><div class="install-progress" aria-label="Etapa ${index+1} de 6">${names.map((name,i) =>
        `<span title="${name}" class="${i<index?'complete':i===index?'current':''}"></span>`).join('')}</div>`+
      `<div class="install-content" aria-live="polite">${content()}</div>`+
      `<div class="install-actions"><button class="secondary" id="real-close">Fechar</button>`+
      `<button class="primary" id="real-next" ${busy || ['checking','installing'].includes(actual.phase)?'disabled':''}>${action} <span>→</span></button></div>`+
      `</div></div>`;
  }
  renderers.installer = realInstaller;
  render('installer');
  document.querySelector('.sidebar-footer').innerHTML = '<span class="status-dot"></span> INSTALAÇÃO REAL <span>01.0</span>';
  document.querySelector('.statusbar>span').innerHTML = '<span class="status-dot"></span> INSTALADOR LOCAL <i>·</i> VM INCLUÍDA';
  async function refresh() {
    try {
      const value = await api('state');
      if (JSON.stringify(value) !== JSON.stringify(actual)) {
        actual = value;
        render('installer');
      }
    } catch (error) { toast('Falha ao consultar a instalação: '+error.message); }
  }
  setInterval(refresh, 900);
  refresh();
  document.addEventListener('change', event => {
    if (event.target.id === 'real-headless') headless = event.target.checked;
  }, true);
  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button || !['real-next','real-close'].includes(button.id)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (busy) return;
    busy = true;
    button.disabled = true;
    try {
      if (button.id === 'real-close') {
        await api('close');
        window.close();
      } else if (actual.phase === 'ready_to_install') await api('install', headless);
      else if (actual.phase === 'error') await api('retry');
      else if (actual.phase === 'restart') {
        if (confirm('Salvou seu trabalho? O Windows será reiniciado agora.')) await api('restart');
      } else if (actual.phase === 'ready') {
        await api('launch');
        window.close();
      }
      await refresh();
    } catch (error) { toast(error.message); }
    finally { busy = false; button.disabled = false; }
  }, true);
}
