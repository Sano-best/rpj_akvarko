# Zadanie projektu: AquaControl

**Názov:** IoT systém na monitorovanie kvality vody v akváriu (aplikácia AquaControl)

## Anotácia

Systém na monitorovanie kvality vody v akváriu, ktorý pomocou senzorov sleduje parametre vody, ako sú teplota, pH, TDS a zákal, a automaticky ukladá údaje na server. Aplikácia umožňuje zobrazovať aktuálne hodnoty, historické štatistiky a grafy, sledovať vývoj kvality vody a upozorniť používateľa na neštandardné hodnoty.

## Problém, ktorý projekt rieši

Kvalitu vody v akváriu (NO₂, NO₃, GH, KH, pH, Cl₂) sa dnes sleduje ručne testovacími prúžkami. Opakované testy stoja čas aj peniaze a z jednotlivých testov nie je vidieť, **kedy** hodnota stúpla alebo klesla. Cieľom je mať jedno miesto, kde sa merania ukladajú, zobrazujú v prehľadnej histórii a kde aplikácia sama upozorní na hodnotu mimo bezpečného rozsahu.

## Ciele

1. Ukladať merania (ručné aj automatické) do jednej databázy.
2. Zobrazovať aktuálny stav a históriu meraní, neskôr aj grafy.
3. Upozorniť používateľa, keď je hodnota príliš nízka alebo príliš vysoká.
4. Používať lacné komponenty a vlastný server, aby bolo riešenie cenovo dostupné.

## Hybridný prístup k meraniu

- **Automaticky (plánované):** teplota, pH, EC/TDS a zákal zo senzorov pripojených k ESP32.
- **Ručne:** NO₂, NO₃, GH, KH a Cl₂ sa merajú testom a zadávajú sa do aplikácie, pretože ich lacné nepretržité meranie nie je jednoduché. Všetky hodnoty sa ukladajú do tej istej databázy.

## Fázy projektu

| Fáza | Obsah | Stav |
|---|---|---|
| 1 | Desktopová aplikácia (Python, PyQt6, SQLite): ručné zadávanie, história, upozornenia, nastaviteľné hranice | **Hotové (v1.0)** |
| 2 | Import fotky testovacieho prúžku a rozpoznanie farieb (OpenCV); používateľ hodnoty pred uložením skontroluje | Plánované |
| 3 | Server (REST API a databáza) a príjem meraní z ESP32 so senzormi | Plánované |
| ďalej | Grafy a filtrovanie histórie, databáza rýb a porovnanie parametrov vody s nárokmi chovaných rýb | Plánované |

## Rozsah verzie 1.0

Verzia 1.0 je lokálna desktopová aplikácia bez servera. Podrobný stav jednotlivých požiadaviek je v súboroch `funkcionalne-poziadavky.xlsx` a `nefunkcionalne-poziadavky.xlsx`.

## Technológie

- Aplikácia: Python, PyQt6, SQLite
- Plánované: OpenCV (fotka), matplotlib (grafy), server v Pythone (napr. FastAPI), ESP32 so senzormi

## Výstupy projektu

Priečinok `aquacontroll` obsahuje požiadavky, analýzu (roly a use cases), návrh (ER diagram, schéma databázy, návrh rozhraní), implementáciu, testovanie a dokumentáciu (inštalačná a používateľská príručka).
