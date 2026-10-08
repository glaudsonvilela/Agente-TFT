# Tom da voz no coach

As dicas continuam sendo decisões locais do motor. O cliente envia ao serviço
apenas o texto e um tom escolhido pelo tipo de ação: `urgent` para rolagem,
`thoughtful` para economia e `confident` para as demais ações. O tom não muda a
ação, não vira rótulo de treinamento e não aparece na interface.

O serviço valida o tom e só insere Audio Tags antes do texto quando
`ELEVENLABS_MODEL_ID` é `eleven_v3`, `eleven_v4` ou `eleven_v4_turbo`. O padrão
permanece `eleven_flash_v2_5`; nesse modelo as tags não são enviadas para a
ElevenLabs, pois poderiam sair como palavras faladas. A escolha do modelo fica
no servidor. O cache de áudio inclui modelo e tom, para não misturar versões.

Em uma prévia isolada da voz já configurada, `eleven_v4_turbo` aceitou tags em
português e retornou PCM. Duas chamadas levaram 1,2 s e 2,6 s para gerar o
áudio completo; uma chamada comparável com Flash levou 0,8 s. Isso mede apenas
essas requisições, não a latência ponta a ponta da dica. A troca do modelo deve
ser acompanhada pelos tempos da sessão e por escuta antes de ser distribuída.

Audio Tags são um recurso de interpretação vocal. Elas não substituem leitura
de tabuleiro, identificação de campeões ou raciocínio estratégico.
