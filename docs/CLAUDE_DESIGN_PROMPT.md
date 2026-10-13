# Prompt per Claude Design

Copia il blocco seguente in Claude Design oppure allega questo file. Il prompt
usa la [bozza pubblicata](PRESENTATION_BRIEF.md) e fissa il commit dei risultati,
così fonti e numeri rimangono coerenti.

```text
Crea una presentazione completa in italiano sul mio progetto “LLM Resource Allocation”.

Autore: Antonio Arbizzani Tonelli.
Pubblico: docenti di scientific computing, sviluppatori C++ e persone che valutano un portfolio GitHub.
Durata: 10–12 minuti.
Formato: 12 slide principali in 16:9, con eventuali appendici tecniche.

Titolo suggerito:
“LLM Resource Allocation: dal modello verificato al parallelismo misurato”

FONTI

Repository:
https://github.com/antonio-arbizzani-tonelli/llm-resource-allocation

Usa il commit:
8a11e7d533e929009ef5e1cae2dde6bdb18d217b

Per leggere direttamente i file, aggiungi i percorsi sotto a questa base:
https://raw.githubusercontent.com/antonio-arbizzani-tonelli/llm-resource-allocation/8a11e7d533e929009ef5e1cae2dde6bdb18d217b/

Leggi prima:
- docs/PRESENTATION_BRIEF.md: bozza narrativa e struttura.
- docs/RESULTS.md: risultati complessivi e limiti.
- docs/PERFORMANCE.md: benchmark Python/C++ e OpenMP.
- docs/STAGE2_RESULTS.md: campagna Stage 2 e rifiuti numerici.
- docs/MODEL.md: formulazione.
- docs/ARCHITECTURE.md: implementazione.
- docs/VALIDATION.md: verifiche e riproducibilità.

Usa esclusivamente risultati documentati in questa versione. Se una fonte non è accessibile, segnala quale manca senza ricostruirne i dati.

STORIA DA RACCONTARE

La domanda iniziale è: come assegnare modelli e GPU eterogenee rispettando costo, domanda e qualità del servizio, e come rendere efficiente il software che prende queste decisioni?

Il contributo personale consiste nel costruire un riferimento Python verificabile, chiarire le unità, validare indipendentemente le decisioni, portare GH/AGH in C++20, misurare OpenMP e studiare l’adattamento operativo Stage 2.

Attribuisci formulazione e algoritmi GH/AGH al paper citato nel repository. Attribuisci al progetto implementazione, verifica, ingegnerizzazione ed esperimenti.

Segui la bozza pubblicata, adattandola a 12 slide. Sposta il confronto dettagliato tra solver in appendice. Mantieni questo percorso:
problema → due stadi decisionali → verifica → implementazione → scalabilità → parallelismo → adattamento Stage 2 → limiti numerici → contributi e sviluppi futuri.

Ogni slide deve sostenere un messaggio preciso. Usa titoli che esprimano quel messaggio e lascia le spiegazioni approfondite nelle note del relatore.

RISULTATI DA PRESENTARE CON IL LORO CONTESTO

Python/C++:
- Sedici confronti completi: 185.832 valori numerici identici bit per bit.
- Mediane AGH C++: 2,889 s a 128×4×4; 7,156 s a 256×4×4; 7,471 s a 128×8×8.
- Le dimensioni indicano query × alternative di modello × alternative di GPU.
- AGH Python incontra MemoryError nei due endpoint maggiori. Per quei punti è verificata la decisione finale C++, senza parità dell’intero algoritmo Python.

OpenMP:
- 32 casi misti, scheduling dinamico, otto thread osservati, 18 round.
- Speedup mediano 4,20× sul calcolo e 2,27× sull’intera invocazione.
- Efficienza 52,5%.
- Mantieni distinti timer, batch e campagne storiche.

Stage 2:
- 40/40 job completati, 37/40 allocazioni iniziali accettate.
- 1.850 LP tentati: 646 accettati, 1.000 infeasible, 204 rifiutati per disaccordo sull’obiettivo.
- Altri 150 scenari sono saltati dopo tre allocazioni iniziali rifiutate.
- Recupero: 256 dei 1.344 fallimenti del routing iniziale, cioè 19,05%.
- Riduzione del costo operativo aggregato C4+C5: 5,86%, sui 390 scenari in cui entrambi i routing sono utilizzabili.
- Questi indicatori riguardano una griglia sintetica deterministica: mostra sempre i denominatori.

Dedica una slide ai rifiuti numerici:
- I 204 casi passano i vincoli e hanno stato ottimo del solver, ma superano la soglia assoluta di accordo sull’obiettivo di 1e-8 USD.
- Le differenze sono di 1–3 spaziature floating point, con massimo relativo 3,40e-16, coerenti con arrotondamento numerico.
- Le tolleranze sono rimaste invariate e i risultati rifiutati sono esclusi dalle metriche.
- Spiega la distinzione tra fattibilità, ottimalità del solver e accordo numerico.

DISEGNO DELLE SLIDE

Riprendi i colori dei grafici pubblicati e mantieni una gerarchia tipografica leggibile, spazio libero e composizioni varie: schemi decisionali, confronti, grafici e pochi numeri essenziali.

I grafici disponibili sono in:
- benchmarks/performance_2026-10-13/analysis/plots/
- benchmarks/stage2_stress_2026-10-13/plots/

Usa PNG o SVG originali, oppure ridisegnali preservando valori, assi, unità, denominatori e marcatori delle verifiche supplementari.

Indica nelle slide sperimentali “dati sintetici del progetto”. Il programma misurato gira su CPU; capacità GPU e latenze sono coefficienti modellati. MPI e Stage 2 nativo C++ sono sviluppi futuri.

CONSEGNA

Realizza direttamente le slide complete ed editabili, con:
- note del relatore adatte ai 10–12 minuti;
- riferimenti discreti alle fonti;
- appendici per dettagli di solver, verifica e tolleranze;
- slide finale con il repository GitHub.

Prima della consegna controlla leggibilità, sovrapposizioni, coerenza dei numeri e distinzione tra risultati accettati, rifiuti numerici e infeasibilità.
```
