# Household Presence

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/elvisek2020/hacs-household_presence)](https://github.com/elvisek2020/hacs-household_presence/releases)
[![Validate](https://github.com/elvisek2020/hacs-household_presence/actions/workflows/validate.yml/badge.svg)](https://github.com/elvisek2020/hacs-household_presence/actions/workflows/validate.yml)
[![Licence](https://img.shields.io/github/license/elvisek2020/hacs-household_presence)](LICENSE)

[![Otevřít v HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=elvisek2020&repository=hacs-household_presence&category=integration)

Integrace pro Home Assistant, která z entit, které už máte (osoby, trackery z aplikace nebo z routeru, binární senzory, kalendáře), určí:

- **kdo** je doma a **kolik** lidí,
- jestli je doma **někdo**,
- jestli je domácnost **krátce** nebo **dlouhodobě pryč**,
- **kdy se kdo vrátí** (z plánu, z blížení k domu a z naučených zvyklostí).

Integrace nic neřídí. Poskytuje stabilní sadu entit, na kterou se napojí topení, světla, alarm nebo notifikace. Všechno běží lokálně, poloha se neukládá.

## Předpoklady a závislosti

- Home Assistant 2026.3 nebo novější.
- Entity, ze kterých se přítomnost pozná: `person`, `device_tracker` (aplikace HA, UniFi a podobně), binární senzory (počítač, konzole, dveře), volitelně kalendáře a senzory vzdálenosti (např. integrace Proximity).
- Žádné další knihovny ani cloud.

## Instalace

### HACS (doporučeno)

1. HACS → tři tečky vpravo nahoře → **Custom repositories**
2. Vlož URL `https://github.com/elvisek2020/hacs-household_presence`, kategorie **Integration**
3. Nainstaluj **Household Presence**
4. Restartuj Home Assistant a přidej ji v Nastavení → Zařízení a služby → Přidat integraci. Zadáš název domácnosti a zpoždění odchodu.

HACS nabízí aktualizace z GitHub releases.

### Ručně

Zkopíruj `custom_components/household_presence` do `/config/custom_components/` a restartuj HA.

## Konfigurace

### Členové a signály

Každý člen domácnosti je samostatná položka integrace (**Přidat člena**). Počet členů, jména i signály jsou libovolné.

U člena nastavíte:

| Pole | Význam |
|---|---|
| Jméno | Z něj vznikne `entity_id`, např. `binary_sensor.hp_jana_home`. |
| Bez signálu doma | **Pryč po zpoždění odchodu:** když žádný signál neříká doma, člen po zpoždění odejde. **Držet poslední stav:** člen odejde jen podle plánu nebo ručně (hodí se pro člověka, který nenosí telefon). |
| Vlastní zpoždění odchodu | Přebije hodnotu domácnosti. |
| Noční okno | Podle domácnosti, vlastní, nebo vypnuto. |

**Signál** je libovolná entita a její význam:

| Význam | Kdy použít | Příklad |
|---|---|---|
| Doma i pryč | entita umí říct obojí | `person`, `device_tracker` z aplikace HA (GPS) |
| Jen doma | zapnuto = doma, vypnuto nic neříká | telefon na domácí Wi-Fi, zapnutý počítač, konzole, Bluetooth |
| Jen pryč | zapnuto = pryč | pracovní VPN, auto mimo domov |

U signálu lze dále nastavit:

- **stavy znamenající doma**, např. SSID domácí Wi-Fi u senzoru. Výchozí jsou `home` u `person` a `device_tracker`, jinak `on` a `home`;
- **zpoždění příchodu**: signál musí hlásit doma aspoň tak dlouho, hodí se u počítače nebo konzole;
- **zaseknutý po N h**: signál, který hlásí doma déle, se ignoruje a vznikne oprava (repair);
- **časové okno platnosti**, např. počítač jen 6–23 h;
- **důvěru**: dovolenou nebo „vynutit pryč“ ukončí jen příchod se signálem s vysokou důvěrou.

#### Plán z kalendáře

Člen může mít jeden nebo víc kalendářů, třeba školní rozvrh nebo pracovní kalendář. Během události je člen pryč, pokud ho žádný signál nevidí doma.

- Mezery mezi událostmi do 45 min se překlenou (přestávky).
- Předstih (20 min) a dojezd (30 min) pokryjí cestu tam a zpět.
- Signál, který svítí už od začátku plánu a nezměnil se, se ignoruje. Typicky je to počítač zapnutý přes noc. Když se signál během plánu zapne (dítě je nemocné a zapne počítač), člen je doma.
- Konec plánu je očekávaný návrat. Člen s volbou „držet poslední stav“ se po konci plánu bere jako doma.

#### Blížení

Volitelně lze zadat entitu vzdálenosti od domova a entitu směru (např. z vestavěné integrace **Proximity**). Když vzdálenost klesá pod práh, `binary_sensor.hp_someone_approaching` se zapne a vznikne odhad příchodu.

### Domácnost

V **Možnostech** integrace najdete:

- **Zpoždění a časové limity:** zpoždění odchodu (15 min), klid po startu (5 min, během něj se neodchází), limit nedostupnosti signálů (6 h).
- **Noční okno a dveře** (22:00–7:00): telefony v noci uspávají Wi-Fi. V nočním okně člen neodejde jen proto, že zhasly signály „jen doma“. Odchod potvrdí změna vstupních dveří.
- **Dlouhodobá nepřítomnost:** viz níže.
- **Host:** automatické vypnutí v čase nebo po několika hodinách.
- **Signály domácnosti:** anonymní signály „někdo je doma“ (např. televize) a senzor pracovního dne pro učení.
- **Kalendáře dovolené:** událost s klíčovým slovem (např. `dovolená, chata`) znamená, že je pryč celá domácnost.
- **Učení:** poločas zapomínání a minimum dnů.

#### Logika

- **Doma:** stačí jeden signál „doma“. Příchod platí hned.
- **Odchod:** člen jde do stavu *právě odešel* a pryč je až po zpoždění odchodu. Když se během zpoždění vrátí, nevznikne žádná událost.
- **Nedostupný signál** (`unavailable`, `unknown`) se ignoruje.
- **Někdo doma:** aspoň jeden člen doma, host nebo signál domácnosti.
- **Dlouhodobě pryč** platí, když je nikdo doma a navíc platí aspoň jedno z:
  - režim dovolená,
  - „pryč do“,
  - událost v kalendáři dovolené,
  - nikdo doma déle než 24 h,
  - nikdo se podle odhadu nevrátí do 12 h.
  Běžný pracovní den tak dlouhodobá nepřítomnost není.
- **Ruční režim** `select.hp_mode`: automaticky, vynutit doma, vynutit pryč, dovolená. Vynucený stav má přednost. „Vynutit pryč“ a dovolenou ukončí potvrzený příchod člena.

## Entity

`entity_id` se vytvoří s prefixem `hp_`. Odběratelé mají entity vybírat v nastavení selektorem.

**Domácnost:**

| Entita | Stav |
|---|---|
| `binary_sensor.hp_someone_home` | on = někdo doma. Atributy `count`, `people`, `since` |
| `binary_sensor.hp_long_away` | on = dlouhodobě pryč, atribut `reason` |
| `binary_sensor.hp_someone_approaching` | on = někdo míří domů |
| `sensor.hp_people_home` | počet členů doma (host se nepočítá) |
| `sensor.hp_household_state` | `home`, `away`, `long_away`, atribut `reason` |
| `sensor.hp_away_since` | od kdy je nikdo doma |
| `sensor.hp_expected_return` | nejbližší očekávaný návrat, atributy `source` (`planned`, `approaching`, `learned`), `person`, `confidence` (0–1) |
| `sensor.hp_expected_return_confidence` | jistota odhadu v % |
| `sensor.hp_expected_return_error` | chyba posledního odhadu v minutách |
| `select.hp_mode` | `auto`, `force_home`, `force_away`, `vacation` |
| `switch.hp_guest` | host doma |
| `datetime.hp_away_until` | plánovaný návrat celé domácnosti |
| `event.hp_household` | `arrived`, `left`, `first_arrived`, `last_left`, `long_away_started`, `long_away_ended`, `mode_changed` |

**Člen** (`<jméno>` = jméno bez diakritiky a mezer):

| Entita | Stav |
|---|---|
| `binary_sensor.hp_<jméno>_home` | on = doma. Atributy `since`, `sources`, `method` (`signal`, `plan`, `manual`) |
| `sensor.hp_<jméno>_state` | `home`, `just_arrived`, `just_left`, `away`, `unknown` |
| `sensor.hp_<jméno>_expected_return` | očekávaný návrat člena |
| `select.hp_<jméno>_mode` | `auto`, `force_home`, `force_away` |
| `datetime.hp_<jméno>_away_until` | plánovaný návrat člena |

**Pravidla:**
- `expected_return` je `unknown`, když nikdo nic neví, a nikdy není v minulosti.
- Po restartu jsou entity chvíli `unavailable`. Odběratel má držet poslední stav.

## Učení

Integrace si pro každého člena i pro celou domácnost vede denní záznamy: přítomnost po půlhodinách a časy příchodů. Uchovává je 70 dní v úložišti integrace, ne v historii HA.

- Odhad návratu: medián příchodů ve stejný den v týdnu a stejný typ dne (pracovní / volno). Při nedostatku dat se použijí všechny dny stejného typu.
- Starší dny mají menší váhu (poločas 4 týdny).
- Dny s dovolenou, ručním režimem nebo „pryč do“ se nepočítají.
- `confidence` vychází z počtu dnů, rozptylu a úspěšnosti minulých odhadů.

Přednost má plán, pak blížení, pak naučený odhad.

## Služby

| Služba | Význam |
|---|---|
| `household_presence.set_away_until` | `until`, volitelně `member`: plánovaný návrat domácnosti nebo člena |
| `household_presence.clear_away_until` | zruší plánovaný návrat |
| `household_presence.reset_learning` | zapomene naučené zvyklosti (všech nebo jednoho člena) |

## Deník, opravy a diagnostika

- **Deník:** zápisy jako „Příchod: Jana“, „Nikdo doma od 7:42“, „Dlouhodobě pryč: dovolená do neděle 18. 10. 18:00“. Stejné události jdou na sběrnici jako `household_presence_event`.
- **Opravy (repairs):** chybějící signál, zaseknutý signál, nedostupný kalendář, člen bez signálů, člen, který nikdy nemůže odejít.
- **Diagnostika:** stav signálů a členů, naučené tabulky, metriky přesnosti. Jména a kalendáře jsou skryté.

## Napojení na topení a další moduly

Například systém topení může číst:

| Vstup | Entita |
|---|---|
| přítomnost domu | `binary_sensor.hp_someone_home` |
| dlouhodobě pryč | `binary_sensor.hp_long_away` |
| očekávaný návrat | `sensor.hp_expected_return` (s atributem `confidence`) |
| přítomnost v pokoji | `binary_sensor.hp_<jméno>_home` |

## Vývoj

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Jádro (`custom_components/household_presence/core/`) nemá žádné importy Home Assistanta a testuje se samostatně (`.venv/bin/pytest tests/core`).

## Vydání verze

1. Zvedni verzi v `manifest.json` a `pyproject.toml` (SemVer).
2. Doplň sekci `## vX.Y.Z — RRRR-MM-DD` do `CHANGELOG.md`.
3. Commit `Release vX.Y.Z: …`, `git tag vX.Y.Z`, push commitu i tagu.
4. GitHub Actions vytvoří release s textem z CHANGELOG a HACS nabídne aktualizaci.

## Známá omezení

- Stačí jeden signál „doma“. Telefon zapomenutý doma na Wi-Fi proto drží člověka doma; řeší to ruční režim člena nebo signál „jen pryč“.
- Člen bez telefonu (jen „jen doma“ signály a plán) se mimo plán pozná až podle zapnutého zařízení.
- Odhad návratu z učení začne fungovat až po několika dnech stejného typu (výchozí minimum 3).
- Výchozí prahy (zpoždění odchodu, noční okno, 24 h, 12 h) jsou odhady, vylaď je podle svého provozu.

## Autor

**[elvisek2020](https://github.com/elvisek2020)** — integrace vznikla jako společný zdroj přítomnosti pro topení a další automatizace domácnosti. Licence MIT.
