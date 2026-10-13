from types import SimpleNamespace as NS

from app.services import cloud_service as C
from app.services import protection_service as P


def asset(name, os_name="", family="", source="acronis", role=None):
    m = {"os_name": os_name, "os_family": family, "hostname": name}
    if role:
        m["role"] = role
    return NS(name=name, source=source, meta=m)


def test_windows_generico_e_estacao():
    assert P.machine_role(asset("EC-SEC-00002", "windows", "WINDOWS")) == "workstation"
    assert P.machine_role(asset("EC-LTDA-00023", "Windows 11 Home Single Language", "WINDOWS")) == "workstation"


def test_servidores_continuam_servidores():
    assert P.machine_role(asset("X", "Windows Server 2019", "WINDOWS")) == "server"
    assert P.machine_role(asset("orcati-pbx", "Debian GNU/Linux", "LINUX")) == "server"
    assert P.machine_role(asset("SRV-ARQUIVOS", "windows", "WINDOWS")) == "server"   # nome de servidor
    assert P.machine_role(asset("COCPRDFS", "windows", "WINDOWS")) == "server"       # duvida = servidor
    assert P.machine_role(asset("SRV-2024", "windows", "WINDOWS")) == "server"       # nome de servidor vence a etiqueta
    assert P.machine_role(asset("EC-SEC-1", "windows", "WINDOWS", role="server")) == "server"  # ajuste manual vale


def test_mesma_maquina_em_outra_integracao():
    assert C.same_machine("OrcaTi-Pbx-Telefonia", ["orcati-pbx", None])
    assert C.same_machine("Servidor", ["servidor"])
    assert not C.same_machine("OrcaTi-Pbx-Telefonia", ["pbx"])            # 1 palavra so nao basta
    assert not C.same_machine("OrcaTi-Sql", ["orcati-pbx"])
