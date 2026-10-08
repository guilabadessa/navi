// Media Type "NAVI Webhook" (Zabbix 7.0) — envia PROBLEM/RESOLVED para a NAVI em tempo real.
try {
    var p = JSON.parse(value);
    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    req.addHeader('X-Navi-Token: ' + p.token);

    var tags = [];
    try { tags = JSON.parse(p.tags || '[]'); } catch (e) { tags = []; }

    var body = {
        eventid:   p.eventid,
        status:    (p.status === 'OK' || p.status === 'RESOLVED') ? 'RESOLVED' : 'PROBLEM',
        hostid:    p.hostid,
        host:      p.host,
        ip:        p.ip,
        triggerid: p.triggerid,
        trigger:   p.trigger,
        itemid:    p.itemid,
        item:      p.item,
        severity:  parseInt(p.severity, 10),
        opdata:    p.opdata,
        r_eventid: p.r_eventid,
        tags:      tags
    };

    var resp = req.post(p.url, JSON.stringify(body));
    if (req.getStatus() < 200 || req.getStatus() >= 300) {
        throw 'HTTP ' + req.getStatus() + ': ' + resp;
    }
    return 'OK';
}
catch (error) {
    Zabbix.log(3, '[NAVI webhook] ' + error);
    throw 'NAVI webhook falhou: ' + error;
}
