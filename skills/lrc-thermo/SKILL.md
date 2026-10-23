---
name: lrc-thermo
description: Čtení a základní analýza termovizních záznamů LabIR (.lrc) – metadata, vykreslení snímku, průměrný/max snímek, statistiky oblastí (ROI), čárový graf teploty v čase, teplotní profil, export do CSV/NPZ. Použij vždy, když uživatel zmíní .lrc soubor, termovizní sekvenci, teplotu v oblasti, snímek z kamery Optherm/LabIR nebo chce graf teploty.
---

# LRC termovize (LabIR)

Soubory `.lrc` čte `scripts/lrc_loading.py` – čistý Python + numpy, funguje na Windows, macOS i Linuxu.
Podporuje LRC verze 2 s 1 streamem (uint16/float), bez externích zařízení a bez dynamické hlavičky;
jinou variantu odmítne chybou `nepodporovaná varianta LRC` – v tom případě to uživateli řekni, neobcházej to.
Neúplný poslední snímek (přerušený zápis) se vynechá a `info` na to upozorní.
Data: `frames` tvaru **(T, H, W)** float32 ve **°C**, `t` v sekundách od prvního snímku.
Typický záznam: 320×240 px, ~23 fps. Celý záznam se načítá do RAM (130 MB soubor ≈ 900 snímků, ~270 MB RAM).

Všechny cesty níže jsou relativní k **adresáři tohoto skillu** (složka, ve které leží tento SKILL.md) –
v příkazech ho vždy nahraď absolutní cestou, dále značeno `<SKILL>`.

## Spouštění

```
python "<SKILL>/scripts/lrc_tool.py" <příkaz> ...
```

Python: pokud má aktuální projekt virtuální prostředí (`.venv/Scripts/python.exe` na Windows, `.venv/bin/python` jinde),
použij ho; jinak `python` (příp. `python3`) z PATH.
Potřebné balíčky jsou v `<SKILL>/requirements.txt` (numpy, matplotlib, scipy). Při `ModuleNotFoundError`
nabídni uživateli `python -m pip install -r "<SKILL>/requirements.txt"` – neinstaluj bez souhlasu.

Výstupy (PNG, CSV) ukládej do složky `results/` aktuálního projektu nebo kam uživatel řekne, ne do adresáře skillu ani vedle zdrojových dat.
Vygenerované PNG si **prohlédni** (otevři obrázek, pokud to tvé prostředí umí) a teprve pak popiš výsledek uživateli;
pokud obrázek vidět nemůžeš, opírej se o čísla, která příkazy vypisují, a uživateli řekni cestu k souboru.

## Příkazy

| Příkaz | Co dělá | Příklad |
|---|---|---|
| `info FILE` | JSON: počet snímků, rozlišení, délka, fps, min/max/průměr, nejteplejší pixel, čas pořízení, parametry měření (emisivita, vzdálenost, odražená teplota, vlhkost…) | `info x.lrc` |
| `frame FILE -o out.png` | Snímek s barevnou škálou. `--index N` (záporný od konce) nebo `--time T`, `--roi`, `--hotspot`, `--cmap`, `--vmin/--vmax` | `frame x.lrc --time 5 --hotspot -o f.png` |
| `mean FILE -o out.png` | Snímek agregovaný přes čas: `--stat mean|max|min|std`, `--start/--end` | `mean x.lrc --stat std -o std.png` |
| `roi FILE --roi ...` | JSON souhrn za každou ROI (průměr, první/poslední, min/max a jejich čas, trend °C/s) + `--csv` časová řada | `roi x.lrc --roi "oko=circle:160,120,20" --csv r.csv` |
| `plot FILE --roi ... -o out.png` | Čárový graf teploty v čase. `--stat mean,max`, `--smooth N`, `--mark T`, `--with-frame` (vedle snímek s ROI) | `plot x.lrc --roi rect:100,80,40,30 --with-frame -o p.png` |
| `profile FILE --line x1,y1,x2,y2 -o out.png` | Teplotní profil podél úsečky v daném snímku | `profile x.lrc --line 50,120,270,120 -o pr.png` |
| `export FILE -o out.npz` | Uloží `frames` + `time_axes` do .npz (rychlé opakované načítání; všechny příkazy berou i .npz) | `export x.lrc --step 2 -o x.npz` |

Bez `--roi` se počítá z celého snímku. Společné: `--start/--end` [s] ořez času, `--step N` podvzorkování.
CSV používá oddělovač `;` (Excel v české lokalizaci), jiný přes `--delimiter`.

### ROI syntaxe (lze opakovat `--roi`)
- `rect:x,y,w,h` · `circle:cx,cy,r` · `point:x,y` · `poly:x1,y1;x2,y2;x3,y3` · `full`
- Pojmenování: `"levé oko=circle:120,100,15"` (jméno se objeví v legendě, CSV i JSON)
- x = sloupec, y = řádek, počátek vlevo nahoře, pixely.

## Doporučený postup

1. `info` – zjisti rozměry, délku, rozsah teplot a polohu nejteplejšího pixelu.
2. Pokud uživatel nezadal souřadnice ROI: vykresli `frame --hotspot` (příp. `mean`), prohlédni PNG, navrhni ROI podle obrazu a řekni uživateli, jaké souřadnice jsi zvolil.
3. `frame --roi ...` pro kontrolu, že ROI sedí, pak `roi` / `plot`.
4. Více souborů → spouštěj příkaz v cyklu; pro opakovanou práci s jedním velkým souborem nejdřív `export` do .npz (do dočasné složky).

## Vlastní analýzy

Na cokoliv mimo příkazy napiš krátký skript (do dočasné složky, ne do projektu uživatele) a načti data přes skill:

```python
import sys; sys.path.insert(0, r"<SKILL>/scripts")
from lrc_tool import load, parse_roi, roi_series, select_range
frames, t, meta = load(path)            # frames (T,H,W) °C, t v s; funguje pro .lrc i .npz
```

Přímo z čtečky: `from lrc_loading import read_lrc, read_lrc_info` – `read_lrc(path, start, stop, step)` načte jen
vybrané snímky (rychlé u velkých souborů), `read_lrc_info(path)` vrátí metadata bez čtení teplot.
Popis formátu je v docstringu `lrc_loading.py`.
Pokud má aktuální projekt vlastní specializované moduly pro .lrc (např. detekce oka, mrknutí), použij je místo psaní nových.
