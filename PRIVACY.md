# Informativa privacy di GitaSerena

Ultimo aggiornamento: 6 novembre 2026

GitaSerena è un'app gratuita che suggerisce mete per una gita in giornata, in base
al meteo, alla distanza e all'interesse dei luoghi.

**In breve:** l'app non ha account, non usa pubblicità, statistiche d'uso o
strumenti di tracciamento, e non ha un server proprio. Per funzionare chiede
alcuni dati a servizi pubblici di terzi, elencati qui sotto. Tutto il resto
resta sul telefono.

## Titolare del trattamento

Giosuè Valfrè
Email: gitaserena.app@gmail.com

## Quali dati usa l'app e dove vanno

### Sul telefono

L'app salva solo sul telefono:

- le mete preferite;
- le impostazioni del viaggio (consumo dell'auto, prezzo del carburante) e il tema;
- copie temporanee di previsioni meteo, percorsi, ristoranti, foto, eventi e della
  configurazione dei servizi, per non ripetere le stesse richieste.

Questi dati non vengono inviati a nessuno. Si cancellano disinstallando l'app o
cancellandone i dati dalle impostazioni del telefono.

### Posizione

La posizione del telefono è usata solo se tocchi "Usa la mia posizione", e solo
dopo il tuo consenso al permesso di localizzazione. In alternativa puoi scrivere
il nome di una località.

Il punto di partenza, che sia la tua posizione o la località scelta, è usato sul
telefono per calcolare le distanze. Esce dal telefono solo per il calcolo dei
percorsi stradali, **arrotondato a circa 100 metri** (vedi sotto).

### Servizi di terzi

Ogni richiesta a un servizio esterno comunica a quel servizio, come per qualsiasi
sito web, l'indirizzo IP del telefono, l'ora e il nome dell'app. Oltre a questo,
ogni servizio riceve solo quanto indicato:

| Servizio | A cosa serve | Cosa riceve |
|---|---|---|
| MET Norway (api.met.no, Norvegia) | previsioni meteo | coordinate delle mete, arrotondate a una griglia di circa 10 km |
| Open-Meteo (Svizzera) | ricerca delle località | il testo che scrivi nel campo di partenza |
| FOSSGIS e.V., routing.openstreetmap.de (Germania) | tempo e km di strada | punto di partenza arrotondato a circa 100 m e coordinate delle mete mostrate |
| FOSSGIS e.V., overpass-api.de (Germania) | ristoranti vicino a una meta | coordinate della meta aperta |
| Wikimedia Foundation (Wikipedia, Wikimedia Commons; USA) | foto delle mete | titolo della pagina Wikipedia della meta aperta |
| GitHub (raw.githubusercontent.com; USA) | file degli eventi e configurazione dei servizi | nessun dato oltre a quelli di ogni richiesta |

Se l'app è stata compilata con una chiave openrouteservice, i percorsi sono
calcolati da HeiGIT gGmbH (Germania) invece che da FOSSGIS, con gli stessi dati.
Se è stato scelto un altro servizio meteo, Open-Meteo o OpenWeather, questo
riceve gli stessi dati indicati per MET Norway.

I gestori di questi servizi possono conservare le richieste nei loro registri
tecnici, secondo le rispettive informative:

- MET Norway: https://www.met.no/en/About-us/privacy
- Open-Meteo: https://open-meteo.com/en/terms
- FOSSGIS e.V.: https://www.fossgis.de/datenschutzerkl%C3%A4rung/
- Wikimedia Foundation: https://foundation.wikimedia.org/wiki/Policy:Privacy_policy
- GitHub: https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement

Alcuni di questi servizi si trovano fuori dall'Unione europea: Norvegia e
Svizzera, che hanno una decisione di adeguatezza, e Stati Uniti.

### Link esterni e condivisione

I pulsanti "Google Maps", "TripAdvisor", "Wikipedia" e i link alle fonti aprono
il browser o l'app corrispondente. Da quel momento vale l'informativa di quel
servizio. "Condividi" apre il menu di condivisione del telefono: sei tu a
scegliere con chi e con quale app condividere la meta.

## Perché e su quale base

I dati sono trattati solo per fornirti i suggerimenti che chiedi. La base
giuridica è l'esecuzione del servizio richiesto e il legittimo interesse a farlo
funzionare (articolo 6, paragrafo 1, lettere b e f del Regolamento UE 2016/679).
Per la posizione del telefono serve il tuo consenso, che puoi revocare in ogni
momento dalle impostazioni del telefono.

## I tuoi diritti

Puoi chiedere accesso, rettifica, cancellazione, limitazione od opposizione al
trattamento scrivendo all'email indicata sopra. Il titolare non conserva dati
che ti riguardano: quelli sul telefono li controlli tu, quelli nei registri dei
servizi di terzi vanno chiesti a loro. Puoi anche proporre reclamo al Garante per
la protezione dei dati personali (https://www.garanteprivacy.it).

## Minori

L'app non è rivolta in modo specifico ai minori e non raccoglie dati che li
identifichino.

## Modifiche

Le modifiche a questa informativa sono pubblicate in questa pagina, con la data
di aggiornamento in alto. La cronologia completa è nel repository
https://github.com/giosu68/gitaserena-data.
