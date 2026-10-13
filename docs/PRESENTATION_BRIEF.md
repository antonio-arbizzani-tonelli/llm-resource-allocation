# Bozza di presentazione per Claude Design

Il [prompt pronto da usare](CLAUDE_DESIGN_PROMPT.md) riunisce queste indicazioni
e le fonti dei risultati pubblicati: copialo in Claude Design o allega il file.

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
[EXPERIMENTS.md](EXPERIMENTS.md) per la riproducibilità,
[STAGE2_RESULTS.md](STAGE2_RESULTS.md) per adattamento e rifiuti numerici e
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
| 7. Dal riferimento Python a C++ | Sedici confronti completi sulle istanze maggiori verificano **185.832 valori identici bit per bit**. AGH Python termina con MemoryError a 256×4×4 e 128×8×8: quei tempi C++ hanno verifica della decisione finale, senza parità dell'intero algoritmo. | Due colonne Python/C++ collegate dalle stesse decisioni; due marcatori distinti per gli endpoint con verifica supplementare. |
| 8. Il costo della crescita | Mediane AGH C++: **2,889 s a 128×4×4**, **7,156 s a 256×4×4**, **7,471 s a 128×8×8**, cinque campioni per punto. Aumentare query e alternative cambia due dimensioni diverse del problema. | Usare [query_scaling.png](../benchmarks/performance_2026-10-13/analysis/plots/query_scaling.png) e [menu_scaling.png](../benchmarks/performance_2026-10-13/analysis/plots/menu_scaling.png), mantenendo i marcatori di verifica. |
| 9. Parallelizzare le prove indipendenti | Nella nuova campagna, 32 casi misti, scheduling dinamico e otto thread osservati: **4,20× mediano sul core**, **2,27× sull'invocazione**, **52,5% di efficienza**, 18 round. Batch maggiori non garantiscono speedup maggiore. | Usare [openmp_core_scaling.png](../benchmarks/performance_2026-10-13/analysis/plots/openmp_core_scaling.png) e [openmp_process_scaling.png](../benchmarks/performance_2026-10-13/analysis/plots/openmp_process_scaling.png). Tenere distinti timer e campagne storiche. |
| 10. Stage 2: misurare anche il confine di fattibilità | **40 job completati**, **37 sorgenti accettate**, **1.850 LP tentati**: 646 accettati, 1.000 infeasible, 204 rifiuti sull'obiettivo. Altri 150 scenari sono saltati dopo tre sorgenti P_DM rifiutate. Nessuna griglia ha 50/50 risultati accettati. | Usare [outcomes.png](../benchmarks/stage2_stress_2026-10-13/plots/outcomes.png). I 150 non tentati vanno in un riquadro separato, fuori dal denominatore 1.850. |
| 11. Adattare senza ricostruire: due vantaggi misurati | Stage 2 recupera **256/1.344 fallimenti del routing iniziale = 19,05%**. Nei **390 scenari con entrambi i routing validi**, la somma C4+C5 diminuisce del **5,86%**. Deployment fisso; cambiano routing e domanda non servita. | Usare [recovery_and_cost.png](../benchmarks/stage2_stress_2026-10-13/plots/recovery_and_cost.png). Etichette: «griglia sintetica deterministica» e «confronto appaiato su 390 scenari». |
| 12. Una soluzione ottima del solver può restare rifiutata | I 204 casi passano i vincoli ma falliscono la soglia assoluta di accordo **1e-8 USD**. Differenze di **1–3 ULP**, massimo relativo **3,40e-16**, coerenti con arrotondamento floating point. Le tolleranze rimangono invariate e i risultati esclusi dalle metriche. | Usare [objective_roundoff.png](../benchmarks/stage2_stress_2026-10-13/plots/objective_roundoff.png). Un esempio a 76 milioni di USD modellati rende visibile il limite di una soglia solo assoluta. |
| 13. Cosa rende il progetto riutilizzabile | Codice Python/C++20/OpenMP, decisioni verificabili, risultati completi anche quando rifiutati, hash e replay senza solver. Restano aperti politica numerica alle grandi scale, calibrazione del paper, solver nativi C++/Stage 2 e MPI. | Mappa minima del repository e link GitHub finale. Attribuire il modello e GH/AGH al paper, e l'implementazione, verifica e misure al progetto. |

Per dodici slide spostare 6 in appendice; per dieci unire anche 3–4 e 7–8.
Le slide principali devono spiegare
una decisione o un risultato ciascuna; dettagli di solver, tolleranze e
compilazione vanno nelle note del relatore o in appendice.

## Numeri utilizzabili e formulazione corretta

- **11,1%**: riduzione della componente di rental GPU C1, `(9−8)/9`, in
  otto istanze sintetiche. Non è il risparmio totale e non è una misura di
  fatturazione reale.
- **4,20× / 2,27× / 52,5%**: mediane della nuova campagna, 32 casi misti,
  scheduling dinamico, otto thread osservati e 18 round. Il solve individuale
  resta seriale. I vecchi 5,16× / 1,73× appartengono a un altro batch e ad
  altri riassunti temporali: non costruire una combinazione di massimi diversi.
- **185.832 valori**: sedici confronti completi Python/C++; gli endpoint con
  MemoryError hanno invece verifica supplementare della decisione finale.
- **19,05%**: recuperi scientificamente accettati tra i 1.344 fallimenti del
  routing iniziale. Non è una probabilità reale né la quota su tutti i 1.850 LP.
- **5,8574%**: `(somma C4+C5 congelato − somma C4+C5 adattato) / somma congelata`
  sui 390 scenari utilizzabili da entrambe le decisioni. Le somme sono dominate
  dal carico sintetico elevato; non è un risparmio tipico o una bolletta cloud.
- **646 / 1.000 / 204**: esiti dei 1.850 LP tentati. I 204 rifiuti numerici
  sono diversi dalle infeasibilità; non diventano successi perché il solver
  dichiara un optimum. I 150 scenari saltati sono un'altra categoria.
- **72/72 contro 69/72**: accettazione di tutti i tentativi misurati HiGHS
  contro Gurobi. Tre risultati Gurobi sono scartati per disaccordo obiettivo
  pur passando i vincoli. Non trasformare una percentuale di accettazione in
  accuratezza di predizione.

I valori precisi e tutte le impostazioni sono in
[summary.json](../benchmarks/portfolio/summary.json),
[indicators.csv](../benchmarks/portfolio/indicators.csv),
[analisi Stage 2](../benchmarks/stage2_stress_2026-10-13/analysis/analysis.json),
[diagnostica numerica](../benchmarks/stage2_stress_2026-10-13/analysis/numerical_diagnostics.json)
e nei relativi manifest.
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

Per Stage 2 usare la [campagna consegnata](STAGE2_RESULTS.md); il
[JSON dell'esempio](../benchmarks/stage2/reference.json) resta una verifica
didattica da appendice, non la fonte dei nuovi indicatori. Non attribuire al progetto gli esperimenti del paper con 500
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

La parte di stress Stage 2 della [campagna notturna](NIGHTLY_CAMPAIGN.md) è ora
eseguita e documentata. Il run principale riparte da zero con alimentazione
da rete e impiega circa 11 minuti di wall time dei worker; il precedente avvio
a batteria è escluso. Non presentare «40/40 job» come «2.000 LP validati».

Nelle note della slide numerica distinguere le tre sorgenti P_DM rifiutate:
16×4×4 ad alto carico viola l'error SLO; 32×4×4 passa i vincoli ma fallisce
l'accordo sull'obiettivo; 16×8×8 viola il bilancio della domanda. Tutti gli otto
solve P_DM terminano al limite con incumbent, senza dimostrare ottimalità.
Un'eventuale revisione delle tolleranze sarà un esperimento separato.

In appendice conservare il risultato negativo del parallelismo interno del
validatore: [validation_grain.png](../benchmarks/portfolio/plots/validation_grain.png).
Serve a spiegare perché il parallelismo di produzione resta sui casi indipendenti.
