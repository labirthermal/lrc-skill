# lrc-thermo – skill pro AI agenty

Skill ve formátu [Agent Skills](https://agentskills.io) (`SKILL.md` + skripty), díky kterému Claude Code, OpenAI Codex,
GitHub Copilot, Gemini CLI a další AI agenti umí číst termovizní záznamy LabIR (`.lrc`) a dělat s nimi základní analýzy:

- metadata záznamu (rozlišení, délka, fps, rozsah teplot, nejteplejší pixel)
- vykreslení snímku s barevnou škálou, oblastmi (ROI) a hotspotem
- průměrný / max / min / std snímek přes čas
- statistiky oblastí v čase + export do CSV
- čárový graf teploty v čase (více oblastí, vyhlazení, značky událostí)
- teplotní profil podél úsečky
- export do `.npz` pro vlastní analýzy

Stačí agentovi napsat např. *„Ukaž mi snímek z mereni.lrc v čase 5 s a vykresli průběh teploty v oblasti kolem nejteplejšího bodu“*.

## Požadavky

- Windows, macOS nebo Linux – čtečka je v čistém Pythonu, žádná DLL
- Python 3.10+ s balíčky z [`skills/lrc-thermo/requirements.txt`](skills/lrc-thermo/requirements.txt):

```
python -m pip install numpy matplotlib scipy
```

## Instalace

Skill je jen složka [`skills/lrc-thermo`](skills/lrc-thermo). Nainstaluješ ho tak, že ji zkopíruješ tam,
kde tvůj nástroj hledá skilly. Agent pak skill použije sám, když zmíníš `.lrc` soubor nebo termovizní záznam.
Po instalaci spusť novou session / restartuj nástroj.

### Claude Code – jako plugin (doporučeno, snadné aktualizace)

```
/plugin marketplace add jsroub/lrc-skill
/plugin install lrc-thermo@lrc-skill
```

Aktualizace: `/plugin marketplace update lrc-skill`. Ruční vyvolání: `/lrc-thermo:lrc-thermo`.

### Kam zkopírovat složku

| Nástroj | Pro všechny projekty | Jen pro jeden projekt |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `<projekt>/.claude/skills/` |
| OpenAI Codex | `~/.agents/skills/` | `<projekt>/.agents/skills/` |
| GitHub Copilot (CLI, VS Code agent mode, cloud agent) | `~/.copilot/skills/` nebo `~/.agents/skills/` | `<projekt>/.github/skills/` nebo `<projekt>/.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` nebo `~/.agents/skills/` | `<projekt>/.gemini/skills/` nebo `<projekt>/.agents/skills/` |
| Claude.ai / Claude desktop | v nastavení v sekci Skills nahraj zip složky `lrc-thermo` | – |

`~` je domovská složka (Windows: `%USERPROFILE%`). Složka `.agents/skills` funguje pro Codex, Copilot i Gemini CLI zároveň.
Umístění se mohou mezi verzemi nástrojů měnit – v případě pochybností ověř v jejich dokumentaci.
Projektovou kopii commitni do gitu, ať ji mají i kolegové.

Příklad – instalace do `~/.agents/skills` z gitu:

```bash
git clone https://github.com/jsroub/lrc-skill.git
mkdir -p ~/.agents/skills && cp -r lrc-skill/skills/lrc-thermo ~/.agents/skills/
```

PowerShell:

```powershell
git clone https://github.com/jsroub/lrc-skill.git
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse lrc-skill\skills\lrc-thermo "$HOME\.agents\skills\"
```

### Nástroje bez podpory skillů (Cursor, Aider, …)

Zkopíruj složku kamkoliv a do instrukcí agenta (`AGENTS.md`, `.cursor/rules`, `CONVENTIONS.md`…) přidej:

```markdown
Pro práci s termovizními .lrc soubory používej nástroj `<cesta>/lrc-thermo/scripts/lrc_tool.py`.
Před použitím si přečti návod `<cesta>/lrc-thermo/SKILL.md`.
```

## Použití bez AI agenta

Nástroj je obyčejné CLI:

```
python skills/lrc-thermo/scripts/lrc_tool.py info mereni.lrc
python skills/lrc-thermo/scripts/lrc_tool.py frame mereni.lrc --time 5 --hotspot -o snimek.png
python skills/lrc-thermo/scripts/lrc_tool.py plot mereni.lrc --roi "oko=circle:160,120,20" --with-frame -o graf.png
python skills/lrc-thermo/scripts/lrc_tool.py roi mereni.lrc --roi rect:100,80,40,30 --csv data.csv
```

Nápověda: `python skills/lrc-thermo/scripts/lrc_tool.py <příkaz> --help`.

## Podporovaný formát

LRC verze 2 s jedním streamem (uint16 nebo float), bez externích zařízení a bez dynamické části hlavičky –
to je varianta, kterou ukládají kamery Optherm. Jiné varianty čtečka odmítne srozumitelnou chybou.
Struktura souboru je popsaná v docstringu [`lrc_loading.py`](skills/lrc-thermo/scripts/lrc_loading.py).
Čtečka byla ověřena proti původní `LRCRecording.dll` na 484 záznamech (shoda teplot na úrovni zaokrouhlení float32).

Python API:

```python
from lrc_loading import read_lrc, read_lrc_info
frames, t, info = read_lrc("mereni.lrc")          # (T, H, W) °C, t [s], metadata
frames, t, info = read_lrc("mereni.lrc", 100, 200) # jen snímky 100–199
```
