# Release Checklist

Checklist pratica per preparare `sortdocs` a un rilascio locale o a una prima condivisione del progetto.

## Prima Del Tag

- verifica che `.env` non sia versionato
- controlla `pyproject.toml` e `src/sortdocs/__init__.py` per la versione
- aggiorna `README.md` se il flusso CLI e cambiato
- verifica `sortdocs.example.yaml`

## Verifiche Tecniche

Esegui:

```bash
make test
make lint
```

Verifica anche il comando reale:

```bash
hash -r
sortdocs . --dry-run
```

## Packaging

Verifica che il console script sia presente:

```bash
.venv/bin/sortdocs --help
```

Verifica il launcher nel `PATH`:

```bash
bash scripts/install-path.sh
hash -r
sortdocs --help
```

## Controlli Manuali Consigliati

- run su una cartella piccola con `--dry-run`
- run confermato su una cartella di test
- verifica collisioni nome
- verifica PDF con testo
- verifica PDF-scansione
- verifica file gia correttamente posizionati

## Post-Rilascio

- annota i casi reali che hanno prodotto review non attese
- aggiorna le euristiche o il prompt AI solo dopo aver raccolto esempi concreti
- valuta una pulizia o migrazione della memoria locale se cambi la strategia di path
