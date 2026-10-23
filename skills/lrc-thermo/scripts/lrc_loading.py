# -*- coding: utf-8 -*-
"""
Čtečka termovizních záznamů LabIR (.lrc, verze 2) v čistém Pythonu – jen numpy, libovolný OS.

Podporovaná varianta (viz specifikace „LRC file format.xlsx“):
    - 1 stream, datový typ uint16 nebo float32
    - bez externích zařízení, bez dynamické části hlavičky (příznaky = 0)
Ostatní varianty skončí výjimkou UnsupportedLRCError.

Struktura:
    Hlavička souboru (25 B)
        0  4×uint8  "LRC\\0"
        4  uint8    verze (2)
        5  int64    časová značka souboru (.NET DateTime.ToBinary)
        13 uint8    počet externích zařízení
        14 uint8    počet streamů
        15 uint8    datový typ streamu (0 = uint16)
        16 uint8    jednotky streamu (2 = °C)
        17 uint16   šířka
        19 uint16   výška
        21 uint32   příznaky dynamické části hlavičky
    Snímek (opakuje se)
        int64       časová značka snímku
        12× float   Tmin, Tmax (jednotky streamu), rozsah kamery min/max [K], emisivita,
                    odražená teplota [K], vzdálenost [m], teplota atmosféry [K], rel. vlhkost,
                    tau, teplota okénka [K], propustnost okénka
        uint8       automatické tau
        H×W         data (uint16: T = Tmin + raw / 65535 · (Tmax − Tmin); float: přímo teploty)

Použití:
    from lrc_loading import read_lrc, load_lrc
    frames, t, meta = read_lrc("x.lrc")     # frames (T, H, W) float32, t [s] od prvního snímku
    frames, t = load_lrc("x.lrc")           # (H, W, T) – kompatibilní s původní DLL čtečkou
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np

FILE_HEADER = np.dtype([
    ("signature", "S4"), ("version", "u1"), ("timestamp", "<i8"),
    ("n_devices", "u1"), ("n_streams", "u1"), ("data_type", "u1"), ("units", "u1"),
    ("width", "<u2"), ("height", "<u2"), ("dyn_flags", "<u4"),
])
assert FILE_HEADER.itemsize == 25

PARAM_NAMES = ("t_min", "t_max", "camera_range_min_K", "camera_range_max_K", "emissivity",
               "reflected_temp_K", "distance_m", "atmosphere_temp_K", "rel_humidity", "tau",
               "window_temp_K", "window_transmission")

# Kód datového typu → numpy typ. 0 = uint16 ověřeno na datech; 1 = float32 je předpoklad
# (specifikace kódy nevyjmenovává).
DATA_TYPES = {0: np.dtype("<u2"), 1: np.dtype("<f4")}
UNITS = {2: "°C"}

_TICKS_MASK = (1 << 62) - 1
_EPOCH = dt.datetime(1, 1, 1)


class UnsupportedLRCError(ValueError):
    """Soubor je validní LRC, ale používá variantu formátu, kterou čtečka neumí."""


def _net_datetime(value: int) -> dt.datetime:
    """Dekóduje .NET DateTime.ToBinary(): bity 62–63 = Kind, zbytek ticky po 100 ns.
    Kind Local (2) i Utc (1) ukládají UTC čas → vrací aware datetime v UTC."""
    value &= (1 << 64) - 1
    kind = value >> 62
    t = _EPOCH + dt.timedelta(microseconds=(value & _TICKS_MASK) // 10)
    return t.replace(tzinfo=dt.timezone.utc) if kind in (1, 2) else t


def _frame_dtype(width: int, height: int, data_type: np.dtype) -> np.dtype:
    return np.dtype([
        ("timestamp", "<i8"), ("params", "<f4", (12,)), ("auto_tau", "u1"),
        ("data", data_type, (height, width)),
    ])


def _open(file_path) -> tuple[Path, np.ndarray, np.dtype, int, dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"LRC soubor neexistuje: {path}")
    size = path.stat().st_size
    if size < FILE_HEADER.itemsize:
        raise ValueError(f"{path.name}: soubor je kratší než hlavička LRC ({size} B).")
    hdr = np.fromfile(path, dtype=FILE_HEADER, count=1)[0]

    if hdr["signature"] != b"LRC":  # S4 ořízne koncovou \0
        raise ValueError(f"{path.name}: není LRC soubor (signatura {bytes(hdr['signature'])!r}).")
    problems = []
    if hdr["version"] != 2:
        problems.append(f"verze {hdr['version']} (podporována 2)")
    if hdr["n_devices"] != 0:
        problems.append(f"{hdr['n_devices']} externích zařízení (podporováno 0)")
    if hdr["n_streams"] != 1:
        problems.append(f"{hdr['n_streams']} streamů (podporován 1)")
    if hdr["dyn_flags"] != 0:
        problems.append(f"dynamická část hlavičky (příznaky 0x{int(hdr['dyn_flags']):08x})")
    if hdr["data_type"] not in DATA_TYPES:
        problems.append(f"datový typ streamu {hdr['data_type']} (podporováno: {sorted(DATA_TYPES)})")
    if problems:
        raise UnsupportedLRCError(f"{path.name}: nepodporovaná varianta LRC – " + "; ".join(problems))

    w, h = int(hdr["width"]), int(hdr["height"])
    data_type = DATA_TYPES[int(hdr["data_type"])]
    fdt = _frame_dtype(w, h, data_type)
    # neúplný poslední snímek (přerušený zápis) se zahodí – stejně jako DLL
    n_frames = (size - FILE_HEADER.itemsize) // fdt.itemsize
    info = {
        "file": str(path.resolve()),
        "version": int(hdr["version"]),
        "start_time_utc": _net_datetime(int(hdr["timestamp"])),
        "width": w, "height": h, "n_frames": int(n_frames),
        "data_type": str(data_type),
        "units": UNITS.get(int(hdr["units"]), f"kód {int(hdr['units'])}"),
        "truncated_bytes": int((size - FILE_HEADER.itemsize) % fdt.itemsize),
    }
    return path, hdr, fdt, n_frames, info


def _memmap(path: Path, fdt: np.dtype, n_frames: int) -> np.ndarray:
    if n_frames == 0:
        return np.zeros(0, dtype=fdt)
    return np.memmap(path, dtype=fdt, mode="r", offset=FILE_HEADER.itemsize, shape=(n_frames,))


def read_lrc_info(file_path) -> dict:
    """Metadata souboru a parametry měření z prvního snímku – bez čtení teplotních dat."""
    path, _, fdt, n, info = _open(file_path)
    if n:
        mm = _memmap(path, fdt, n)
        info["frame_params"] = {k: round(float(v), 4) for k, v in zip(PARAM_NAMES, mm[0]["params"])}
        info["auto_tau"] = bool(mm[0]["auto_tau"])
        ts = mm["timestamp"].astype(np.int64) & _TICKS_MASK
        info["duration_s"] = float((ts[-1] - ts[0]) / 1e7)
        del mm
    return info


def read_lrc(file_path, start: int = 0, stop: int | None = None, step: int = 1,
             chunk: int = 256) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Načte snímky [start:stop:step].

    Vrací
    -----
    frames : (T, H, W) float32, teploty v jednotkách streamu (u našich souborů °C)
    t      : (T,) float64, čas v sekundách od prvního snímku souboru
    info   : dict – metadata (viz read_lrc_info)
    """
    path, _, fdt, n, info = _open(file_path)
    mm = _memmap(path, fdt, n)
    idx = np.arange(n)[start:stop:step]
    frames = np.empty((len(idx), info["height"], info["width"]), dtype=np.float32)
    ts_all = mm["timestamp"].astype(np.int64) & _TICKS_MASK if n else np.zeros(0, np.int64)
    is_uint16 = fdt["data"].base == np.dtype("<u2")
    for c in range(0, len(idx), chunk):
        sel = idx[c:c + chunk]
        rec = mm[sel] if step != 1 else mm[sel[0]:sel[-1] + 1]
        data = rec["data"]
        if is_uint16:
            p = rec["params"]
            t_min = p[:, 0, None, None].astype(np.float32)
            t_max = p[:, 1, None, None].astype(np.float32)
            frames[c:c + len(sel)] = t_min + data.astype(np.float32) * ((t_max - t_min) / np.float32(65535))
        else:
            frames[c:c + len(sel)] = data
    t = (ts_all[idx] - ts_all[0]) / 1e7 if n else np.zeros(0)
    if n:
        info["frame_params"] = {k: round(float(v), 4) for k, v in zip(PARAM_NAMES, mm[0]["params"])}
        info["auto_tau"] = bool(mm[0]["auto_tau"])
    del mm
    return frames, t.astype(np.float64), info


def load_lrc(file_path, progress=False):
    """Kompatibilní rozhraní s původní DLL čtečkou: (H, W, T) float32, time_axes float32 [s]."""
    frames, t, info = read_lrc(file_path)
    if progress:
        print(f"  {Path(file_path).name}  [{info['width']}x{info['height']}]  {len(t)} frames",
              file=sys.stderr)
    return np.ascontiguousarray(np.transpose(frames, (1, 2, 0))), t.astype(np.float32)
