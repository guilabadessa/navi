"""Cliente da API JSON-RPC do Zabbix (somente leitura)."""
import httpx


class ZabbixError(Exception):
    pass


class ZabbixService:
    def __init__(self, url: str, token: str, timeout: float = 60.0):
        self.url, self.token = url, token
        self._c = httpx.Client(timeout=timeout, verify=True, headers={"Content-Type": "application/json-rpc"})
        self._id = 0

    def call(self, method: str, params: dict | list | None = None, auth: bool = True):
        self._id += 1
        headers = {}
        if auth and method != "apiinfo.version":
            if not self.token:
                raise ZabbixError("Token da API do Zabbix não configurado")
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = self._c.post(self.url, json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": self._id},
                             headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ZabbixError(f"Falha de conexão com o Zabbix: {e}") from e
        data = r.json()
        if "error" in data:
            e = data["error"]
            raise ZabbixError(f"{e.get('message')}: {e.get('data')}")
        return data["result"]

    def version(self) -> str:
        return self.call("apiinfo.version", auth=False)

    # --- inventario ---
    def host_groups(self):
        return self.call("hostgroup.get", {"output": ["groupid", "name"], "with_hosts": True,
                                            "selectHosts": "count"})

    def hosts(self):
        return self.call("host.get", {
            "output": ["hostid", "host", "name", "status", "active_available"],
            "selectInterfaces": ["interfaceid", "ip", "dns", "type", "main", "available", "port"],
            "selectHostGroups": ["groupid"],
            "selectParentTemplates": ["templateid", "name"],
            "selectTags": ["tag", "value"],
            "filter": {"flags": 0},
        })

    def item_counts(self):
        return self.call("item.get", {"output": ["hostid"], "countOutput": False, "filter": {"flags": [0, 4]},
                                      "monitored": True, "templated": None})

    def items(self, hostids: list[str] | None = None, limit: int | None = None):
        p = {"output": ["itemid", "hostid", "name", "key_", "status", "state", "units", "lastvalue", "lastclock"],
             "filter": {"flags": [0, 4]}, "sortfield": "itemid"}
        if hostids:
            p["hostids"] = hostids
        if limit:
            p["limit"] = limit
        return self.call("item.get", p)

    def triggers(self):
        return self.call("trigger.get", {
            "output": ["triggerid", "description", "priority", "status", "value", "lastchange"],
            "selectHosts": ["hostid"], "expandDescription": True, "monitored": True, "skipDependent": False})

    # --- eventos ---
    def problem_events(self, time_from: int, time_till: int | None = None, limit: int = 5000):
        p = {"output": ["eventid", "r_eventid", "clock", "name", "severity", "objectid", "acknowledged"],
             "source": 0, "object": 0, "value": 1, "time_from": time_from, "sortfield": ["eventid"],
             "sortorder": "ASC", "limit": limit, "selectHosts": ["hostid", "host", "name"],
             "selectTags": "extend", "selectRelatedObject": ["triggerid", "description", "priority"]}
        if time_till:
            p["time_till"] = time_till
        return self.call("event.get", p)

    def events_by_ids(self, ids: list[str]):
        if not ids:
            return []
        return self.call("event.get", {"eventids": ids, "output": ["eventid", "clock", "value"], "source": 0, "object": 0})

    def trigger_items(self, triggerids: list[str]):
        if not triggerids:
            return {}
        res = self.call("trigger.get", {"triggerids": triggerids, "output": ["triggerid"],
                                         "selectItems": ["itemid", "name"], "expandDescription": True})
        return {t["triggerid"]: t.get("items", []) for t in res}

    def active_problems(self):
        return self.call("problem.get", {"output": ["eventid", "objectid", "clock", "severity", "name"],
                                          "source": 0, "object": 0, "recent": False, "suppressed": False})
