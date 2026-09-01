"""Metadata discovery for ACA SDIM.

Automates the AJAX endpoints that populate the SDIM UI so the library can
resolve human-readable selections (river, basin, parameter, ...) to the internal
IDs used by ``consultaInforme.do``.

Endpoints covered:

* ``filtre.do``                -> networks + subnetworks (per period)
* ``serveiTipusVariables.do``  -> variable-type tree (g / f / v)
* spatial providers            -> rivers, basins, comarques, municipis,
                                  aquifers, masses, reservoirs
* ``serveiDetallSeleccio.do``  -> stations (code, name, coords)
"""

from __future__ import annotations

import re
from html import unescape
from typing import Iterable

from .query import PERIOD_AFTER_2007, PERIOD_BEFORE_2007
from .session import SDIMSession

BASE = "https://aplicacions.aca.gencat.cat/sdim21"
PERIODS = (PERIOD_AFTER_2007, PERIOD_BEFORE_2007)

# provider name -> (endpoint suffix, checkbox field name)
SPATIAL_PROVIDERS = {
    "rivers": ("serveiRius.do", "riuAmbit"),
    "basins": ("serveiConques.do", "concaAmbit"),
    "comarcas": ("serveiComarques.do", "comarcaAmbit"),
    "municipis": ("serveiMunicipis.do", "municipiAmbit"),
    "aquifers": ("serveiAquifer.do", "AquiferAmbit"),
    "masses": ("serveiMasses.do", "massaAmbit"),
    "reservoirs": ("serveiEmbassaments.do", "embassamentAmbit"),
}


def _clean(text: str | None) -> str:
    if text is None:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parse_elements(html: str, field: str) -> list[tuple[str, str]]:
    """Parse ``<input name=field value=code/> <label>name</label>`` pairs."""
    result: list[tuple[str, str]] = []
    for attrs, label in _blocks(html):
        if attrs.get("name") == field:
            name = _clean(label)
            code = attrs.get("value", "")
            if name and (code, name) not in result:
                result.append((code, name))
    return result


def _blocks(html: str) -> list[tuple[dict[str, str], str]]:
    """Yield (input_attributes, label_text) for each ``<div>`` block."""
    attr_re = re.compile(r'([\w]+)="([^"]*)"')
    item = re.compile(r"<input[^>]*?(?:/>|>)", re.S)
    label_re = re.compile(r"<label[^>]*>(.*?)</label>", re.S)
    out = []
    for block in re.findall(r"<div[^>]*>(.*?)</div>", html, re.S):
        tag = item.search(block)
        if not tag:
            continue
        attrs = dict(attr_re.findall(tag.group(0)))
        label = label_re.search(block)
        out.append((attrs, _clean(label.group(1)) if label else ""))
    return out


def _parse_tipus_tree(
    html: str,
) -> list[tuple[str, str, str, str, str, str]]:
    """Parse the g/f/v variable tree.

    Returns (g, g_name, f, f_name, v, v_name) tuples.
    """
    import lxml.html  # project dependency

    root = lxml.html.fromstring(f"<div>{html}</div>")
    rows: list[tuple[str, str, str, str, str, str]] = []
    for group in root.xpath(".//ul[contains(@class, 'nodoGrupo')]"):
        g_input = group.xpath("./li[1]//input[@name='g']")
        g_a = group.xpath("./li[1]/a")
        if not g_input:
            continue
        g_code = g_input[0].get("value", "")
        g_name = _clean(g_a[0].text_content()) if g_a else ""
        # all families are sibling <li> inside one <ul class="nodoFamilia">
        for fam_li in group.xpath(".//ul[contains(@class, 'nodoFamilia')]/li"):
            f_input = fam_li.xpath("./input[@name='f']")
            f_a = fam_li.xpath("./a")
            if not f_input:
                continue
            f_code = f_input[0].get("value", "")
            f_name = _clean(f_a[0].text_content()) if f_a else ""
            for var_li in fam_li.xpath(".//ul[contains(@class, 'nodoVariable')]/li"):
                v_input = var_li.xpath("./input[@name='v']")
                v_label = var_li.xpath("./label")
                if not v_input:
                    continue
                v_code = v_input[0].get("value", "")
                v_name = _clean(v_label[0].text_content()) if v_label else ""
                rows.append((g_code, g_name, f_code, f_name, v_code, v_name))
    return rows


class Discovery:
    """Discover SDIM metadata IDs by talking to the AJAX endpoints."""

    def __init__(self, session: SDIMSession | None = None, delay: float = 0.4,
                 timeout: float = 90.0):
        self.session = session or SDIMSession(delay=delay, timeout=timeout)
        self._pages: dict[str, str] = {}

    # -- session / pages ---------------------------------------------------

    def _bootstrap(self, period: str) -> str:
        if period in self._pages:
            return self._pages[period]
        self.session.initialize()
        self.session.post(
            BASE + "/seleccioXarxes.do",
            data={"accio": "seleccioXarxa", "page": "inici"},
        )
        r = self.session.post(
            BASE + "/filtre.do",
            data={
                "accio": "puntsDeControl",
                "page": "periodeControl",
                "periodeXarxaControl": period,
            },
        )
        self._pages[period] = r.text
        return r.text

    # -- networks / subnetworks --------------------------------------------

    def networks(self, period: str) -> list[tuple[str, str]]:
        page = self._bootstrap(period)
        return _parse_elements(page, "xarxaControl")

    def subnetworks(self, period: str) -> list[tuple[str, str, str]]:
        """Return (subnetwork_code, network_code, name)."""
        page = self._bootstrap(period)
        result: list[tuple[str, str, str]] = []
        for attrs, label in _blocks(page):
            if attrs.get("name") != "subXarxaControl":
                continue
            code = attrs.get("value", "")
            cls = attrs.get("class", "")
            parent_match = re.search(r"xarxaControl([A-Za-z0-9]+)", cls)
            parent = parent_match.group(1) if parent_match else ""
            name = _clean(label)
            if name and (code, parent, name) not in result:
                result.append((code, parent, name))
        return result

    # -- variable tree -----------------------------------------------------

    def _post_body(self, endpoint: str, data: list[tuple[str, str]]) -> str:
        """POST an endpoint and return the response text (helper for caches)."""
        return self.session.post(BASE + endpoint, data=data).text

    def variable_tree(
        self,
        period: str,
        network: str,
        subnetworks: Iterable[str],
    ) -> list[tuple[str, str, str, str, str, str]]:
        """Fetch the g/f/v tree for a network/subnetwork selection."""
        data = [("periodeXarxaControl", period), ("xarxaControl", network)]
        data += [("subXarxaControl", s) for s in subnetworks]
        r = self.session.post(BASE + "/serveis/serveiTipusVariables.do", data=data)
        return _parse_tipus_tree(r.text)

    def variables(self, period: str) -> list[dict]:
        """All g/f/v branches across every subnetwork of the period."""
        rows: list[dict] = []
        seen = set()
        for period2 in ([period] if period else PERIODS):
            subs = self.subnetworks(period2)
            for code, parent, _name in subs:
                for row in self.variable_tree(period2, parent, [code]):
                    g, gn, f, fn, v, vn = row
                    key = (period2, parent, code, g, f, v)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "period": period2, "network": parent, "subnetwork": code,
                        "g": g, "g_name": gn, "f": f, "f_name": fn,
                        "v": v, "v_name": vn,
                    })
        return rows

    # -- spatial elements --------------------------------------------------

    def spatial(self, period: str, provider: str) -> list[tuple[str, str]]:
        """All elements of a spatial provider for a period (code, name)."""
        endpoint, field = SPATIAL_PROVIDERS[provider]
        subs = [c for c, _p, _n in self.subnetworks(period)]
        nets = [n for n, _name in self.networks(period)]
        data = [("periodeXarxaControl", period)]
        data += [("xarxaControl", n) for n in nets]
        data += [("subXarxaControl", s) for s in subs]
        r = self.session.post(BASE + "/serveis/" + endpoint, data=data)
        return _parse_elements(r.text, field)

    # -- stations ----------------------------------------------------------

    def stations(self, period: str) -> list[dict]:
        """All monitoring stations for a period (code, name, x, y)."""
        records: list[dict] = []
        seen = set()
        for network, _name in self.networks(period):
            subs = [c for c, p, _n in self.subnetworks(period) if p == network]
            data = [
                ("periodeXarxaControl", period),
                ("xarxaControl", network),
            ] + [("subXarxaControl", s) for s in subs] + [
                ("ambit", "catalunya"),
                ("modoConsultaDetall", "resumen"),
            ]
            r = self.session.post(BASE + "/serveis/serveiDetallSeleccio.do", data=data)
            pattern = re.compile(
                r'<input[^>]*name="puntControl"[^>]*value="([^"]*)"'
                r'[^>]*x="([^"]*)" y="([^"]*)"[^>]*>\s*<a[^>]*>\s*'
                r"<label[^>]*title=\"([^\"]*)\"",
                re.S,
            )
            for code, x, y, name in pattern.findall(r.text):
                if code in seen:
                    continue
                seen.add(code)
                records.append({
                    "period": period, "network": network, "station": code,
                    "name": unescape(name), "x": x, "y": y,
                })
        return records

    def detail_select(
        self,
        period: str,
        network: str,
        subnetworks: Iterable[str],
        *,
        variable_kinds: Iterable[tuple[str, str]] = (),
        ambit: str = "catalunya",
        spatial: dict[str, list[str]] | None = None,
    ) -> list[dict]:
        """Resolve the station↔variable set for a target + spatial filter.

        Mirrors the UI's final selection step (``serveiDetallSeleccio.do`` in
        completa mode). Returns ``parse_detall_completa`` records.
        """
        data = [("periodeXarxaControl", period), ("xarxaControl", network)]
        data += [("subXarxaControl", s) for s in subnetworks]
        for kind, value in variable_kinds or ():
            data.append((kind, value))
        data.append(("ambit", ambit))
        for field, values in (spatial or {}).items():
            for value in values:
                data.append((field, value))
        data.append(("modoConsultaDetall", "completa"))
        r = self.session.post(BASE + "/serveis/serveiDetallSeleccio.do", data=data)
        return parse_detall_completa(r.text)

    def close(self) -> None:
        self.session.close()


def parse_detall_completa(html: str) -> list[dict]:
    """Parse a ``serveiDetallSeleccio.do`` completa-mode response.

    Returns one dict per station: ``{station, name, x, y,
    variables: [(variable_id, name), ...]}``.
    """
    import lxml.html

    root = lxml.html.fromstring(f"<div>{html}</div>")
    out: list[dict] = []
    for li in root.xpath(".//li[./input[@name='puntControl']]"):
        inp = li.xpath("./input[@name='puntControl']")[0]
        code = inp.get("value", "")
        x, y = inp.get("x", ""), inp.get("y", "")
        label = li.xpath("./a/label")
        name = _clean(label[0].text_content()) if label else ""
        variables = []
        for vin in li.xpath("./ul//li[./input[@name='variable']]"):
            vi = vin.xpath("./input[@name='variable']")[0]
            vl = vin.xpath("./label")
            variables.append((vi.get("value", ""), _clean(vl[0].text_content()) if vl else ""))
        out.append({
            "station": code, "name": name, "x": x, "y": y, "variables": variables,
        })
    return out