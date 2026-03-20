# sortdocs

`sortdocs` e un organizer CLI in Python per macOS che riordina documenti locali in base al contenuto del file, ai metadati e alla classificazione tramite OpenAI.

Il flusso e pensato per essere semplice:

1. entri nella cartella da riordinare
2. lanci `sortdocs .`
3. il tool scansiona ricorsivamente, mostra il piano e chiede conferma
4. se confermi, sposta e rinomina i file in modo sicuro

## Caratteristiche

- CLI installabile come comando `sortdocs`
- scansione ricorsiva di default
- supporto iniziale per `pdf`, `txt`, `md`, `jpg`, `png`, `docx`
- classificazione con OpenAI Responses API
- output terminale leggibile con piano e riepilogo
- guardrail su rename, estensioni, path traversal e collisioni
- fallback prudente per file poco leggibili o ambigui
- memoria locale per riusare meglio i path gia scelti

## Requisiti

- macOS
- Python 3.11+
- `OPENAI_API_KEY`

## Installazione

### Con `uv`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
uv sync --extra dev
```

### Con `pip`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Comando Nel PATH

Per usare `sortdocs` come comando globale:

```bash
bash scripts/install-path.sh
hash -r
```

Il launcher viene installato in una directory gia presente nel tuo `PATH` e richiama la `.venv` del progetto.

Dopo l’installazione puoi usare:

```bash
cd ~/Documents
sortdocs .
```

Nota utile:

- il launcher installato da `scripts/install-path.sh` carica automaticamente il file `.env` del progetto se esiste
- se usi direttamente `.venv/bin/sortdocs`, invece, devi esportare tu la variabile `OPENAI_API_KEY`

## Configurazione OpenAI

Parti dal file di esempio:

```bash
cp .env.example .env
```

Poi imposta la chiave:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

## Uso Quotidiano

### Flusso predefinito

```bash
cd ~/Documents
sortdocs .
```

Questo comando:

- scansiona ricorsivamente la cartella
- analizza i file supportati
- mostra il piano delle azioni
- chiede `Proceed with these actions?`
- applica le modifiche solo se confermi

### Anteprima senza modifiche

```bash
sortdocs . --dry-run
```

### Limite numero file

```bash
sortdocs . --max-files 50
```

### Scansione non ricorsiva

```bash
sortdocs . --no-recursive
```

### Salta il prompt di conferma

```bash
sortdocs . --yes
```

### Dettagli tecnici nei log

```bash
sortdocs . --verbose
```

In modalita normale, `sortdocs` mostra soprattutto piano e riepilogo finale. I log `INFO` interni del client AI sono nascosti di default per non sporcare l’output.

## File Di Configurazione

Puoi creare un file `sortdocs.yaml` o `.sortdocs.yaml` nella directory corrente, oppure passarlo con `--config`.

Esempio minimo:

```yaml
cli:
  dry_run: false
  recursive_default: true
  review_dir: "."
  library_dir: "."
  max_files_per_run: 100

extraction:
  max_excerpt_chars: 4000

openai:
  model: "gpt-4.1-mini"
  temperature: 0.1

planner:
  confidence_threshold: 0.65
  folder_pattern: "{category}/{subcategory}"

logging:
  level: INFO
```

Campi principali:

- `cli.dry_run`
- `cli.recursive_default`
- `cli.review_dir`
- `cli.library_dir`
- `cli.max_files_per_run`
- `extraction.max_excerpt_chars`
- `openai.model`
- `openai.temperature`
- `planner.confidence_threshold`
- `planner.allowed_categories`
- `planner.folder_pattern`
- `logging.level`

Pattern supportati per le cartelle target:

- `{category}/{subcategory}`
- `{category}`
- `{year}/{category}`

Vedi anche [sortdocs.example.yaml](/Users/davdifr/Workspace/sortdocs/sortdocs.example.yaml).

## Comportamento Del Planner

Per default `sortdocs` lavora direttamente nella cartella che gli passi:

- non crea automaticamente `Library/` e `Review/` separate
- crea nuove sottocartelle quando servono
- prova a riusare cartelle esistenti quando il contesto e equivalente
- evita collisioni aggiungendo suffissi incrementali
- non sovrascrive mai file esistenti

Per file con evidenza debole:

- abbassa la confidence
- puo lasciare il file in posizione con `skip` o `review`
- usa fallback visuale per PDF-scansione quando non c’e testo estraibile

## Logging

Comportamento predefinito:

- output centrato sul piano e sul riepilogo
- warning ed errori importanti visibili
- log informativi interni del client AI nascosti

Se vuoi vedere i dettagli tecnici:

```bash
sortdocs . --verbose
```

## Troubleshooting

### `sortdocs: command not found`

- esegui `bash scripts/install-path.sh`
- poi esegui `hash -r`
- in alternativa usa `.venv/bin/sortdocs`

### `OPENAI_API_KEY is not set`

- crea `.env` a partire da `.env.example`
- se usi il launcher globale, `.env` viene caricato automaticamente
- se usi `.venv/bin/sortdocs`, fai:

```bash
set -a
source .env
set +a
```

### Il piano non e quello atteso

- prova prima `sortdocs . --dry-run`
- se vuoi limitare il batch, usa `--max-files`
- se vuoi piu contesto tecnico, usa `--verbose`

### Alcuni PDF non hanno testo

`sortdocs` prova prima l’estrazione testuale. Se il PDF e una scansione, puo usare un fallback visuale via OpenAI per classificare comunque il file in modo prudente.

## Sviluppo Locale

Installazione dipendenze:

```bash
make install
```

Test:

```bash
make test
```

Lint:

```bash
make lint
```

Esempio rapido:

```bash
make run-example INPUT=~/Documents/Inbox
```

## Stato Del Progetto

Il progetto e pronto per uso locale su macOS come MVP production-minded:

- pipeline completa `scan -> extract -> classify -> plan -> execute`
- test unitari ed end-to-end
- launcher nel `PATH`
- output terminale leggibile
- guardrail su operazioni filesystem

Per una checklist di rilascio locale vedi [docs/release-checklist.md](/Users/davdifr/Workspace/sortdocs/docs/release-checklist.md).
