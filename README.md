# ⚡ PC Analyzer

Applicazione desktop per Windows in stile CPU-Z che:

- **rileva tutti i componenti**: CPU (core, thread, cache, socket), scheda madre e BIOS, RAM (ogni modulo con produttore, part number e frequenza), schede video (VRAM reale), SSD/HDD (NVMe/SATA, capacità, spazio libero, stato di salute), sistema operativo;
- **assegna un voto da 1 a 5 (con mezzi voti)** alla build per **Gaming**, **Ufficio**, **Produttività** e un voto **Complessivo**;
- **misura la velocità di Internet** (download, upload, ping, jitter, provider) e assegna un voto alla connessione;
- **controlla se la build è bilanciata** (colli di bottiglia CPU/GPU, RAM, disco, single channel, XMP disattivato…) e **propone upgrade compatibili con i relativi prezzi**, mostrando come cambierebbero i voti;
- **aggiorna i prezzi** in base al mercato (IA con ricerca web oppure listino remoto);
- **integra un'IA opzionale** (Claude di Anthropic) per un'analisi approfondita e per domande libere;
- **sezione Driver**: link ufficiali per driver e BIOS della scheda madre, chipset e scheda video rilevati;
- **si aggiorna da sola da GitHub** e ha uno script per pubblicare le nuove versioni.

Interfaccia con tema **Graphite Ember** (grigio grafite + arancione) e animazioni: transizioni tra le pagine,
voti che contano fino al valore finale, stelle e barre che si riempiono, indicatore del menu che scorre,
notifiche a comparsa. Le animazioni si possono disattivare in *Impostazioni › Aspetto*.

---

## Installazione rapida

Serve **Python 3.10 o superiore** (consigliato 3.12) da [python.org](https://www.python.org/downloads/): durante l'installazione spunta *"Add Python to PATH"*.

1. Estrai la cartella `PCAnalyzer` dove preferisci.
2. Fai doppio clic su **`avvia.bat`**: installa le dipendenze e apre l'app.

Oppure da terminale:

```bat
cd PCAnalyzer
pip install -r requirements.txt
python main.py
```

### Creare l'eseguibile `.exe`

Doppio clic su **`build_exe.bat`**: alla fine trovi `dist\PCAnalyzer\PCAnalyzer.exe` (la cartella `dist\PCAnalyzer` si può copiare su altri PC senza installare Python).

---

## Come funziona

### Rilevamento hardware (`app/hardware.py`)
Un solo script PowerShell (`Get-CimInstance`, `Get-PhysicalDisk`, registro di Windows) legge tutti i dati in formato JSON: niente driver o librerie native, **non servono i permessi di amministratore**. La VRAM viene letta dal registro perché il campo WMI standard si ferma a 4 GB.

### Voti 1-5 (`app/scoring.py` + `data/components_db.json`)
Il database contiene oltre **220 CPU** e **110 GPU** (dal 2011 alle serie Ryzen 9000, Core Ultra 200, RTX 50, RX 9000, Arc B) con indici prestazionali relativi:

| Indice | Riferimento = 100 |
|---|---|
| CPU single-thread / multi-thread | Ryzen 9 9950X |
| CPU gaming | Ryzen 7 9800X3D |
| GPU gaming (1440p) | RTX 5090 |

Ogni componente riceve un punteggio 0-5; i voti finali sono medie pesate con **penalità per il collo di bottiglia** (il componente più debole abbassa il voto), arrotondate al mezzo voto:

| Utilizzo | Pesi |
|---|---|
| Gaming | GPU 55% · CPU 25% · RAM 12% · disco 8% |
| Ufficio | CPU single-thread 40% · RAM 30% · disco 30% |
| Produttività | CPU multi-thread 45% · RAM 20% · GPU 20% · disco 15% |

Se un modello non è nel database viene stimato (generazione, core, thread, VRAM) e l'app lo segnala.
Per aggiungere modelli: modifica `tools/genera_database.py` ed eseguilo, oppure metti un `components_db.json` personalizzato nella cartella dati utente (vedi sotto), che ha la precedenza.

### Bilanciamento e upgrade (`app/balance.py`)
L'algoritmo:
1. confronta CPU e GPU per individuare chi limita l'altra nel gaming;
2. controlla RAM (quantità, single/dual channel, moduli misti, **XMP/EXPO non attivo** letto dal part number), disco di sistema (HDD, SSD piccolo, poco spazio, stato di salute), VRAM;
3. calcola un **punteggio di bilanciamento 0-100** (Bilanciata / Leggermente sbilanciata / Sbilanciata);
4. sceglie dal listino gli upgrade **compatibili** (stesso socket CPU, tipo di RAM DDR4/DDR5, SO-DIMM per portatili, NVMe o SATA) dimensionati sulla build: una GPU proporzionata alla CPU, la CPU più economica che elimina il collo di bottiglia o, se il socket è a fine corsa, un pacchetto **CPU + scheda madre + RAM**;
5. **simula ogni upgrade** e mostra i nuovi voti (es. Gaming 3.0 → 4.0), con stima dell'alimentatore necessario, note sul BIOS e link di ricerca su Amazon.it, Idealo e Trovaprezzi.

Sui portatili non vengono proposte CPU/GPU (non sostituibili), solo RAM e SSD dove possibile.

### Prezzi aggiornati (`app/prices.py` + `data/prices.json`)
Il listino parte con prezzi indicativi e si aggiorna da **Bilanciamento → Aggiorna prezzi** in due modi:
- **✨ IA con ricerca web**: Claude cerca i prezzi correnti sui negozi e comparatori italiani; valori anomali (±60% rispetto al precedente) vengono scartati e l'app mostra la variazione di prezzo;
- **🌐 URL remoto**: un `prices.json` nello stesso formato pubblicato online (es. file *raw* su GitHub), utile per aggiornare più PC insieme.

Il file è modificabile anche a mano (*Impostazioni → Apri file listino*). Se è più vecchio di 30 giorni l'app lo segnala.

### Speed test (`app/speedtest_engine.py`)
Motore predefinito: server **Cloudflare** (latenza e jitter su 12 campioni, download con 6 connessioni parallele, upload con 4, 10 secondi per fase, escludendo il primo secondo). Se è installato `speedtest-cli` compare anche il motore **Ookla**. L'ultimo risultato viene salvato e incluso nel report.

### Assistente IA (`app/ai_advisor.py`)
1. Crea una API key su [console.anthropic.com](https://console.anthropic.com) (servizio a consumo).
2. Incollala in **Impostazioni → API key** e premi *Prova chiave*.
3. Nella sezione **Assistente IA** scegli utilizzo e budget e premi *Analizza con IA*; poi puoi fare domande libere ("con 300 € cosa cambio?").

L'IA riceve solo il riepilogo dell'hardware e i risultati dell'algoritmo, mai file personali. La chiave è salvata in chiaro solo sul tuo PC; in alternativa puoi impostare la variabile d'ambiente `ANTHROPIC_API_KEY`.

---

### Driver e BIOS (`app/drivers.py`)
In base a produttore e modello della scheda madre (ASUS, MSI, Gigabyte, ASRock) l'app costruisce il link diretto
alla pagina download del modello e a quella dei BIOS; per PC di marca e portatili (Dell, HP, Lenovo…) usa il
supporto del produttore del sistema. Per la scheda video propone i driver NVIDIA (con NVIDIA App), AMD
Adrenalin o Intel Arc, e per il chipset i driver AMD Ryzen o Intel Driver & Support Assistant. Segnala anche
un BIOS più vecchio di 2 anni. C'è sempre una ricerca limitata al sito ufficiale come riserva.

---

## Aggiornamenti automatici tramite GitHub

### Prima configurazione (una volta sola, sul tuo PC)
1. Installa **Git** da [git-scm.com/download/win](https://git-scm.com/download/win) (opzioni predefinite).
2. Su GitHub crea un repository **vuoto e pubblico**, ad esempio `PCAnalyzer` (*New repository*, senza README).
3. Nella cartella `PCAnalyzer` fai doppio clic su **`pubblica_aggiornamento.bat`**: alla prima esecuzione chiede
   l'indirizzo del repository (es. `https://github.com/tuonome/PCAnalyzer`), poi versione e novità, e carica
   tutto. La prima volta Git apre il browser per l'accesso a GitHub.

### Pubblicare una nuova versione
1. Modifica i file dell'app (o fatteli modificare da Claude).
2. Doppio clic su **`pubblica_aggiornamento.bat`** → conferma il nuovo numero di versione (es. 1.1.1) e scrivi le novità.
3. Lo script aggiorna `version.json`, fa commit e push su GitHub e crea il tag `v1.1.1`.

### Ricevere gli aggiornamenti
- Chi scarica l'app da GitHub (*Code › Download ZIP*) ha già il repository impostato in `version.json`; in
  alternativa si inserisce in *Impostazioni › Aggiornamenti* nel formato `utente/nome`.
- All'avvio l'app controlla `version.json` su GitHub; se c'è una versione più recente compare una notifica con
  le novità e il pulsante **Aggiorna ora**: scarica i sorgenti, salva un backup della versione attuale in
  `_backup/`, sostituisce i file, installa eventuali nuove librerie e si riavvia. Impostazioni, prezzi e speed
  test restano dove sono (`%APPDATA%\PCAnalyzer`).
- Sulla tua copia di sviluppo (cartella con `.git`) l'app non sovrascrive nulla: esegue `git pull`.
- L'aggiornamento automatico funziona con la versione a sorgenti (`avvia.bat`). Chi usa `PCAnalyzer.exe` deve
  aggiornare i sorgenti e rilanciare `build_exe.bat`.

## Dati utente
Impostazioni, listino prezzi aggiornato e ultimo speed test si trovano in `%APPDATA%\PCAnalyzer\`.

## Esportazione
**Esporta report** salva un riepilogo leggibile (`.txt`) o completo (`.json`).

## Struttura del progetto
```
PCAnalyzer/
├── main.py                 avvio
├── version.json            versione, novità e repository GitHub
├── avvia.bat / build_exe.bat / pubblica_aggiornamento.bat
├── requirements.txt
├── app/
│   ├── gui.py              interfaccia (CustomTkinter)
│   ├── theme.py            colori e font del tema Graphite Ember
│   ├── anim.py             motore delle animazioni
│   ├── drivers.py          link ufficiali driver e BIOS
│   ├── updater.py          aggiornamento automatico da GitHub
│   ├── hardware.py         rilevamento componenti
│   ├── scoring.py          indici prestazionali e voti
│   ├── balance.py          colli di bottiglia e upgrade
│   ├── prices.py           listino e aggiornamento prezzi
│   ├── speedtest_engine.py speed test
│   ├── ai_advisor.py       integrazione Claude
│   ├── report.py           esportazione
│   └── paths.py            percorsi e impostazioni
├── assets/               icona (icon.ico, icon.png, icon.svg)
├── data/
│   ├── components_db.json  database prestazioni
│   └── prices.json         listino iniziale
└── tools/
    ├── genera_database.py  rigenera il database prestazioni
    └── pubblica.py         pubblica una nuova versione su GitHub
```

## Limiti noti
- Temperature e tensioni non sono lette (su Windows richiedono un driver kernel, es. LibreHardwareMonitor): è un'estensione possibile.
- Il modello dell'alimentatore non è rilevabile via software: l'app stima i watt necessari.
- Gli indici sono medie di benchmark pubblici: indicano la fascia di prestazioni, non gli FPS esatti in un gioco.
- I prezzi del listino iniziale sono stime: aggiornali al primo avvio.
