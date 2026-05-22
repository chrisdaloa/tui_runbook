# Demo Runbook

Un runbook di esempio per testare l'MVP localmente.

## Stampa messaggio di benvenuto

Verifica che l'output di testo funzioni correttamente.

```bash
echo "=== Runbook avviato ==="
echo "Data: $(date)"
echo "Utente: $(whoami)"
echo "Directory: $(pwd)"
```

## Saluta l'utente

<!-- runbook:rollback: echo "Operazione annullata per ${NAME}" -->

Usa la variabile `${NAME}` per personalizzare il messaggio.

```bash
echo "Ciao, ${NAME}!"
echo "Benvenuto nel runbook interattivo."
```

## Conferma manuale

<!-- runbook:manual -->

Verifica visivamente che i passi precedenti abbiano prodotto l'output atteso,
poi premi `r` per confermare e procedere.

```bash
echo "conferma avvenuta"
```

## Elaborazione multi-step

<!-- runbook:rollback: echo "Rollback elaborazione: ripristino stato iniziale" -->

Simula un'operazione che richiede qualche secondo.

```bash
echo "Fase 1/3: preparazione..."
sleep 1
echo "Fase 2/3: elaborazione..."
sleep 1
echo "Fase 3/3: completamento..."
echo "Fatto."
```

## Step che fallisce intenzionalmente

Questo step termina con exit code 1 per mostrare la gestione degli errori.

```bash
echo "Questo comando sta per fallire..."
echo "Errore simulato" >&2
exit 1
```
