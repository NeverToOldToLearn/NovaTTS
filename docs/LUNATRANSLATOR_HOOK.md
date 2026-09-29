# LunaTranslator als tekstbron (websocket)

NovaTTS kan zijn `raw_text` op twee manieren uit LunaTranslator krijgen. Deze
pagina gaat over de websocket. De andere is het klembord, en die staat in de
hoofd-README.

## Wat dit is, en wat het niet is

LunaTranslator heeft een **eigen netwerkservice**. Die publiceert twee
websocket-endpoints:

| endpoint | stuurt |
|---|---|
| `/api/ws/text/origin` | alle originele teksten |
| `/api/ws/text/trans` | alle vertaalde teksten |

Je hebt daarvoor **geen Textractor nodig** en ook geen
`textractor_websocket.dll`. LunaTranslator hakt het spel zelf al, en duwt de
vertaalde tekst via deze service naar buiten. NovaTTS leest die service op.

Dat is een andere route dan de `textractor_websocket`-extensie voor
Textractor, die ook bestaat en die eveneens de rol van server speelt. Beide
zijn ondersteund; zie de module-docstring van `backend/novatts/adapters/luna.py`.

## Aanzetten

1. Start LunaTranslator en hang het spel eraan, zoals je nu doet.
2. Zet de netwerkservice aan. In LunaTranslator: **Instellingen → Netwerkservice**
   (in het Engels *Network service*), en dan de service starten.
3. Zet in `backend/.env`:

   ```
   NOVATTS_HOOK_MODE=websocket
   NOVATTS_LUNA_WS_URL=ws://127.0.0.1:2333/api/ws/text/trans
   ```

4. Herstart de backend. `NOVATTS_HOOK_MODE` wordt bij het opstarten gelezen,
   niet tussentijds.

Het pad (`/api/ws/text/trans`) maakt deel uit van de URL. NovaTTS gebruikt de
URL zoals je hem opgeeft, inclusief het pad.

## De poort

Standaard `2333`, uit de LunaTranslator-instelling `networktcpport`. Als je
die in LunaTranslator verandert, moet je dezelfde waarde hier gebruiken. De
poort in de URL is dus de enige die telt; de NovaTTS-kant heeft geen eigen
default die hier overheen gaat.

## Waarom dit alleen op je eigen netwerk hoort

LunaTranslator bindt zijn service op `0.0.0.0`, niet op `127.0.0.1`. Terwijl
de service draait is hij dus bereikbaar vanaf je hele lokale netwerk, en er
zit geen wachtwoord op. Op een hotelnetwerk of een kantoornetwerk is dat iets
om te weten. LunaTranslator heeft zelf een instelling om individuele paden uit
te schakelen (`network_service_disabled_paths`); zet daar minstens
`/api/tts` en `/api/translate` uit als je de service op een gedeeld netwerk
aanzet.

## Wat je hiervan mag verwachten, en wat niet

**Gemeten** op je eigen klembordlog, 90 payload's met een regeleinde:

| | |
|---|---|
| de kale vorm `Tatsuo`⏎`Consider it your lucky day.` | werkt, `speaker='Tatsuo'` |
| de vorm `<b>Tatsuo</b>`⏎`The girl…` | werkt sinds F14, `speaker='Tatsuo'` |
| alles bij elkaar plakken, 3 van 61 (~5%) | **niet** opgelost, blijft één beurt |

Dat laatste staat bewust vastgepind in
`backend/tests/test_renpy_parser.py::test_a_block_of_pairs_stays_one_turn`. Het
opeisen zou het contract van `RenPyParser.parse` veranderen, en dat is een
bewuste keuze die nog niet gemaakt is.

**Niet gemeten hier**: het berichtformaat en de standaardpoort zijn gelezen uit
de bron van LunaTranslator (`main`), niet tegen een draaiende instantie. De
service stond op deze machine niet aan. De poort is instelbaar, dus een
afwijkende versie zou een andere waarde kunnen geven — controleer dan de
LunaTranslator-instelling tegen de URL hierboven. Wat wél gemeten is, is dat de
vorm van je payload's door de ontvangende code heen komt, want die code is
ongewijzigd.

## Fouten herkennen

- **Log zegt "niet gestart" en noemt de URL**: LunaTranslator's service draait
  niet op dat pad. Controleer poort en pad.
- **Log zegt wel gestart, maar er komt geen tekst binnen**: de service draait
  wel, maar `/api/ws/text/trans` is nog nooit gevuld omdat er nog niets
  vertaald is sinds je verbond. Zet het spel even aan de praat.
- **Verkeerde stem**: kijk in de log of er een `speaker=` staat. Ontbreekt die,
  dan werd je regel als vertelling gelezen. Met de `<b>`-vorm was dat een
  bekende oorzaak; die is nu gefixt.
