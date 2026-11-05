# AquaControl

Aplikácia na evidenciu a sledovanie kvality vody v akváriu. Ročníkový projekt: IoT systém na monitorovanie kvality vody v akváriu.

Verzia **1.0** je desktopová aplikácia (Python, PyQt6, SQLite). Server a senzory (ESP32) sú plánované.

## Čo aplikácia vie

- zadať výsledky testu vody (NO₃, NO₂, GH, KH, pH, Cl₂) s dátumom a poznámkou,
- upozorniť oknom, keď je zadaná hodnota príliš nízka alebo príliš vysoká,
- zobraziť posledné meranie a upozornenia na stránke Domov,
- zobraziť históriu meraní (hodnoty mimo hraníc sú červené) a vymazať meranie,
- nastaviť povolené hranice pre každý parameter,
- tmavý režim,
- vybrať fotku testovacieho prúžku (zatiaľ len náhľad).

## Rýchly štart (Windows)

```
cd aquacontroll\04_Implementacia\src
py -m pip install -r requirements.txt
py aquacontroll.py
```

Podrobný postup je v `06_Dokumentacia/instalacna-prirucka.docx`.

## Testy

```
py aquacontroll\05_Testovanie\test_aquacontroll.py
```

Testy bežia bez otvárania okna a pracujú s dočasnou databázou. Výsledky sú v `05_Testovanie/testovacie-scenare.xlsx`.

## Štruktúra priečinka

| Priečinok | Obsah |
|---|---|
| `01_Poziadavky` | zadanie, funkčné a nefunkčné požiadavky, roly systému |
| `02_Analyza` | use cases (dokument a diagram) |
| `03_Navrh` | ER diagram, schéma databázy, návrh rozhraní |
| `04_Implementacia/src` | zdrojový kód aplikácie |
| `05_Testovanie` | testovacie scenáre, zistené chyby, automatické testy |
| `06_Dokumentacia` | inštalačná a používateľská príručka |

## Stav a plány

Podiel splnených požiadaviek je v hárku „Prehľad“ v súboroch s požiadavkami.

1. **Hotové:** aplikácia s ručným zadávaním, históriou, upozorneniami a nastaviteľnými hranicami.
2. **Ďalej:** rozpoznanie hodnôt z fotky testovacieho prúžku, potom server a príjem meraní zo senzorov.
3. **Neskôr:** grafy, filtrovanie histórie a databáza rýb (kontrola, či sú hodnoty vody vhodné pre chované ryby).
