'use strict';
const step = document.querySelector('#bootstrap-step');
const title = document.querySelector('#bootstrap-title');
const description = document.querySelector('#bootstrap-description');
const statusLine = document.querySelector('#bootstrap-status');
const busy = document.querySelector('#bootstrap-busy');
const errorLine = document.querySelector('#bootstrap-error');
const closeButton = document.querySelector('#bootstrap-close');
const progress = [...document.querySelectorAll('.install-progress span')];
let redirected = false;
let failures = 0;
closeButton.addEventListener('click', () => window.close());
async function refresh() {
  if (redirected) return;
  try {
    const response = await fetch('api/state', {cache: 'no-store'});
    if (!response.ok) throw new Error('O instalador local parou de responder.');
    const state = await response.json();
    failures = 0;
    if (state.phase === 'handoff') {
      if (!/^http:\/\/127\.0\.0\.1:\d+\/[A-Za-z0-9_-]+\//.test(state.url || ''))
        throw new Error('Endereço do assistente local inválido.');
      redirected = true;
      location.replace(state.url);
      return;
    }
    const phases = {
      verifying: ['01 / 05 · VERIFICANDO O PACOTE', 'Tudo incluído.<br>Conferindo agora.', 'Verificando a integridade do aplicativo e da VM antes de instalar.', 0],
      extracting: ['02 / 05 · PREPARANDO A INSTALAÇÃO', 'Seu estúdio<br>está tomando forma.', 'Preparando o pacote Windows para instalação. O progresso continua nesta janela.', 1],
      installing: ['03 / 05 · INSTALANDO O APLICATIVO', 'Mais perto da<br>próxima jogada.', 'Instalando o aplicativo, criando os atalhos e preparando a VM incluída.', 2],
      starting: ['04 / 05 · ABRINDO A CONFIGURAÇÃO', 'Vamos verificar<br>a VM local.', 'Abrindo o assistente que testa o ambiente e explica cada etapa.', 3],
      error: ['ETAPA INTERROMPIDA', 'Precisamos corrigir<br>esta etapa.', 'A instalação foi interrompida. O motivo e o registro estão abaixo.', 0]
    };
    const [label, heading, detail, index] = phases[state.phase] || phases.verifying;
    step.textContent = label; title.innerHTML = heading; description.textContent = detail;
    statusLine.textContent = state.message || 'Aguarde…';
    progress.forEach((part, n) => part.className = n < index ? 'complete' : n === index ? 'current' : '');
    if (state.phase === 'error') { busy.hidden = true; errorLine.hidden = false; errorLine.textContent = state.error || 'Veja o registro da instalação.'; closeButton.hidden = false; }
  } catch (error) {
    if (++failures >= 3) { busy.hidden = true; errorLine.hidden = false; errorLine.textContent = String(error); closeButton.hidden = false; }
  }
}
setInterval(refresh, 350);
refresh();
