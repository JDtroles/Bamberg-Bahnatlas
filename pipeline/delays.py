"""Delay / transfer-miss probabilities for the journeys in data/journeys.json.

Source: piebro/deutsche-bahn-data (CC BY 4.0, from DB Timetables API),
monthly files Aug-Oct 2026, weekdays (Mon-Fri) only.

Per leg, history = all records at the leg's alighting station with the same
train type and the same planned arrival time of day (HH:MM) - i.e. the same
scheduled train service. Arrival delay = arrival_change_time - arrival_planned_time
(no change record = on time). Cancelled arrivals count as failures.

Per journey:
  p_late6 / p_late15 : final leg arrives >= 6 / >= 15 min late (or is cancelled)
  p_miss             : probability that at least one change is missed
                       (feeder arrival delay > scheduled change time, or feeder cancelled),
                       legs assumed independent
  p_ontime           : (1 - p_miss) * (1 - p_late6)  -> arriving < 6 min late as planned
Output: data/delays.json
"""
import json
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FILES = str(ROOT / 'data/raw/delays/data-2026-*.parquet').replace('\\', '/')
MIN_SAMPLES = 10


ALIASES = {  # GTFS name -> name in delay data
    'Hamburg, Hamburg-Harburg': 'Hamburg-Harburg',
    'Kassel Bahnhof Wilhelmshöhe': 'Kassel-Wilhelmshöhe',
}
# Long-distance types are matched exactly; regional legs are matched by station and
# planned arrival minute only, because the delay data labels them by operator ("ag", "erx", ...).
FV_TYPES = ('ICE', 'IC', 'EC', 'ECE', 'RJ', 'RJX', 'NJ', 'EN', 'FLX', 'TGV')


def leg_type(t):
    return t if t in FV_TYPES else '*'


def norm(name):
    name = ALIASES.get(name, name)
    n = name.lower().replace('hauptbahnhof', 'hbf').replace('fernbahnhof', 'fernbf').replace(' am main', ' main')
    n = re.sub(r'\(m(ain)?\)', 'main', n)
    n = re.sub(r'\s(bahnhof|bf)$', '', n)
    return re.sub(r'[^a-z0-9äöüß]', '', n)


def main():
    jdata = json.load(open(ROOT / 'data/journeys.json', encoding='utf-8'))
    con = duckdb.connect()
    names = [r[0] for r in con.execute(
        f"select distinct station_name from read_parquet('{FILES}') where station_name is not null").fetchall()]
    con.execute('create table nm(station_name varchar, st varchar)')
    con.executemany('insert into nm values (?,?)', [(n, norm(n)) for n in names])
    # needed (station, type, hh:mm) keys
    keys = set()
    for city in jdata['journeys'].values():
        for d in ('out', 'in'):
            for j in city[d]:
                for leg in j['legs']:
                    keys.add((norm(leg['to']), leg_type(leg['type']), leg['arr']))
    con.execute('create table k(st varchar, typ varchar, hm varchar)')
    con.executemany('insert into k values (?,?,?)', list(keys))
    print(len(keys), 'leg keys')
    rows = con.execute(f"""
        with d as (
          select nm.st, case when train_type in {FV_TYPES} then train_type else '*' end typ,
                 strftime(arrival_planned_time, '%H:%M') hm,
                 coalesce(arrival_is_canceled, false) canc,
                 coalesce(date_diff('minute', arrival_planned_time, arrival_change_time), 0) delay
          from read_parquet('{FILES}') p join nm using (station_name)
          where arrival_planned_time is not null
            and dayofweek(arrival_planned_time) between 1 and 5
        )
        select d.st, d.typ, d.hm, list(case when canc then 9999 else delay end)
        from d join k on d.st = k.st and d.typ = k.typ and d.hm = k.hm
        group by 1, 2, 3
    """).fetchall()
    hist = {(r[0], r[1], r[2]): r[3] for r in rows}
    print(len(hist), 'matched keys')

    def leg_hist(leg):
        h = hist.get((norm(leg['to']), leg_type(leg['type']), leg['arr']))
        return h if h and len(h) >= MIN_SAMPLES else None

    def share(h, thr):
        return sum(1 for x in h if x >= thr) / len(h)

    out = {}
    for city, r in jdata['journeys'].items():
        out[city] = {}
        for d in ('out', 'in'):
            res = []
            for j in r[d]:
                legs = j['legs']
                hs = [leg_hist(l) for l in legs]
                item = {'date': j['date'], 'dep': j['dep'], 'arr': j['arr'],
                        'n_samples': [len(h) if h else 0 for h in hs]}
                if hs[-1] is None or any(h is None for h in hs[:-1]):
                    item['matched'] = False
                else:
                    p_ok_transfers = 1.0
                    for i in range(len(legs) - 1):
                        a = legs[i]['arr']; b = legs[i + 1]['dep']
                        buf = (int(b[:2]) * 60 + int(b[3:])) - (int(a[:2]) * 60 + int(a[3:]))
                        buf %= 1440
                        p_ok_transfers *= 1 - share(hs[i], buf + 1)
                    p6, p15 = share(hs[-1], 6), share(hs[-1], 15)
                    item.update(matched=True, p_late6=p6, p_late15=p15,
                                p_miss=1 - p_ok_transfers,
                                p_ontime=p_ok_transfers * (1 - p6))
                res.append(item)
            m = [x for x in res if x['matched']]
            mean = lambda k: round(sum(x[k] for x in m) / len(m), 3) if m else None
            out[city][d] = {'journeys': res, 'matched': len(m), 'total': len(res),
                            'p_late6': mean('p_late6'), 'p_late15': mean('p_late15'),
                            'p_miss': mean('p_miss'), 'p_ontime': mean('p_ontime')}
            print(f"{city:18s} {d:3s} matched {len(m)}/{len(res)}  "
                  f"late6 {out[city][d]['p_late6']}  miss {out[city][d]['p_miss']}  "
                  f"ontime {out[city][d]['p_ontime']}")
    json.dump({'source': 'piebro/deutsche-bahn-data (CC BY 4.0), 2026-08..2026-10, Mon-Fri',
               'cities': out}, open(ROOT / 'data/delays.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
