"""Merge journeys, delays, prices and map outline into site/index.html."""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LON0, LON1, LAT0, LAT1 = 5.4, 15.6, 47.0, 55.3
K = 100  # px per degree latitude
COSL = math.cos(math.radians(51.2))


def proj(lon, lat):
    return round((lon - LON0) * COSL * K, 1), round((LAT1 - lat) * K, 1)


def topo_paths(path, ids_main='276'):
    t = json.load(open(path))
    sx, sy = t['transform']['scale']
    tx, ty = t['transform']['translate']
    arcs = []
    for arc in t['arcs']:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts

    main, others = '', []
    for g in t['objects']['countries']['geometries']:
        polys = g['arcs'] if g['type'] == 'MultiPolygon' else [g['arcs']] if g['type'] == 'Polygon' else []
        d = []
        for poly in polys:
            for r in poly:
                pts = ring(r)
                if not any(LON0 - 1 < x < LON1 + 1 and LAT0 - 1 < y < LAT1 + 1 for x, y in pts):
                    continue
                pp = []
                for x, y in pts:  # whole pixels, drop repeated points
                    q = tuple(round(v) for v in proj(x, y))
                    if not pp or q != pp[-1]:
                        pp.append(q)
                if len(pp) < 4:
                    continue
                d.append('M' + 'L'.join(f'{a},{b}' for a, b in pp) + 'Z')
        if not d:
            continue
        if g.get('id') == ids_main:
            main = ''.join(d)
        else:
            others.append(''.join(d))
    return main, others


def main():
    cities = list(csv.DictReader(open(ROOT / 'data/cities.csv', encoding='utf-8')))
    jd = json.load(open(ROOT / 'data/journeys.json', encoding='utf-8'))
    dd = json.load(open(ROOT / 'data/delays.json', encoding='utf-8'))
    out_cities = []
    for c in cities:
        x, y = proj(float(c['lon']), float(c['lat']))
        item = {'city': c['city'], 'pop': int(c['population']), 'station': c['station'], 'x': x, 'y': y}
        for d in ('out', 'in'):
            s = jd['summary'][c['city']][d]
            dl = dd['cities'][c['city']][d]
            dj = {(j['date'], j['dep'], j['arr']): j for j in dl['journeys']}
            js = []
            for j in jd['journeys'][c['city']][d]:
                m = dj.get((j['date'], j['dep'], j['arr']), {})
                js.append({'date': j['date'], 'dep': j['dep'], 'arr': j['arr'], 'dur': j['duration_min'],
                           'ch': j['changes'],
                           'via': [l['to'] for l in j['legs'][:-1]],
                           'lines': [l['line'] for l in j['legs']],
                           'ontime': round(m['p_ontime'], 3) if m.get('matched') else None})
            # same connection on several sample days -> one row with all dates
            merged = {}
            for j in js:
                k = (j['dep'], j['arr'], tuple(j['lines']), tuple(j['via']))
                if k in merged:
                    merged[k]['dates'].append(j['date'])
                    if j['ontime'] is not None:
                        merged[k]['_o'].append(j['ontime'])
                else:
                    merged[k] = {**{x: j[x] for x in ('dep', 'arr', 'dur', 'ch', 'via', 'lines')},
                                 'dates': [j['date']], '_o': [j['ontime']] if j['ontime'] is not None else []}
            rows = []
            for m in sorted(merged.values(), key=lambda r: r['dep']):
                o = m.pop('_o')
                m['ontime'] = round(sum(o) / len(o), 3) if o else None
                rows.append(m)
            # route variants (same trains/changes = same path); most frequent first
            variants = {}
            for j in jd['journeys'][c['city']][d]:
                k = (tuple(l['line'] for l in j['legs']), tuple(l['to'] for l in j['legs'][:-1]))
                if k not in variants:
                    pts = []
                    for l in j['legs']:
                        for lat, lon in l['path']:
                            q = proj(lon, lat)
                            if not pts or q != pts[-1]:
                                pts.append(q)
                    variants[k] = {'d': 'M' + 'L'.join(f'{a},{b}' for a, b in pts), 'n': 0,
                                   'label': ' · '.join(k[0]) + (' über ' + ', '.join(k[1]) if k[1] else '')}
                variants[k]['n'] += 1
            routes = sorted(variants.values(), key=lambda v: -v['n'])
            item[d] = {**s, 'delay': {k: dl[k] for k in ('p_late6', 'p_late15', 'p_miss', 'p_ontime', 'matched', 'total')},
                       'journeys': rows, 'routes': routes}
        out_cities.append(item)

    de, nb = topo_paths(ROOT / 'data/raw/geo/countries-50m.json')
    w, h = proj(LON1, LAT0)
    bx, by = proj(10.899493, 49.90076)
    data = {
        'days': jd['days'], 'window': jd['window'],
        'origin': {'name': 'Bamberg', 'x': bx, 'y': by},
        'cities': out_cities,
        'geo': {'w': w, 'h': h, 'de': de, 'nb': nb},
    }
    tpl = (ROOT / 'docs/template.html').read_text(encoding='utf-8')
    html = tpl.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    # GitHub Pages needs a full document (otherwise quirks mode); the claude.ai artifact
    # adds its own document frame, so it gets the bare page.
    (ROOT / 'docs/index.html').write_text('<!doctype html>\n<html lang="de">\n' + html + '\n</html>\n', encoding='utf-8')
    art = ROOT / '_unpublished/artifact.html'
    art.parent.mkdir(exist_ok=True)
    art.write_text(html, encoding='utf-8')
    print('docs/index.html', len(html) // 1024, 'KB')


if __name__ == '__main__':
    main()
