# -*- coding: utf-8 -*-
"""
lrc_tool.py – CLI pro rychlou práci s termovizními .lrc soubory (LabIR).

Používá lrc_loading.read_lrc (čistý Python + numpy) – data mají tvar (T, H, W), °C.

Příkazy:
    info     FILE                         – metadata a globální statistiky
    frame    FILE [--index|--time] -o PNG – vykreslení snímku (+ ROI, hotspot)
    mean     FILE -o PNG                  – průměrný / max / min / std snímek přes čas
    roi      FILE --roi ... [--csv]       – statistiky oblastí (min/max/mean/std) po snímcích
    plot     FILE --roi ... -o PNG        – čárový graf teploty v čase
    profile  FILE --line x1,y1,x2,y2 -o PNG – teplotní profil podél úsečky
    export   FILE -o NPZ                  – uložení do .npz pro vlastní analýzu

Formát ROI (lze opakovat --roi):
    rect:x,y,w,h      circle:cx,cy,r      point:x,y
    poly:x1,y1;x2,y2;x3,y3                full   (celý snímek)
    Volitelně jméno: "levé oko=circle:120,100,15"
Souřadnice jsou v pixelech, x = sloupec, y = řádek, počátek vlevo nahoře.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------------------
# Načítání
# ---------------------------------------------------------------------------

def load(path: str) -> tuple[np.ndarray, np.ndarray, dict]:
    """Načte .lrc (nebo .npz z příkazu export) → frames (T,H,W), časy (T,), metadata."""
    p = Path(path)
    if p.suffix.lower() == ".npz":
        d = np.load(p)
        frames, t = d["frames"], np.asarray(d["time_axes"], dtype=np.float64)
        meta = {}
    else:
        from lrc_loading import read_lrc
        frames, t, meta = read_lrc(p)
    meta.update(source=str(p.resolve()), fps=_fps(t))
    return frames, t, meta


def _fps(t: np.ndarray) -> float:
    if len(t) < 2:
        return float("nan")
    dt = float(np.mean(np.diff(t)))
    return round(1.0 / dt, 2) if dt > 0 else float("nan")


def select_range(frames, t, start=None, end=None, step=1):
    """Ořízne sekvenci podle času [s] a podvzorkuje krokem step."""
    mask = np.ones(len(t), dtype=bool)
    if start is not None:
        mask &= t >= start
    if end is not None:
        mask &= t <= end
    idx = np.nonzero(mask)[0][::max(1, step)]
    return frames[idx], t[idx], idx


def frame_index(t: np.ndarray, index: int | None, time: float | None) -> int:
    if time is not None:
        return int(np.argmin(np.abs(t - time)))
    i = 0 if index is None else index
    if i < 0:
        i += len(t)
    if not 0 <= i < len(t):
        raise SystemExit(f"Index snímku {i} mimo rozsah 0..{len(t) - 1}")
    return i


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------

def parse_roi(spec: str, shape: tuple[int, int]) -> tuple[str, np.ndarray, dict]:
    """Vrátí (jméno, bool maska H×W, geometrie pro vykreslení)."""
    name = None
    if "=" in spec:
        name, spec = spec.split("=", 1)
    kind, _, args = spec.partition(":")
    kind = kind.strip().lower()
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    if kind == "full":
        mask = np.ones(shape, dtype=bool)
        geom = {"kind": "full"}
    elif kind == "rect":
        x, y, rw, rh = (int(float(v)) for v in args.split(","))
        mask = (xx >= x) & (xx < x + rw) & (yy >= y) & (yy < y + rh)
        geom = {"kind": "rect", "x": x, "y": y, "w": rw, "h": rh}
    elif kind == "circle":
        cx, cy, r = (float(v) for v in args.split(","))
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2
        geom = {"kind": "circle", "cx": cx, "cy": cy, "r": r}
    elif kind == "point":
        x, y = (int(float(v)) for v in args.split(","))
        mask = np.zeros(shape, dtype=bool)
        mask[y, x] = True
        geom = {"kind": "point", "x": x, "y": y}
    elif kind == "poly":
        from matplotlib.path import Path as MplPath
        pts = [tuple(float(v) for v in p.split(",")) for p in args.split(";") if p.strip()]
        mask = MplPath(pts).contains_points(np.c_[xx.ravel(), yy.ravel()]).reshape(shape)
        geom = {"kind": "poly", "pts": pts}
    else:
        raise SystemExit(f"Neznámý typ ROI: {kind!r} (rect/circle/point/poly/full)")
    if not mask.any():
        raise SystemExit(f"ROI {spec!r} neobsahuje žádný pixel (rozměr snímku {w}×{h}).")
    return name or spec, mask, geom


def parse_rois(specs: list[str] | None, shape) -> list[tuple[str, np.ndarray, dict]]:
    return [parse_roi(s, shape) for s in (specs or ["full"])]


def roi_series(frames: np.ndarray, mask: np.ndarray) -> dict[str, np.ndarray]:
    px = frames[:, mask]  # (T, N)
    return {
        "mean": px.mean(axis=1),
        "max": px.max(axis=1),
        "min": px.min(axis=1),
        "std": px.std(axis=1),
    }


def draw_rois(ax, rois):
    import matplotlib.patches as mpatches
    colors = ["#00e5ff", "#76ff03", "#ff4081", "#ffea00", "#ffffff", "#b388ff"]
    for i, (name, _, g) in enumerate(rois):
        c = colors[i % len(colors)]
        if g["kind"] == "full":
            continue
        if g["kind"] == "rect":
            ax.add_patch(mpatches.Rectangle((g["x"] - .5, g["y"] - .5), g["w"], g["h"],
                                            fill=False, ec=c, lw=1.5))
            lx, ly = g["x"], g["y"] - 2
        elif g["kind"] == "circle":
            ax.add_patch(mpatches.Circle((g["cx"], g["cy"]), g["r"], fill=False, ec=c, lw=1.5))
            lx, ly = g["cx"] - g["r"], g["cy"] - g["r"] - 2
        elif g["kind"] == "point":
            ax.plot(g["x"], g["y"], "+", color=c, ms=10, mew=2)
            lx, ly = g["x"] + 3, g["y"] - 3
        else:
            ax.add_patch(mpatches.Polygon(g["pts"], closed=True, fill=False, ec=c, lw=1.5))
            lx, ly = g["pts"][0]
        ax.text(lx, ly, name, color=c, fontsize=8, va="bottom",
                bbox=dict(fc="black", alpha=.5, lw=0, pad=1))


# ---------------------------------------------------------------------------
# Příkazy
# ---------------------------------------------------------------------------

def cmd_info(a):
    frames, t, meta = load(a.file)
    mean_t = frames.mean(axis=(1, 2))
    info = {
        "file": str(Path(a.file).resolve()),
        "n_frames": int(frames.shape[0]),
        "width": int(frames.shape[2]),
        "height": int(frames.shape[1]),
        "duration_s": round(float(t[-1] - t[0]), 3),
        "fps": meta.get("fps", _fps(t)),
        "dt_min_s": round(float(np.diff(t).min()), 4) if len(t) > 1 else None,
        "dt_max_s": round(float(np.diff(t).max()), 4) if len(t) > 1 else None,
        "temp_min_C": round(float(frames.min()), 3),
        "temp_max_C": round(float(frames.max()), 3),
        "temp_mean_C": round(float(frames.mean()), 3),
        "frame_mean_C_first": round(float(mean_t[0]), 3),
        "frame_mean_C_last": round(float(mean_t[-1]), 3),
        "frame_mean_C_range": [round(float(mean_t.min()), 3), round(float(mean_t.max()), 3)],
    }
    max_pos = np.unravel_index(np.argmax(frames), frames.shape)
    info["hottest_pixel"] = {"frame": int(max_pos[0]), "x": int(max_pos[2]), "y": int(max_pos[1])}
    if "start_time_utc" in meta:
        start = meta["start_time_utc"]
        info["start_time_local"] = (start.astimezone() if start.tzinfo else start).isoformat(timespec="milliseconds")
        info["units"] = meta["units"]
        info["measurement_params_first_frame"] = meta.get("frame_params")
        if meta.get("truncated_bytes"):
            info["warning"] = f"neúplný poslední snímek ({meta['truncated_bytes']} B) byl vynechán"
    print(json.dumps(info, ensure_ascii=False, indent=2))


def _imshow(ax, img, a, title):
    vmin = a.vmin if a.vmin is not None else float(np.percentile(img, 0.5))
    vmax = a.vmax if a.vmax is not None else float(np.percentile(img, 99.5))
    im = ax.imshow(img, cmap=a.cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("x [px]")
    ax.set_ylabel("y [px]")
    cb = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("°C")
    return im


def _mark_hotspot(ax, img):
    y, x = np.unravel_index(np.argmax(img), img.shape)
    ax.plot(x, y, "x", color="white", ms=8, mew=2)
    ax.annotate(f"max {img[y, x]:.2f} °C", (x, y), xytext=(5, 5), textcoords="offset points",
                color="white", fontsize=8, bbox=dict(fc="black", alpha=.5, lw=0, pad=1))


def cmd_frame(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frames, t, _ = load(a.file)
    i = frame_index(t, a.index, a.time)
    img = frames[i]
    rois = parse_rois(a.roi, img.shape) if a.roi else []
    fig, ax = plt.subplots(figsize=(8, 6), dpi=a.dpi)
    _imshow(ax, img, a, f"{Path(a.file).name}\nsnímek {i}  t = {t[i]:.3f} s")
    draw_rois(ax, rois)
    if a.hotspot:
        _mark_hotspot(ax, img)
    fig.tight_layout()
    fig.savefig(a.output)
    print(f"Uloženo: {Path(a.output).resolve()}  (snímek {i}, t={t[i]:.3f} s, "
          f"min {img.min():.2f} / max {img.max():.2f} / průměr {img.mean():.2f} °C)")
    for name, mask, _ in rois:
        px = img[mask]
        print(f"  ROI {name}: n={px.size} min {px.min():.2f}  max {px.max():.2f}  "
              f"průměr {px.mean():.2f}  std {px.std():.3f} °C")


def cmd_mean(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frames, t, _ = load(a.file)
    frames, t, _ = select_range(frames, t, a.start, a.end)
    img = {"mean": frames.mean(0), "max": frames.max(0), "min": frames.min(0),
           "std": frames.std(0)}[a.stat]
    rois = parse_rois(a.roi, img.shape) if a.roi else []
    fig, ax = plt.subplots(figsize=(8, 6), dpi=a.dpi)
    _imshow(ax, img, a, f"{Path(a.file).name}\n{a.stat} přes čas  {t[0]:.2f}–{t[-1]:.2f} s "
                        f"({len(t)} snímků)")
    draw_rois(ax, rois)
    if a.hotspot:
        _mark_hotspot(ax, img)
    fig.tight_layout()
    fig.savefig(a.output)
    print(f"Uloženo: {Path(a.output).resolve()}")


def cmd_roi(a):
    frames, t, _ = load(a.file)
    frames, t, idx = select_range(frames, t, a.start, a.end, a.step)
    rois = parse_rois(a.roi, frames.shape[1:])
    summary = []
    series = {}
    for name, mask, _ in rois:
        s = roi_series(frames, mask)
        series[name] = s
        m = s["mean"]
        slope = float(np.polyfit(t, m, 1)[0]) if len(t) > 1 else float("nan")
        summary.append({
            "roi": name, "pixels": int(mask.sum()),
            "mean_C": round(float(m.mean()), 3),
            "mean_first_C": round(float(m[0]), 3),
            "mean_last_C": round(float(m[-1]), 3),
            "mean_min_C": round(float(m.min()), 3), "t_mean_min_s": round(float(t[m.argmin()]), 3),
            "mean_max_C": round(float(m.max()), 3), "t_mean_max_s": round(float(t[m.argmax()]), 3),
            "abs_max_C": round(float(s["max"].max()), 3),
            "abs_min_C": round(float(s["min"].min()), 3),
            "spatial_std_avg_C": round(float(s["std"].mean()), 4),
            "trend_C_per_s": round(slope, 5),
        })
    print(json.dumps({"file": str(Path(a.file).resolve()), "n_frames": len(t),
                      "t_range_s": [round(float(t[0]), 3), round(float(t[-1]), 3)],
                      "rois": summary}, ensure_ascii=False, indent=2))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f, delimiter=a.delimiter)
            header = ["frame", "time_s"]
            for name in series:
                header += [f"{name}_{k}" for k in ("mean", "max", "min", "std")]
            wr.writerow(header)
            for j in range(len(t)):
                row = [int(idx[j]), f"{t[j]:.4f}"]
                for s in series.values():
                    row += [f"{s[k][j]:.4f}" for k in ("mean", "max", "min", "std")]
                wr.writerow(row)
        print(f"CSV: {Path(a.csv).resolve()}")


def cmd_plot(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frames, t, _ = load(a.file)
    frames, t, _ = select_range(frames, t, a.start, a.end, a.step)
    rois = parse_rois(a.roi, frames.shape[1:])
    stats = a.stat.split(",")

    if a.with_frame:
        fig, (ax_img, ax) = plt.subplots(1, 2, figsize=(14, 5), dpi=a.dpi,
                                         gridspec_kw={"width_ratios": [1, 1.4]})
        _imshow(ax_img, frames[0], a, f"snímek t = {t[0]:.2f} s")
        draw_rois(ax_img, rois)
    else:
        fig, ax = plt.subplots(figsize=(10, 5), dpi=a.dpi)

    for name, mask, _ in rois:
        s = roi_series(frames, mask)
        for st in stats:
            y = s[st]
            if a.smooth and a.smooth > 1:
                from scipy.ndimage import uniform_filter1d
                y = uniform_filter1d(y, a.smooth, mode="nearest")
            label = name if len(stats) == 1 else f"{name} ({st})"
            ax.plot(t, y, lw=1.4, label=label)
    for ev in a.mark or []:
        ax.axvline(ev, color="grey", ls="--", lw=1)
    ax.set_xlabel("čas [s]")
    ax.set_ylabel(f"teplota [°C] ({'/'.join(stats)})")
    ax.set_title(a.title or Path(a.file).name, fontsize=10)
    ax.grid(alpha=.3)
    if len(rois) * len(stats) > 1 or rois[0][0] != "full":
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(a.output)
    print(f"Uloženo: {Path(a.output).resolve()}")


def cmd_profile(a):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import map_coordinates

    frames, t, _ = load(a.file)
    i = frame_index(t, a.index, a.time)
    img = frames[i]
    x1, y1, x2, y2 = (float(v) for v in a.line.split(","))
    n = int(np.hypot(x2 - x1, y2 - y1)) + 1
    xs, ys = np.linspace(x1, x2, n), np.linspace(y1, y2, n)
    prof = map_coordinates(img, [ys, xs], order=1)
    dist = np.hypot(xs - x1, ys - y1)

    fig, (ax_img, ax) = plt.subplots(1, 2, figsize=(14, 5), dpi=a.dpi,
                                     gridspec_kw={"width_ratios": [1, 1.4]})
    _imshow(ax_img, img, a, f"snímek {i}  t = {t[i]:.3f} s")
    ax_img.plot([x1, x2], [y1, y2], color="#00e5ff", lw=1.5)
    ax.plot(dist, prof, lw=1.4)
    ax.set_xlabel("vzdálenost podél úsečky [px]")
    ax.set_ylabel("teplota [°C]")
    ax.set_title(f"Profil ({x1:.0f},{y1:.0f}) → ({x2:.0f},{y2:.0f})", fontsize=10)
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(a.output)
    print(f"Uloženo: {Path(a.output).resolve()}  min {prof.min():.2f} / max {prof.max():.2f} °C "
          f"(max v {dist[prof.argmax()]:.0f} px)")


def cmd_export(a):
    frames, t, meta = load(a.file)
    frames, t, _ = select_range(frames, t, a.start, a.end, a.step)
    np.savez_compressed(a.output, frames=frames, time_axes=t)
    print(f"Uloženo: {Path(a.output).resolve()}  frames {frames.shape} (T,H,W) °C, time_axes {t.shape}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, out=True, rng=False, img=False):
        sp.add_argument("file", help=".lrc soubor (nebo .npz z exportu)")
        if out:
            sp.add_argument("-o", "--output", required=True)
        if rng:
            sp.add_argument("--start", type=float, help="začátek [s]")
            sp.add_argument("--end", type=float, help="konec [s]")
        if img:
            sp.add_argument("--cmap", default="inferno")
            sp.add_argument("--vmin", type=float)
            sp.add_argument("--vmax", type=float)
            sp.add_argument("--dpi", type=int, default=110)

    sp = sub.add_parser("info"); common(sp, out=False); sp.set_defaults(fn=cmd_info)

    sp = sub.add_parser("frame"); common(sp, img=True)
    sp.add_argument("--index", type=int, help="index snímku (záporný = od konce)")
    sp.add_argument("--time", type=float, help="čas [s] – vezme nejbližší snímek")
    sp.add_argument("--roi", action="append")
    sp.add_argument("--hotspot", action="store_true", help="vyznačit nejteplejší pixel")
    sp.set_defaults(fn=cmd_frame)

    sp = sub.add_parser("mean"); common(sp, rng=True, img=True)
    sp.add_argument("--stat", default="mean", choices=["mean", "max", "min", "std"])
    sp.add_argument("--roi", action="append")
    sp.add_argument("--hotspot", action="store_true")
    sp.set_defaults(fn=cmd_mean)

    sp = sub.add_parser("roi"); common(sp, out=False, rng=True)
    sp.add_argument("--roi", action="append")
    sp.add_argument("--step", type=int, default=1)
    sp.add_argument("--csv", help="uložit časovou řadu do CSV")
    sp.add_argument("--delimiter", default=";")
    sp.set_defaults(fn=cmd_roi)

    sp = sub.add_parser("plot"); common(sp, rng=True, img=True)
    sp.add_argument("--roi", action="append")
    sp.add_argument("--stat", default="mean", help="mean,max,min,std (čárkou oddělené)")
    sp.add_argument("--step", type=int, default=1)
    sp.add_argument("--smooth", type=int, default=0, help="klouzavý průměr přes N snímků")
    sp.add_argument("--mark", type=float, action="append", help="svislá čára v čase [s]")
    sp.add_argument("--title")
    sp.add_argument("--with-frame", action="store_true", help="vedle grafu ukázat snímek s ROI")
    sp.set_defaults(fn=cmd_plot)

    sp = sub.add_parser("profile"); common(sp, img=True)
    sp.add_argument("--line", required=True, help="x1,y1,x2,y2")
    sp.add_argument("--index", type=int)
    sp.add_argument("--time", type=float)
    sp.set_defaults(fn=cmd_profile)

    sp = sub.add_parser("export"); common(sp, rng=True)
    sp.add_argument("--step", type=int, default=1)
    sp.set_defaults(fn=cmd_export)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"Chyba: {e}")


if __name__ == "__main__":
    main()
