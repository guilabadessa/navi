"""KPIs: disponibilidade por uniao de intervalos de indisponibilidade (sem dupla contagem de eventos sobrepostos)."""
from collections import defaultdict
from datetime import datetime, timezone

from ..models import SEVERITIES


def _union(intervals: list[tuple[float, float]]) -> float:
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def _subtract(iv: tuple[float, float], excl: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove de 'iv' os trechos cobertos por 'excl' (janelas de manutencao)."""
    pieces = [iv]
    for xs, xe in excl:
        nxt = []
        for s, e in pieces:
            if xe <= s or xs >= e:
                nxt.append((s, e))
                continue
            if xs > s:
                nxt.append((s, xs))
            if xe < e:
                nxt.append((xe, e))
        pieces = nxt
    return [(s, e) for s, e in pieces if e > s]


def compute(events: list, hosts: list[dict], start: datetime, end: datetime, sla_target: float | None = None,
            exclude: list[tuple[float, float]] | None = None) -> dict:
    """events: objetos Event; hosts: [{hostid,name,ip}] universo avaliado."""
    now = datetime.now(timezone.utc)
    end_eff = min(end, now)
    period = max(1.0, (end_eff - start).total_seconds())
    S, E = start.timestamp(), end_eff.timestamp()

    per_host: dict[str, list] = defaultdict(list)
    rows = []
    for ev in events:
        s = max(ev.started_at.timestamp(), S)
        e = min((ev.recovered_at or now).timestamp(), E)
        if e <= s:
            continue
        pieces = _subtract((s, e), exclude) if exclude else [(s, e)]
        if not pieces:
            continue  # todo o incidente ocorreu dentro de manutencao programada
        per_host[ev.hostid or ev.host].extend(pieces)
        rows.append((ev, sum(b - a for a, b in pieces)))

    hostmap = {h["hostid"]: h for h in hosts}
    for ev in events:
        if (ev.hostid or ev.host) not in hostmap and ev.hostid:
            hostmap[ev.hostid] = {"hostid": ev.hostid, "name": ev.host, "ip": ev.ip}
    host_stats = []
    total_down = 0.0
    for hid, h in hostmap.items():
        ivs = per_host.get(hid, [])
        down = _union(ivs)
        inc = [ev for ev, _ in rows if (ev.hostid or ev.host) == hid]
        total_down += down
        host_stats.append({
            "hostid": hid, "host": h.get("name"), "ip": h.get("ip"), "incidents": len(inc),
            "downtime_s": int(down), "availability": round(100 * (1 - down / period), 4),
            "mtbf_s": int((period - down) / len(inc)) if inc else None})
    n_hosts = max(1, len(hostmap))
    availability = round(100 * (1 - total_down / (period * n_hosts)), 4)

    durs = [d for _, d in rows]
    resolved = [ev for ev, _ in rows if ev.status == "RESOLVED"]
    open_ = [ev for ev, _ in rows if ev.status != "RESOLVED"]
    res_durs = [d for ev, d in rows if ev.status == "RESOLVED"]
    biggest = max(rows, key=lambda x: x[1]) if rows else None
    smallest = min(rows, key=lambda x: x[1]) if rows else None
    mtbfs = [h["mtbf_s"] for h in host_stats if h["mtbf_s"] is not None]

    def count_by(keyf):
        c = defaultdict(lambda: [0, 0.0])
        for ev, d in rows:
            k = keyf(ev) or "-"
            c[k][0] += 1
            c[k][1] += d
        return sorted(({"key": k, "incidents": v[0], "downtime_s": int(v[1])} for k, v in c.items()),
                      key=lambda x: (-x["incidents"], -x["downtime_s"]))

    by_sev = count_by(lambda e: SEVERITIES.get(e.severity, str(e.severity)))
    by_day = defaultdict(int)
    for ev, _ in rows:
        by_day[ev.started_at.astimezone(timezone.utc).strftime("%Y-%m-%d")] += 1

    sla_actual = availability
    summary = {
        "period_s": int(period), "hosts_total": len(hostmap),
        "hosts_affected": len({(ev.hostid or ev.host) for ev, _ in rows}),
        "availability": availability, "downtime_s": int(total_down), "downtime_h": round(total_down / 3600, 2),
        "incidents": len(rows), "resolved": len(resolved), "open": len(open_),
        "mttr_s": int(sum(res_durs) / len(res_durs)) if res_durs else None,
        "mtbf_s": int(sum(mtbfs) / len(mtbfs)) if mtbfs else None,
        "avg_duration_s": int(sum(durs) / len(durs)) if durs else None,
        "max_duration_s": int(biggest[1]) if biggest else None, "min_duration_s": int(smallest[1]) if smallest else None,
        "biggest": {"host": biggest[0].host, "trigger": biggest[0].trigger_name, "duration_s": int(biggest[1])} if biggest else None,
        "sla_target": sla_target, "sla_actual": sla_actual,
        "sla_met": (sla_actual >= sla_target) if sla_target is not None else None,
    }
    return {
        "summary": summary,
        "by_host": sorted(host_stats, key=lambda x: (-x["downtime_s"], -x["incidents"])),
        "by_severity": by_sev, "by_trigger": count_by(lambda e: e.trigger_name)[:15],
        "by_item": count_by(lambda e: e.item_name)[:15], "by_day": dict(sorted(by_day.items())),
    }
