# shadow-player

Mantém uma **linha simulada contínua** entre checkpoints reais.

```text
real GameState rev 100
        ↓ reset
shadow state rev 100
        ↓ Action A
shadow rev 101
        ↓ Action B
shadow rev 102

real GameState rev 101 chega
        ↓
divergence
        ↓
reconcile/reset
        ↓
shadow continua do real rev 101
```

O crate não controla o cliente TFT. Ele executa ações apenas através de um backend que implemente `ShadowSimulator`.

Isso permite testar uma policy como se ela estivesse jogando continuamente, mantendo a realidade como checkpoint de reconciliação.
