"""Travel times Bamberg <-> cities from open GTFS data (gtfs.de, CC BY 4.0).

Connection Scan Algorithm (earliest arrival) over the merged long-distance (fv)
and regional (rv) feeds. For every departure from the origin between 14:00 and
18:00 on the sample days, the earliest-arrival journey is computed; dominated
journeys (depart earlier, arrive same or later) are dropped.

Output: data/journeys.json
"""
import bisect
import csv
import datetime as dt
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS = [ROOT / 'data/raw/gtfs_fv', ROOT / 'data/raw/gtfs_rv']
ORIGIN = 'Bamberg'
DAYS = [dt.date(2026, 12, 1), dt.date(2026, 12, 2), dt.date(2026, 12, 3)]  # Tue-Thu
WIN_FROM, WIN_TO = 14 * 3600, 18 * 3600
MIN_TRANSFER = 5 * 60  # seconds, same-station change
MAX_SCAN = 30 * 3600   # ignore connections after 06:00 next day
# (name prefix in GTFS, display name, routing key = city main station from cities.csv)
CITY_GROUPS = [
    ('Bamberg=', 'Bamberg', 'Bamberg'),  # '=' = exact name
    ('Berlin Hbf', 'Berlin Hbf', 'Berlin Hbf'),
    ('Berlin Südkreuz', 'Berlin Südkreuz', 'Berlin Hbf'),
    ('Berlin Gesundbrunnen', 'Berlin Gesundbrunnen', 'Berlin Hbf'),
    ('Berlin Spandau', 'Berlin-Spandau', 'Berlin Hbf'),
    ('Berlin Ostbahnhof', 'Berlin Ostbahnhof', 'Berlin Hbf'),
    ('Hamburg Hbf', 'Hamburg Hbf', 'Hamburg Hbf'),
    ('Hamburg, Hamburg Hbf', 'Hamburg Hbf', 'Hamburg Hbf'),
    ('Hamburg Dammtor', 'Hamburg Dammtor', 'Hamburg Hbf'),
    ('Hamburg, Hamburg-Harburg', 'Hamburg-Harburg', 'Hamburg Hbf'),
    ('Hamburg-Harburg', 'Hamburg-Harburg', 'Hamburg Hbf'),
    ('Hamburg, Hamburg-Altona', 'Hamburg-Altona', 'Hamburg Hbf'),
    ('Hamburg-Altona', 'Hamburg-Altona', 'Hamburg Hbf'),
    ('München Hbf', 'München Hbf', 'München Hbf'),
    ('München-Pasing', 'München-Pasing', 'München Hbf'),
    ('München Ost', 'München Ost', 'München Hbf'),
    ('Köln Hbf', 'Köln Hbf', 'Köln Hbf'),
    ('Köln Messe/Deutz', 'Köln Messe/Deutz', 'Köln Hbf'),
    ('Frankfurt(Main)Hbf', 'Frankfurt(Main)Hbf', 'Frankfurt(Main)Hbf'),
    ('Frankfurt (Main) Hauptbahnhof', 'Frankfurt(Main)Hbf', 'Frankfurt(Main)Hbf'),
    ('Düsseldorf Hbf', 'Düsseldorf Hbf', 'Düsseldorf Hbf'),
    ('Stuttgart Hbf', 'Stuttgart Hbf', 'Stuttgart Hbf'),
    ('Leipzig Hbf', 'Leipzig Hbf', 'Leipzig Hbf'),
    ('Dortmund Hbf', 'Dortmund Hbf', 'Dortmund Hbf'),
    ('Bremen Hbf', 'Bremen Hbf', 'Bremen Hbf'),
    ('Bremen Hauptbahnhof', 'Bremen Hbf', 'Bremen Hbf'),
    ('Essen Hbf', 'Essen Hbf', 'Essen Hbf'),
    ('Dresden Hbf', 'Dresden Hbf', 'Dresden Hbf'),
    ('Dresden Hauptbahnhof', 'Dresden Hbf', 'Dresden Hbf'),
    ('Dresden-Neustadt', 'Dresden-Neustadt', 'Dresden Hbf'),
    ('Dresden Bahnhof Neustadt', 'Dresden-Neustadt', 'Dresden Hbf'),
    ('Nürnberg Hbf', 'Nürnberg Hbf', 'Nürnberg Hbf'),
    ('Hannover Hbf', 'Hannover Hbf', 'Hannover Hbf'),
    ('Hannover Hauptbahnhof', 'Hannover Hbf', 'Hannover Hbf'),
    ('Duisburg Hbf', 'Duisburg Hbf', 'Duisburg Hbf'),
]
STOPS = {}  # stop_id -> stops.txt row (filled by load)
WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


def secs(t):
    h, m, s = t.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def hhmm(s):
    return f'{s // 3600 % 24:02d}:{s // 60 % 60:02d}'


def read(feed, name):
    with open(feed / name, encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def load():
    routes, trips = {}, {}
    services = defaultdict(set)  # service_id -> active dates
    stops = {}
    for feed in FEEDS:  # stop ids are identical across both gtfs.de feeds
        for s in read(feed, 'stops.txt'):
            stops[s['stop_id']] = s
    # station key = parent station (or the stop itself); several unrelated stops share
    # generic names such as "Hauptbahnhof", so names must not be used as keys.
    key_of = {sid: (s['parent_station'] or sid) for sid, s in stops.items()}
    name_of = {}
    for sid, k in key_of.items():
        name_of.setdefault(k, stops[k]['stop_name'] if k in stops else stops[sid]['stop_name'])
    # Routing key: every long-distance station of a target city (all spellings/platform
    # groups) maps to the city's main station, so "arriving in Köln" includes Köln Messe/Deutz.
    # Display name stays the real station (needed for delay matching).
    route_key, display = {}, {}
    for sid, s in stops.items():
        n = s['stop_name']
        hit = next(((disp, main) for pre, disp, main in CITY_GROUPS
                    if (n == pre[:-1] if pre.endswith('=') else n.startswith(pre))), None)
        if hit:
            display[sid], route_key[sid] = hit
        else:
            k = key_of[sid]
            display[sid] = name_of[k]
            route_key[sid] = f'{name_of[k]}#{k}'
    stop_name = (route_key, display)
    STOPS.update(stops)
    for feed in FEEDS:
        tag = feed.name[-2:]
        for r in read(feed, 'routes.txt'):
            routes[(tag, r['route_id'])] = r['route_short_name'] or r['route_long_name']
        for c in read(feed, 'calendar.txt'):
            start = dt.datetime.strptime(c['start_date'], '%Y%m%d').date()
            end = dt.datetime.strptime(c['end_date'], '%Y%m%d').date()
            for d in DAYS:
                if start <= d <= end and c[WEEKDAYS[d.weekday()]] == '1':
                    services[(tag, c['service_id'])].add(d)
        for c in read(feed, 'calendar_dates.txt'):
            d = dt.datetime.strptime(c['date'], '%Y%m%d').date()
            if d in DAYS:
                key = (tag, c['service_id'])
                if c['exception_type'] == '1':
                    services[key].add(d)
                else:
                    services[key].discard(d)
        for t in read(feed, 'trips.txt'):
            trips[(tag, t['trip_id'])] = (routes[(tag, t['route_id'])], (tag, t['service_id']))
    return stop_name, trips, services


def connections_for(day, stop_name, trips, services):
    """List of (dep, arr, from_station, to_station, trip_key) for one service day."""
    conns = []
    route_key, display = stop_name
    for feed in FEEDS:
        tag = feed.name[-2:]
        prev = None
        for st in read(feed, 'stop_times.txt'):
            key = (tag, st['trip_id'])
            if prev and prev[0] == key:
                trip = trips[key]
                if day in services.get(trip[1], ()):  # active
                    dep, arr = secs(prev[2]), secs(st['arrival_time'])
                    if 11 * 3600 <= dep <= MAX_SCAN:
                        conns.append((dep, arr, route_key[prev[1]], route_key[st['stop_id']], key,
                                      prev[3] != '1', st['drop_off_type'] != '1',
                                      display[prev[1]], display[st['stop_id']]))
            prev = (key, st['stop_id'], st['departure_time'], st['pickup_type'])
    conns.sort(key=lambda c: (c[0], c[1]))
    return conns


MAX_RIDES = 5            # at most 4 changes
CHANGE_PENALTY = 30 * 60  # one change "feels" like 30 extra minutes


def cost(legs):
    return legs[-1]['arr'] + CHANGE_PENALTY * (len(legs) - 1)


def csa(conns, origin, t0, targets):
    """Transfer-bounded CSA: earliest arrival per number of rides (1..MAX_RIDES).
    Returns {target: legs} choosing, per target, the option with the lowest
    arrival time + CHANGE_PENALTY per change (i.e. fewer changes preferred)."""
    INF = 10 ** 9
    best = [defaultdict(lambda: INF) for _ in range(MAX_RIDES + 1)]  # best[r][station]
    best[0][origin] = t0 - MIN_TRANSFER  # so first boarding needs dep >= t0
    trip_in = {}   # trip -> (boarding idx, rides when riding this trip)
    link = {}      # (rides, station) -> (board_idx, alight_idx)
    target_cut = t0 + 12 * 3600  # never search more than 12 h ahead
    fastest = None
    start = bisect.bisect_left(conn_deps, t0)
    for i in range(start, len(conns)):
        dep, arr, a, b, trip, can_board, can_alight = conns[i][:7]
        if dep > target_cut:
            break
        if can_board:  # (re)board with the fewest rides possible
            cur = trip_in.get(trip, (None, MAX_RIDES + 1))[1]
            for r in range(0, min(cur - 1, MAX_RIDES)):
                if best[r][a] + MIN_TRANSFER <= dep:
                    trip_in[trip] = (i, r + 1)
                    break
        if trip in trip_in and can_alight:
            bi, r = trip_in[trip]
            if arr < best[r][b]:
                best[r][b] = arr
                link[(r, b)] = (bi, i)
                if fastest is None and all(any(best[k][t] < INF for k in range(1, MAX_RIDES + 1)) for t in targets):
                    fastest = max(min(best[k][t] for k in range(1, MAX_RIDES + 1)) for t in targets)
                    # fewer-change options may arrive later: keep scanning a while
                    target_cut = min(target_cut, fastest + (MAX_RIDES - 1) * CHANGE_PENALTY)
    out = {}
    for t in targets:
        options = []
        for r in range(1, MAX_RIDES + 1):
            if (r, t) not in link:
                continue
            legs, s, rr = [], t, r
            while rr > 0:
                bi, ai = link[(rr, s)]
                c0, c1 = conns[bi], conns[ai]
                legs.append({'line': trips_names[c0[4]], 'from': c0[7], 'dep': c0[0],
                             'to': c1[8], 'arr': c1[1], 'trip': f'{c0[4][0]}|{c0[4][1]}'})
                s, rr = c0[2], rr - 1
            options.append(legs[::-1])
        if options:
            out[t] = min(options, key=lambda l: (cost(l), -l[0]['dep']))
    return out


def pareto(journeys):
    """Drop a journey if another one leaves no earlier and is at least as good in
    arrival time + change penalty (so a direct train beats a slightly faster change)."""
    js = sorted({(j[0]['dep'], j[-1]['arr'], len(j)): j for j in journeys}.values(),
                key=lambda j: (j[0]['dep'], j[-1]['arr']))
    keep = []
    for j in js:
        if any(k is not j and k[0]['dep'] >= j[0]['dep'] and cost(k) <= cost(j)
               and (k[0]['dep'], cost(k)) != (j[0]['dep'], cost(j)) for k in js):
            continue
        keep.append(j)
    return keep


def clean(n):
    return n.split('#')[0]


def fmt(j, day):
    j = [{**l, 'from': clean(l['from']), 'to': clean(l['to'])} for l in j]
    return {
        'date': day.isoformat(),
        'dep': hhmm(j[0]['dep']), 'arr': hhmm(j[-1]['arr']),
        'duration_min': (j[-1]['arr'] - j[0]['dep']) // 60,
        'changes': len(j) - 1,
        'legs': [{**l, 'dep': hhmm(l['dep']), 'arr': hhmm(l['arr']), 'dep_s': l['dep'], 'arr_s': l['arr'],
                  'type': l['line'].split()[0] if l['line'] else ''} for l in j],
    }


def add_paths(result):
    """Attach the stop-by-stop coordinates [lat, lon] of every leg (GTFS.DE has no shapes.txt,
    so the route is traced through all intermediate stops of the train actually used)."""
    legs = [l for city in result.values() for d in ('out', 'in') for j in city[d] for l in j['legs']]
    wanted = {l['trip'] for l in legs}
    seq = defaultdict(list)  # trip -> [(arr_s, dep_s, stop_id)]
    for feed in FEEDS:
        tag = feed.name[-2:]
        for st in read(feed, 'stop_times.txt'):
            k = f"{tag}|{st['trip_id']}"
            if k in wanted:
                seq[k].append((int(st['stop_sequence']), secs(st['arrival_time']), secs(st['departure_time']), st['stop_id']))
    for l in legs:
        stops = sorted(seq[l['trip']])
        path = [(float(STOPS[sid]['stop_lat']), float(STOPS[sid]['stop_lon']))
                for _, a, d, sid in stops if d >= l['dep_s'] and a <= l['arr_s']]
        l['path'] = [[round(a, 4), round(b, 4)] for a, b in path]
        del l['dep_s'], l['arr_s']


def main():
    global trips_names
    cities = list(csv.DictReader(open(ROOT / 'data/cities.csv', encoding='utf-8')))
    stations = [c['station'] for c in cities]
    stop_name, trips, services = load()
    trips_names = {k: v[0] for k, v in trips.items()}
    result = {c['city']: {'out': [], 'in': []} for c in cities}
    global conn_deps
    for day in DAYS:
        conns = connections_for(day, stop_name, trips, services)
        conn_deps = [c[0] for c in conns]
        print(day, len(conns), 'connections', flush=True)
        # outbound: Bamberg -> all cities (one run serves all targets)
        deps = sorted({c[0] for c in conns if c[2] == ORIGIN and c[5] and WIN_FROM <= c[0] <= WIN_TO})
        found = defaultdict(list)
        for t0 in deps:
            for st, legs in csa(conns, ORIGIN, t0, stations).items():
                if WIN_FROM <= legs[0]['dep'] <= WIN_TO:
                    found[st].append(legs)
        # inbound: each city -> Bamberg. A run from t0 yields a journey leaving at d >= t0;
        # every start time in (t0, d] yields the same journey, so skip ahead to d + 1 min.
        back = defaultdict(list)
        for st in stations:
            t0 = WIN_FROM
            while t0 <= WIN_TO:
                r = csa(conns, st, t0, [ORIGIN]).get(ORIGIN)
                if not r:
                    break
                if r[0]['dep'] <= WIN_TO:
                    back[st].append(r)
                t0 = r[0]['dep'] + 60
        print(day, 'done', flush=True)
        for c in cities:
            result[c['city']]['out'] += [fmt(j, day) for j in pareto(found[c['station']])]
            result[c['city']]['in'] += [fmt(j, day) for j in pareto(back[c['station']])]
    add_paths(result)
    summary = {}
    for city, r in result.items():
        summary[city] = {}
        for d in ('out', 'in'):
            durs = [j['duration_min'] for j in r[d]]
            summary[city][d] = {
                'n': len(durs),
                'fastest_min': min(durs) if durs else None,
                'median_min': round(statistics.median(durs)) if durs else None,
                'median_changes': statistics.median([j['changes'] for j in r[d]]) if durs else None,
            }
        print(f"{city:20s} out {summary[city]['out']}  in {summary[city]['in']}")
    json.dump({'days': [d.isoformat() for d in DAYS], 'window': '14:00-18:00',
               'summary': summary, 'journeys': result},
              open(ROOT / 'data/journeys.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
