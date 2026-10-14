# Changelog

Poznámky k vydání. Sekce `## vX.Y.Z` se při releasu automaticky použije jako
text vydání na GitHubu — a ten Home Assistant / HACS ukazuje v okně aktualizace.

Nejnovější verze je nahoře.

## v0.3.0 — 2026-10-14

### ✨ Novinky

- **Skutečné časy změn jako entity:** dashboardy ukazují `last_changed`, který se při restartu HA nastaví na čas restartu. Nové časové entity mají skutečný čas a po restartu se obnoví beze skoku:
  - člen: `sensor.hp_<člen>_since` (Změna stavu), `sensor.hp_<člen>_last_arrived` (Poslední příchod), `sensor.hp_<člen>_last_left` (Poslední odchod),
  - domácnost: `sensor.hp_someone_home_since`, `sensor.hp_multiple_home_since`,
  - skupina: `sensor.hp_group_<název>_since`.
- Poslední příchod a odchod se začnou plnit od prvního příchodu nebo odchodu po aktualizaci.

Po aktualizaci restartuj Home Assistant.

## v0.2.0 — 2026-10-13

### ✨ Novinky

- **Víc lidí doma:** `binary_sensor.hp_multiple_home` je zapnutý, když je doma aspoň nastavený počet členů (výchozí 2, Možnosti → Domácnost). Host se nepočítá.
- **Skupiny členů:** nový typ položky „Skupina“ (název, členové, kolik jich musí být doma). Vytvoří `binary_sensor.hp_group_<název>_home` a `sensor.hp_group_<název>_expected_return` s nejbližším návratem člena skupiny.
- Ruční režim domácnosti má přednost i před skupinami a počtem lidí. Deník zapisuje „Víc lidí doma“ a „Skupina …: doma / pryč“.

### 🐛 Opravy

- Krátký výpadek signálu (např. reload integrace UniFi: `unavailable` a zpět) už během plánu neznamená falešný příchod. Výpadek neposouvá ani zpoždění příchodu a dobu zaseknutí. Integrace si to pamatuje i přes restart.

Po aktualizaci restartuj Home Assistant.

## v0.1.0 — 2026-10-12

### ✨ Novinky

- Kdo je doma, jestli je doma někdo, krátce / dlouhodobě pryč a očekávaný návrat.
- Členové domácnosti jako samostatné položky, každý s vlastními signály (doma i pryč, jen doma, jen pryč).
- Plán z kalendářů s překlenutím přestávek, předstihem a dojezdem; zaseknutý signál během plánu se ignoruje.
- Noční okno proti Wi-Fi sleep, potvrzení odchodu dveřmi.
- Režimy (automaticky, vynutit doma, vynutit pryč, dovolená), host s automatickým vypnutím, „pryč do“ pro domácnost i člena.
- Učení zvyklostí a odhad návratu s jistotou, blížení k domu.
- Deník, event entita, diagnostika, opravy (repairs) a služby; čeština a angličtina.
