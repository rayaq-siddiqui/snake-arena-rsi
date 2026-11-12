"""A self-contained HTML dashboard for an evolve run.

It reads only what the run already stores (lineage records, archive, timing, and
``report.json`` when ``report`` has run), so it is cheap enough to rewrite after every
generation and needs no service, account or JavaScript library. While a run is going the
page reloads itself.
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.agents.registry import STYLES
from arena.evolution.entrants import param_specs
from arena.evolution.report import LineageView, clean_note, load_run
from arena.evolution.report import verdict as report_verdict
from arena.rsi.store import read_json, write_atomic
from arena.rsi.types import Candidate, ParamSpec

W, H = 320, 170
PAD_L, PAD_R, PAD_T, PAD_B = 40, 10, 12, 26


@dataclass(frozen=True)
class Attempt:
    generation: int
    accepted: bool
    stage: str
    effect: float | None
    ci: tuple[float, float] | None
    rel_gain: float | None
    deaths: tuple[float, float] | None
    rationale: str
    change: str


def attempts(view: LineageView) -> list[Attempt]:
    out = []
    for rec in view.records:
        d = rec["decision"]
        stats = d.get("stats", {})
        hold, dev = stats.get("holdout"), stats.get("dev")
        if hold is not None:
            effect, ci, rel = hold["diff"], tuple(hold["ci"]), hold.get("rel_gain")
        else:
            effect, ci, rel = (dev["diff"] if dev else None), None, None
        guards = stats.get("guards", {}).get("deaths_per_1k_alive")
        chosen = next((f for f in rec["feedback"] if f["candidate"]["id"] == rec["chosen"]), None)
        if guards is None and chosen and chosen.get("dev"):
            guards = chosen["dev"]["guards"].get("deaths_per_1k_alive")
        note = clean_note(chosen["candidate"]["note"]) if chosen else "-"
        out.append(
            Attempt(
                rec["generation"],
                bool(d["accept"]),
                d["stage"],
                effect,
                (float(ci[0]), float(ci[1])) if ci else None,
                rel,
                (float(guards[0]), float(guards[1])) if guards else None,
                d["rationale"],
                note,
            )
        )
    return out


def champion_units(view: LineageView, space: Sequence[ParamSpec]) -> list[list[float]]:
    """Each parameter of the champion after every generation, in [0, 1] of its bounds."""
    champ: Candidate = view.hall[0][1]
    hall = dict(view.hall)
    rows = [[p.to_unit(champ.params[p.name]) for p in space]]
    for rec in view.records:
        champ = hall.get(rec["generation"], champ)
        rows.append([p.to_unit(champ.params[p.name]) for p in space])
    return rows


def _hit(x: float) -> str:
    """A transparent column wider than the mark, so hovering near a point finds it."""
    return (
        f'<rect class="hit" x="{x - 9:.1f}" y="{PAD_T}" width="18" height="{H - PAD_T - PAD_B}"/>'
    )


def _esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def _fmt(x: float | None, digits: int = 3) -> str:
    return "-" if x is None else f"{x:+.{digits}f}"


class Plot:
    """One small chart: linear x and y scales over a fixed viewBox."""

    def __init__(self, x0: float, x1: float, y0: float, y1: float) -> None:
        if x1 <= x0:
            x1 = x0 + 1
        if y1 <= y0:
            y0, y1 = y0 - 1, y1 + 1
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.parts: list[str] = []

    def x(self, v: float) -> float:
        return PAD_L + (v - self.x0) / (self.x1 - self.x0) * (W - PAD_L - PAD_R)

    def y(self, v: float) -> float:
        return H - PAD_B - (v - self.y0) / (self.y1 - self.y0) * (H - PAD_T - PAD_B)

    def axes(self, xticks: Sequence[int], yticks: Sequence[float], ylabel: str) -> None:
        for t in yticks:
            yy = self.y(t)
            self.parts.append(
                f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{yy:.1f}" y2="{yy:.1f}"/>'
                f'<text class="tick" x="{PAD_L - 4}" y="{yy + 3:.1f}" text-anchor="end">'
                f"{t:g}</text>"
            )
        for t in xticks:
            self.parts.append(
                f'<text class="tick" x="{self.x(t):.1f}" y="{H - PAD_B + 13}" '
                f'text-anchor="middle">{t}</text>'
            )
        self.parts.append(f'<text class="tick" x="{PAD_L}" y="{PAD_T - 2}">{_esc(ylabel)}</text>')

    def svg(self, title: str) -> str:
        return (
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(title)}">'
            + "".join(self.parts)
            + "</svg>"
        )


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        return [lo]
    step = 10 ** math.floor(math.log10((hi - lo) / n))
    for m in (1, 2, 5, 10):
        if (hi - lo) / (step * m) <= n:
            step *= m
            break
    start = math.ceil(lo / step) * step
    out, t = [], start
    while t <= hi + 1e-9:
        out.append(round(t, 10))
        t += step
    return out


def gen_ticks(last: int) -> list[int]:
    step = max(1, math.ceil(last / 6))
    return list(range(0, last + 1, step))


def effect_chart(name: str, rows: list[Attempt], last: int) -> str:
    colour = STYLES[name][1]
    vals = [0.0]
    for a in rows:
        if a.ci:
            vals += list(a.ci)
        elif a.effect is not None:
            vals.append(a.effect)
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 0.1
    p = Plot(0.5, last + 0.5, lo - pad, hi + pad)
    p.axes([t for t in gen_ticks(last) if t > 0], nice_ticks(lo - pad, hi + pad), "kills/1k")
    p.parts.append(
        f'<line class="zero" x1="{PAD_L}" x2="{W - PAD_R}" y1="{p.y(0):.1f}" y2="{p.y(0):.1f}"/>'
    )
    for a in rows:
        if a.effect is None:
            continue
        cx, cy = p.x(a.generation), p.y(a.effect)
        tip = (
            f"generation {a.generation}: {'ACCEPTED' if a.accepted else 'rejected'} at "
            f"{a.stage}\nchange: {a.change}\neffect {_fmt(a.effect)}"
            + (f", 95% CI [{a.ci[0]:+.3f}, {a.ci[1]:+.3f}]" if a.ci else "")
            + f"\n{a.rationale}"
        )
        g = [f"<g><title>{_esc(tip)}</title>"]
        if a.ci:
            g.append(
                f'<line class="ci" stroke="{colour}" x1="{cx:.1f}" x2="{cx:.1f}" '
                f'y1="{p.y(a.ci[0]):.1f}" y2="{p.y(a.ci[1]):.1f}"/>'
            )
        if a.accepted:
            g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.5" fill="{colour}" class="ring"/>')
        elif a.stage == "holdout":
            g.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="var(--surface)" '
                f'stroke="{colour}" stroke-width="2"/>'
            )
        else:
            g.append(
                f'<path d="M{cx - 3.5:.1f},{cy - 3.5:.1f}l7,7m0,-7l-7,7" stroke="{colour}" '
                f'stroke-width="2"/>'
            )
        g.append(_hit(cx))
        g.append("</g>")
        p.parts.append("".join(g))
    return p.svg(f"{STYLES[name][0]}: effect of each proposal")


def accepts_chart(views: Mapping[str, LineageView], last: int) -> str:
    top = max([1] + [sum(r["decision"]["accept"] for r in v.records) for v in views.values()])
    p = Plot(0, max(last, 1), 0, top)
    p.axes(gen_ticks(max(last, 1)), nice_ticks(0, top), "champion version - 1")
    for i, (name, v) in enumerate(views.items()):
        colour = STYLES[name][1]
        count, pts = 0, [(0.0, 0.0)]
        for rec in v.records:
            g = rec["generation"]
            pts.append((g, count))
            count += int(rec["decision"]["accept"])
            pts.append((g, count))
        off = (i - 2) * 0.8
        d = " ".join(f"{p.x(x):.1f},{p.y(y) + off:.1f}" for x, y in pts)
        p.parts.append(
            f'<polyline points="{d}" fill="none" stroke="{colour}" stroke-width="2">'
            f"<title>{_esc(STYLES[name][0])}: {count} accepted</title></polyline>"
        )
    return p.svg("Accepted changes over generations")


def guard_chart(name: str, rows: list[Attempt], last: int) -> str:
    colour = STYLES[name][1]
    pts = [a for a in rows if a.deaths]
    vals = [x for a in pts for x in a.deaths or ()] or [0.0, 1.0]
    hi = max(vals) * 1.1 or 1.0
    p = Plot(0.5, last + 0.5, 0, hi)
    p.axes([t for t in gen_ticks(last) if t > 0], nice_ticks(0, hi), "deaths/1k alive")
    for a in pts:
        assert a.deaths
        cand, champ = a.deaths
        x = p.x(a.generation)
        tip = (
            f"generation {a.generation}: candidate {cand:.3f}, champion {champ:.3f} deaths "
            f"per 1,000 alive ticks"
        )
        p.parts.append(
            f"<g><title>{_esc(tip)}</title>"
            f'<line class="link" x1="{x:.1f}" x2="{x:.1f}" '
            f'y1="{p.y(champ):.1f}" y2="{p.y(cand):.1f}"/>'
            f'<rect x="{x - 4:.1f}" y="{p.y(champ) - 4:.1f}" width="8" height="8" '
            f'fill="var(--muted)" class="ring"/>'
            f'<circle cx="{x:.1f}" cy="{p.y(cand):.1f}" r="4.5" fill="{colour}" class="ring"/>'
            + _hit(x)
            + "</g>"
        )
    return p.svg(f"{STYLES[name][0]}: deaths, candidate vs champion")


def param_heatmap(name: str, view: LineageView) -> str:
    space = param_specs(name, view.hall[0][1].params)
    rows = champion_units(view, space)
    cols = len(rows)
    cell_w = max(6.0, min(28.0, 220 / cols))
    label_w, cell_h = 140, 13
    width = label_w + cell_w * cols + 4
    height = cell_h * len(space) + 18
    parts = []
    for j, spec in enumerate(space):
        y = j * cell_h
        parts.append(
            f'<text class="tick" x="{label_w - 6}" y="{y + 10}" text-anchor="end">'
            f"{_esc(spec.name)}</text>"
        )
        for g, row in enumerate(rows):
            u = row[j]
            changed = g > 0 and abs(u - rows[g - 1][j]) > 1e-12
            value = spec.from_unit(u)
            parts.append(
                f'<rect x="{label_w + g * cell_w:.1f}" y="{y}" width="{cell_w - 1:.1f}" '
                f'height="{cell_h - 1}" fill="var(--seq)" fill-opacity="{0.08 + 0.92 * u:.3f}"'
                + (' stroke="var(--ink)" stroke-width="1.5"' if changed else "")
                + f"><title>{_esc(spec.name)} after generation {g}: {value:.4g} "
                f"(bounds {spec.low:g} to {spec.high:g})</title></rect>"
            )
    for g in gen_ticks(cols - 1):
        parts.append(
            f'<text class="tick" x="{label_w + g * cell_w + cell_w / 2:.1f}" '
            f'y="{height - 4}" text-anchor="middle">{g}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width:.0f} {height}" role="img" '
        f'aria-label="{_esc(STYLES[name][0])} champion parameters">' + "".join(parts) + "</svg>"
    )


def time_chart(timing: list[dict[str, Any]]) -> str:
    if not timing:
        return '<p class="muted">No generation has finished yet.</p>'
    last = max(t["generation"] for t in timing)
    top = max(t["seconds"] for t in timing) * 1.1
    p = Plot(0.5, last + 0.5, 0, top)
    p.axes([t for t in gen_ticks(last) if t > 0], nice_ticks(0, top), "seconds")
    bw = max(3.0, (p.x(1.5) - p.x(0.5)) - 4)
    for t in timing:
        x = p.x(t["generation"]) - bw / 2
        y = p.y(t["seconds"])
        p.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{p.y(0) - y:.1f}" '
            f'rx="2" fill="var(--seq)"><title>generation {t["generation"]}: '
            f"{t['seconds']:.0f} s, {t['episodes']} episodes on {t['workers']} workers"
            "</title></rect>"
        )
    return p.svg("Wall time per generation")


def matrix_table(matrix: Mapping[str, Any]) -> str:
    kills = matrix["kills"]
    top = max([1] + [x for row in kills for x in row])
    head = "".join(f"<th>{_esc(s)}</th>" for s in matrix["snakes"])
    body = []
    for name, row in zip(matrix["snakes"], kills, strict=True):
        cells = "".join(
            f'<td style="background:color-mix(in srgb, var(--seq) {100 * k / top:.0f}%, '
            f'transparent)">{k}</td>'
            for k in row
        )
        body.append(f"<tr><th>{_esc(name)}</th>{cells}</tr>")
    return (
        f'<table class="matrix"><tr><th>killer ↓ / victim →</th>{head}</tr>'
        + "".join(body)
        + "</table>"
        + f'<p class="muted">{matrix["episodes"]} games of {matrix["ticks"]:,} ticks on '
        "the final seeds.</p>"
    )


CSS = """
:root{--surface:#fcfcfb;--panel:#ffffff;--ink:#1d1f24;--ink2:#4a4f59;--muted:#8a909b;
--line:#e3e5e8;--seq:#3a6fd8;--accent:#3a6fd8}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--surface:#16181d;
--panel:#1d2026;--ink:#e8eaee;--ink2:#b5bac4;--muted:#7d8491;--line:#30343c;--seq:#7aa2f7}}
:root[data-theme="dark"]{--surface:#16181d;--panel:#1d2026;--ink:#e8eaee;--ink2:#b5bac4;
--muted:#7d8491;--line:#30343c;--seq:#7aa2f7}
*{box-sizing:border-box}body{margin:0;background:var(--surface);color:var(--ink);
font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 4px}
p.lede{color:var(--ink2);margin:0 0 4px;max-width:75ch}.muted{color:var(--muted)}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid var(--line);
font-size:12px;color:var(--ink2);margin-right:6px}
.badge.warn{border-color:#d08c2a;color:#b06f10}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px}
.tile .name{display:flex;align-items:center;gap:6px;font-weight:600}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.tile .big{font-size:24px;font-weight:600;margin-top:4px}
.tile .sub{color:var(--ink2);font-size:12px}
.grid5{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}
figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:10px}
figcaption{font-weight:600;font-size:13px;display:flex;align-items:center;gap:6px}
svg{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--line);stroke-width:1}
.zero{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
.tick{fill:var(--muted);font-size:10px}.ci{stroke-width:2;stroke-linecap:round;opacity:.55}
.ring{stroke:var(--panel);stroke-width:2}.link{stroke:var(--muted);stroke-width:1.5}
.hit{fill:transparent}g:hover .hit{fill:var(--ink);fill-opacity:.05}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--ink2);font-size:12px;margin:6px 0 8px}
.legend svg{width:14px;height:14px;display:inline-block;vertical-align:-2px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:var(--panel)}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.matrix td{text-align:center;font-variant-numeric:tabular-nums;width:14%}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
.acc{font-weight:600}select{font:inherit;padding:2px 6px;background:var(--panel);color:var(--ink);
border:1px solid var(--line);border-radius:6px}
"""

SCRIPT = """
const sel=document.getElementById('lineage');
if(sel){sel.addEventListener('change',()=>{for(const r of document.querySelectorAll('tr[data-l]'))
r.hidden=sel.value!=='all'&&r.dataset.l!==sel.value;});}
"""


def _legend() -> str:
    return (
        '<div class="legend">'
        '<span><svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="5" fill="var(--ink2)"/></svg> '
        "accepted</span>"
        '<span><svg viewBox="0 0 14 14"><circle cx="7" cy="7" r="4.5" fill="none" '
        'stroke="var(--ink2)" stroke-width="2"/></svg> rejected at holdout (bar = 95% CI)</span>'
        '<span><svg viewBox="0 0 14 14"><path d="M3.5,3.5l7,7m0,-7l-7,7" stroke="var(--ink2)" '
        'stroke-width="2"/></svg> rejected at dev screen</span></div>'
    )


def render(run_dir: Path) -> str:
    profile, views = load_run(run_dir)
    budget = max(
        read_json(run_dir / "lineages" / n / "config.json")["budget"]["generations"] or 0
        for n in views
    )
    final_path = run_dir / "final.json"
    final = read_json(final_path) if final_path.exists() else None
    report_path = run_dir / "report.json"
    report = read_json(report_path) if report_path.exists() else None
    timing_path = run_dir / "timing.jsonl"
    timing = (
        [json.loads(x) for x in timing_path.read_text().splitlines() if x.strip()]
        if timing_path.exists()
        else []
    )
    last = max([len(v.records) for v in views.values()] + [1])
    done = final is not None
    rows = {n: attempts(v) for n, v in views.items()}

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "" if done else "<meta http-equiv='refresh' content='60'>",
        f"<title>Evolution dashboard</title><style>{CSS}</style></head><body><main>",
        f"<h1>Snake evolution · {_esc(run_dir.name)}</h1>",
        "<p class='lede'>Each snake runs its own improvement loop: propose a parameter change, "
        "test it in paired games against the current champion, and keep it only if it wins "
        "on held-out seeds by a clear margin without dying more.</p>",
        f"<p><span class='badge'>profile: {_esc(profile.name)}</span>",
        f"<span class='badge'>{profile.settings.width}&times;{profile.settings.height} board, "
        f"{profile.settings.ticks:,}-tick episodes</span>",
        f"<span class='badge'>{last if any(v.records for v in views.values()) else 0} of "
        f"{budget} generations</span>",
        f"<span class='badge'>{'finished' if done else 'running · reloads every minute'}</span>",
    ]
    if profile.name != "default":
        out.append("<span class='badge warn'>reduced setting, not the specified experiment</span>")
    out.append("</p>")

    out.append("<div class='tiles'>")
    for name, v in views.items():
        accepted = sum(1 for a in rows[name] if a.accepted)
        verdict, stop = "", ""
        if final and name in final.get("lineages", {}):
            lin = final["lineages"][name]
            stop = lin.get("stop_reason") or ""
            f = lin.get("final")
            verdict = f"vs generation 0: {report_verdict(f)}"
            if f:
                verdict += f", {_fmt(f['diff'])} [{f['ci'][0]:+.3f}, {f['ci'][1]:+.3f}]"
        out.append(
            f"<div class='tile'><div class='name'><span class='dot' "
            f"style='background:{STYLES[name][1]}'></span>{_esc(STYLES[name][0])}</div>"
            f"<div class='big'>v{len(v.hall)}</div>"
            f"<div class='sub'>{accepted} accepted of {len(v.records)} proposals</div>"
            + (f"<div class='sub'>{_esc(verdict)}</div>" if verdict else "")
            + (f"<div class='sub muted'>{_esc(stop)}</div>" if stop else "")
            + "</div>"
        )
    out.append("</div>")

    out += [
        "<h2>Every proposal and its measured effect</h2>",
        "<p class='lede'>Paired difference in kills per 1,000 ticks, candidate minus champion "
        "(above the dashed line = the change helped). Hover a point for the change and the "
        "reason it was kept or dropped.</p>",
        _legend(),
        "<div class='grid5'>",
    ]
    for name in views:
        out.append(
            f"<figure><figcaption><span class='dot' style='background:{STYLES[name][1]}'></span>"
            f"{_esc(STYLES[name][0])}</figcaption>{effect_chart(name, rows[name], last)}</figure>"
        )
    out.append(
        "<figure><figcaption>Accepted changes, all lineages</figcaption>"
        f"{accepts_chart(views, last)}</figure></div>"
    )

    if report:
        out += [
            "<h2>Strength of each champion version</h2>",
            "<p class='lede'>Kills per 1,000 ticks of each version against the hand-set reference "
            "snakes on the untouched final seeds, with 95% bootstrap intervals.</p>",
            "<figure>",
            (run_dir / "progress.svg").read_text() if (run_dir / "progress.svg").exists() else "",
            "</figure>",
        ]

    out += [
        "<h2>Safety guard: does a change make the snake die more?</h2>",
        "<p class='lede'>Deaths per 1,000 alive ticks for the candidate (dot) and the champion "
        "(grey square) in the same paired games. A change that buys kills with lives is "
        "rejected.</p>",
        "<div class='grid5'>",
    ]
    for name in views:
        out.append(
            f"<figure><figcaption><span class='dot' style='background:{STYLES[name][1]}'></span>"
            f"{_esc(STYLES[name][0])}</figcaption>{guard_chart(name, rows[name], last)}</figure>"
        )
    out.append("</div>")

    out += [
        "<h2>What the champions are made of</h2>",
        "<p class='lede'>Each champion parameter after every generation, shaded by where it sits "
        "between its bounds (darker = nearer the upper bound). Outlined cells changed that "
        "generation.</p>",
        "<div class='grid5'>",
    ]
    for name, v in views.items():
        out.append(
            f"<figure><figcaption><span class='dot' style='background:{STYLES[name][1]}'></span>"
            f"{_esc(STYLES[name][0])}</figcaption>{param_heatmap(name, v)}</figure>"
        )
    out.append("</div>")

    if report and report.get("matrix"):
        out += ["<h2>Who kills whom (final champions)</h2>", matrix_table(report["matrix"])]

    out += [
        "<h2>Compute</h2>",
        f"<figure style='max-width:420px'><figcaption>Wall time per generation</figcaption>"
        f"{time_chart(timing)}</figure>",
        "<h2>Decision log</h2>",
        "<p><label>Lineage <select id='lineage'><option value='all'>all</option>"
        + "".join(f"<option value='{n}'>{_esc(STYLES[n][0])}</option>" for n in views)
        + "</select></label></p>",
        "<div class='scroll'><table><tr><th>gen</th><th>snake</th><th>change</th>"
        "<th>effect</th><th>95% CI</th><th>deaths cand / champ</th><th>decision</th></tr>",
    ]
    for g in range(1, last + 1):
        for name in views:
            for a in rows[name]:
                if a.generation != g:
                    continue
                ci = f"[{a.ci[0]:+.3f}, {a.ci[1]:+.3f}]" if a.ci else "-"
                deaths = f"{a.deaths[0]:.3f} / {a.deaths[1]:.3f}" if a.deaths else "-"
                verdict = "<span class='acc'>ACCEPT</span>" if a.accepted else "reject"
                out.append(
                    f"<tr data-l='{name}'><td class='num'>{g}</td>"
                    f"<td><span class='dot' style='background:{STYLES[name][1]}'></span> "
                    f"{_esc(STYLES[name][0])}</td><td>{_esc(a.change)}</td>"
                    f"<td class='num'>{_fmt(a.effect)}</td><td class='num'>{ci}</td>"
                    f"<td class='num'>{deaths}</td><td>{verdict}: {_esc(a.rationale)}</td></tr>"
                )
    out.append("</table></div>")
    out.append(f"<script>{SCRIPT}</script></main></body></html>")
    return "\n".join(x for x in out if x)


def write(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    path = run_dir / "dashboard.html"
    write_atomic(path, render(run_dir))
    return path
