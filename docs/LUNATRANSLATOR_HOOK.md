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

### Gematen tegen een draaiende LunaTranslator

Op 2026-09-30, met het spel *Chrono Ecstasy* aan de service hangend:

| | |
|---|---|
| beide endpoints geven **101** bij de handdruk | `/api/ws/text/trans` en `/api/ws/text/origin` |
| twee verzonnen paden geven **404** | dus "101" betekent iets, niet "de server is vaag" |
| de binding is **`0.0.0.0:2333`** | bevestigd, niet langer uit de bron gelezen |
| het frameformaat is **platte tekst, geen JSON** | één frame per regel |
| de vorm is `naam⏎tekst⏎` | met afsluitende newline, en die is ondeelbaar |
| **13 frames op `/origin`, 0 op `/trans`** | over vijf minuten spelen |

Die laatste regel is de belangrijkste. Beide endpoints waren tegelijk
beluisterd, dus "0 op `/trans`" is niet "er was geen tekst". Het betekent:
**er wordt op dat moment niets vertaald**, en `/trans` blijft leeg totdat dat
wel zo is. Wie `/trans` gebruikt zonder vertaling aan te zetten, krijgt een
gezonde verbinding, `hook_clients: 1`, en geen enkele regel.

Kies dus het pad dat bij je situatie hoort:

- **vertaald spel, vertaling aan** → `/api/ws/text/trans`
- **spel speelt in het Engels, of er wordt niet vertaald** → `/api/ws/text/origin`

Wisselen is één woord in de URL, gevolgd door een herstart van de backend.

Wat nog steeds **niet** gemeten is: de poort is instelbaar, dus een andere
LunaTranslator-versie kan een andere standaard geven. Vergelijk bij twijfel de
LunaTranslator-instelling met de URL hierboven.

## Sprekers registreren: een naam van twee woorden

`Work Inspector` is één spreker, maar de grenszoeker herkent die alleen als
**`Work Inspector` in het register staat**. Dat is geen eigenheid van deze
route maar de algemene regel van de parser, en het is een installatiestap:

| naam | staat hij niet in het register? |
|---|---|
| `Tatsuo` (één woord) | werkt alsnog, de heuristiek noemt het een plausibele naam |
| `Work Inspector` (twee woorden) | wordt `Work` + `"Inspector …"` |

Het register hoort bij het spel dat je speelt. Staat er een ander spel actief,
dan krijgt iedere onbekende naam de stem van de **verteller** en niet die van
een personage — stil, zonder foutmelding. Maak in de GUI per spel zijn
eigen sprekers aan.

De twee-woord-vorm werkt in alle drie de vormen waarin hij aankomt —
`naam⏎tekst`, `naam tekst` en `naam: tekst` — sinds de fix die hierboven staat.

## Fouten herkennen

- **Log zegt "niet gestart" en noemt de URL**: LunaTranslator's service draait
  niet op dat pad. De regel noemt de URL die is gebruikt, dus die klopt per
  definitie; kijk naar de poort en het pad erin.
- **Log zegt wel gestart, maar er komt geen tekst binnen**: de service draait
  wel. Kijk eerst welk pad je hebt gekozen tegen de tabel hierboven — een
  verbonden client op `/trans` zonder vertaling ziet er precies hetzelfde uit
  als een werkende. Daarna: `/status` op `http://127.0.0.1:8765/status` en
  kijk naar `hook_last_raw`.
- **Verkeerde stem**: kijk in het log naar de regel `Synthesized …`. Staat er
  `voice=` leeg, dan heeft die spreker geen stem toegewezen en valt hij terug op
  de modelstem. Is het begin van de zin een stuk van een naam (`Inspector Hm.`
  in plaats van `Hm.`), dan is die naam niet geregistreerd — zie hierboven.
- **Verkeerde taal**: je hoort het Engels terwijl je een vertaling verwachtte.
  Dat is geen parseerfout maar het verkeerde pad; zie de tabel hierboven.
