# Bozza di presentazione per Claude Design

## Obiettivo e pubblico

Preparare una presentazione di 10–12 minuti per un pubblico tecnico: docenti
di scientific computing, sviluppatori C++ e chi valuta un portfolio GitHub.
Autore: **Antonio Arbizzani Tonelli**. Titolo suggerito:
**«LLM Resource Allocation: dal modello verificato al parallelismo misurato»**.

La storia parte da una domanda concreta: come assegnare modelli e GPU
eterogenee rispettando costo, domanda e qualità del servizio, e come rendere
veloce il software che prende questa decisione? Il paper fornisce formulazione
e algoritmi; il contributo personale è trasformarli in un sistema controllabile,
riproducibile e misurato. Evitare di attribuire all'autore nuovi algoritmi GH/AGH
o il problema scientifico originale.

Il repository consegnato è la fonte del progetto. Usare [RESULTS.md](RESULTS.md)
per numeri e limiti, [MODEL.md](MODEL.md) per la formulazione,
[ARCHITECTURE.md](ARCHITECTURE.md) per il software,
[EXPERIMENTS.md](EXPERIMENTS.md) per la riproducibilità e
[VALIDATION.md](VALIDATION.md) per i controlli finali.
I risultati del paper e le misure del progetto devono avere attribuzioni visibili
diverse. Non importare numeri da documenti o conversazioni non consegnati.

## Sequenza proposta

| Slide | Messaggio e contenuto | Visuale suggerita |
|---|---|---|
| 1. Il costo di una decisione sbagliata | Domanda variabile, modelli diversi, GPU diverse: un'assegnazione economica deve comunque rispettare i vincoli. Presentare autore e domanda del progetto. | Schema semplice: workload → allocatore → modelli/GPU, con costo e SLO come due criteri. |
| 2. Due tempi decisionali | Stage 1 sceglie deployment e routing; Stage 2 mantiene il deployment e adatta routing/domanda non servita. Le latenze GPU sono coefficienti del modello; il programma misurato gira su CPU. | Due pannelli con elementi fissi e variabili evidenziati. |
| 3. Il primo risultato è poter controllare il risultato | Una risposta del solver o una conclusione dell'euristica non basta: decisioni, vincoli, costo ricalcolato e stato del solver restano distinti. | Pipeline breve: input → algoritmo → decisione → validatore indipendente. |
| 4. Una convenzione dimensionale esplicita | Mostrare perché ore, secondi, millisecondi, concorrenza KV e dati residenti hanno confini espliciti. Le convenzioni storiche restano identificate. | Un solo esempio di conversione e un riquadro con le unità; evitare una pagina di formule. |
| 5. Costo e servizio: guardare le componenti | Otto casi sintetici condivisi: GH rental 9 USD, AGH 8 USD. Riduzione **11,1% della componente C1** e domanda interamente servita; guadagno sul totale nominale soltanto 0,087–0,278%. | Due barre C1 9/8, con etichetta «USD per orizzonte sintetico». Riquadro separato con il piccolo guadagno totale. |
| 6. Il solver cambia anche la lettura del confronto | Sei optima piccoli per backend; nessun optimum dimostrato sui casi maggiori. Sul nominale 10×10×10 Gurobi trova un incumbent 724,0209 USD contro 1274,7587 di HiGHS; AGH vale 1150,0550. | Tre barre per lo stesso caso, etichettate «incumbent accettato»/«euristica», e una nota sulla domanda servita. |
| 7. Dal riferimento Python a C++ | Preservare decisioni e ordine numerico prima di misurare. **63/63 controlli**, 3023 valori finali senza differenze bitwise; sei casi maggiori verificano altri 20494 valori, riportati come campagna separata. | Due colonne Python/C++ collegate dalle stesse decisioni, con i contatori di verifica. |
| 8. La velocità dipende dal confine del cronometro | AGH 16×4×4/load200: Python 4,774378 s, core C++ 0,045939 s. Rapporto 103,93× tra implementazioni con costi e ambienti differenti. Non chiamarlo «C++ è 104 volte più veloce». | Barre con confini del tempo espliciti: input/trace e core/trasporto. Preferire questo confronto in una slide tecnica, senza farne il titolo principale. |
| 9. Parallelizzare le prove indipendenti | OpenMP: 16 AGH grandi, otto thread, **5,16× sul core**, **64,5% di efficienza** e **1,73× sull'invocazione completa**. Batch misto: 5,07× / 63,4% / 1,96×. | Usare il grafico [openmp_scaling.png](../benchmarks/portfolio/plots/openmp_scaling.png), mantenendo entrambe le scale temporali. |
| 10. Un'ottimizzazione rifiutata è informazione | Il prototipo interno del validatore non aggiunge un beneficio robusto rispetto agli slot seriali. Su AGH32: 0,102698 s seriale contro 0,109183/0,133577/0,205992 con 2/4/8 thread. Si mantiene il validatore seriale. | Usare [validation_grain.png](../benchmarks/portfolio/plots/validation_grain.png). Titolo: «Scegliere il lavoro giusto da parallelizzare». |
| 11. Stage 2: adattare senza ricostruire | Un GPU fisso: la domanda passa da 6 a 12 richieste/ora, routing da 1 a 0,5 e domanda non servita da 0 a 0,5. Il volume servito resta 6/ora, e il costo modellato aumenta da 43,8 a 193,8 USD per 3 ore. Entrambi i risultati sono indipendentemente fattibili. | Prima/dopo delle frazioni con etichette di domanda; citare [il JSON dell'esempio](../benchmarks/stage2/reference.json). È una verifica sintetica, senza inventare un risparmio o un tasso di robustezza. |
| 12. Cosa rende il progetto riutilizzabile | Codice Python/C++20/OpenMP, API esplicite, test, risultati machine-readable, hash, input e comandi di riproduzione. Restano aperti calibrazione completa del paper, solver nativi C++/Stage 2 e MPI. | Mappa minima del repository e link GitHub finale. |

Se servono dieci slide, unire 3–4 e 7–8. Le slide principali devono spiegare
una decisione o un risultato ciascuna; dettagli di solver, tolleranze e
compilazione vanno nelle note del relatore o in appendice.

## Numeri utilizzabili e formulazione corretta

- **11,1%**: riduzione della componente di rental GPU C1, `(9−8)/9`, in
  otto istanze sintetiche. Non è il risparmio totale e non è una misura di
  fatturazione reale.
- **5,16× e 64,5%**: batch fisso di 16 AGH, core OpenMP a otto thread,
  `T_serial/T_parallel` e `speedup/8`. Il solve individuale resta seriale.
- **1,73×**: la stessa configurazione uniforme a otto thread includendo
  processi e trasporto. Non è il massimo tra tutte le configurazioni: i tempi
  completi variano e quattro thread possono essere migliori.
- **63/63 e 3023**: 48 casi di placement e 15 controlli RNG; i valori numerici
  confrontati appartengono ai placement. La campagna maggiore è separata.
- **72/72 contro 69/72**: accettazione di tutti i tentativi misurati HiGHS
  contro Gurobi. Tre risultati Gurobi sono scartati per disaccordo obiettivo
  pur passando i vincoli. Non trasformare una percentuale di accettazione in
  accuratezza di predizione.

I valori precisi e tutte le impostazioni sono in
[summary.json](../benchmarks/portfolio/summary.json),
[indicators.csv](../benchmarks/portfolio/indicators.csv) e nei relativi manifest.
I grafici disponibili sono scientifici, costruiti dalle misure registrate.
Claude Design può adattare tipografia e disposizione, preservando etichette,
unità, valori, assi e attribuzioni.

## Indicazioni visive e note del relatore

Usare un fondo chiaro, un colore per il riferimento seriale e uno per il
parallelismo. Limitare le formule alla chiusura della domanda, alle percentuali
di vantaggio e al significato di speedup/efficienza. Mettere sotto ogni grafico
«dati sintetici del progetto» oppure la citazione del paper quando la visuale
mostra dati degli autori. Le GPU devono apparire come risorse modellate, senza
foto che suggeriscano un cluster sperimentale reale.

Il racconto deve rendere evidente il metodo di lavoro: rendere esplicite le
ambiguità; verificare un riferimento; portare senza alterare decisioni;
profilare; scegliere una granularità utile; conservare anche risultati
negativi. Chi guarda il GitHub deve poter seguire questa catena attraverso
codice, comandi e risultati consegnati.

Per Stage 2 usare soltanto [il JSON dell'esempio](../benchmarks/stage2/reference.json)
eseguito nella versione consegnata. Non attribuire al progetto gli esperimenti del paper con 500
scenari, un cluster GPU, nuove euristiche, risultati MPI o la riproduzione
numerica completa degli autori. Il lavoro originale rimane attribuito a
Cheng e Nguyen:
[paper v2](https://arxiv.org/abs/2604.07472v2) e
[paper v1](https://arxiv.org/abs/2604.07472v1).

La [nuova analisi delle prestazioni](PERFORMANCE.md) aggiunge misure del 13
ottobre: nove dimensioni, 18 punti GH/AGH C++, cinque campioni per punto e
batch OpenMP da 32/64/128 casi con 18 round. Per le slide sul costo della
crescita usare `query_scaling.png` e `menu_scaling.png`; per il parallelismo
usare `openmp_core_scaling.png` e `openmp_process_scaling.png` nella cartella
`benchmarks/performance_2026-10-13/analysis/plots`.

Numeri utilizzabili: AGH C++ mediano **2,889 s a 128x4x4**, **7,156 s a
256x4x4**, **7,471 s a 128x8x8**. Lo speedup OpenMP mediano migliore osservato
è **4,20x per il calcolo**, **2,27x per l'intera invocazione**, efficienza
**52,5%**: 32 casi misti, scheduling dinamico, otto thread osservati.
Mostrare il confronto statico/dinamico sullo stesso batch; non affermare che
batch più grandi aumentino sempre lo speedup.

Un risultato da raccontare è il limite del riferimento: AGH Python termina
con MemoryError nei casi 256x4x4 e 128x8x8. I tempi nativi di quei casi hanno
validazione indipendente della decisione finale e dell'obiettivo, senza parità
dell'intero algoritmo Python. Nei grafici questi punti sono distinti; non
inventare un tempo Python o un rapporto di accelerazione per il run fallito.
Sedici confronti completi verificano 185.832 valori numerici identici bit per bit.

La parte di stress di Stage 2 della [campagna notturna](NIGHTLY_CAMPAIGN.md)
rimane in attesa. Per quella parte usare ancora soltanto l'esempio consegnato.
