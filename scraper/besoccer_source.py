#!/usr/bin/env python3
"""Fuente BeSoccer para Primera Federación 2026/27.

Estrategia de cobertura completa:
1. BeSoccer sigue siendo la única fuente de scraping.
2. Descubrimos los 20 equipos de cada grupo desde la competición 2026/27.
3. Abrimos la página de partidos de CADA equipo y agregamos todas las entradas
   de Primera Federación de la temporada. Así no dependemos de que el selector
   de jornadas de la página de resultados sea navegable desde requests.
4. Deduplificamos los encuentros y los cruzamos con docs/data/horarios.json.

Esto evita el fallo anterior: una jornada podía tener horarios confirmados en
BeSoccer pero quedar vacía si /jornadaN redirigía a la jornada activa.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from curl_cffi import requests as curl_requests

BASE_COMPETITION = "https://es.besoccer.com/competicion/resultados/primera_division_rfef/2027"
BASE_TEAMS = "https://es.besoccer.com/competicion/equipos/primera_division_rfef/2027"
MADRID = ZoneInfo("Europe/Madrid")
SEASON_START = date(2026, 8, 28)
SEASON_END = date(2027, 5, 23)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

ROUND_RE = re.compile(r"(?:Jornada|Round)\s+(\d+)", re.IGNORECASE)
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
DATE_TEXT_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+"
    r"(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC|"
    r"JAN|APR|AUG|DEC)"
    r"(?:\s+(20\d{2}))?(?!\d)",
    re.IGNORECASE,
)
LEAGUE_RE = re.compile(r"Primera\s+(?:Federaci[oó]n|RFEF|Divisi[oó]n\s+RFEF)", re.IGNORECASE)

MONTHS = {
    "ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
}

# Nombres de BeSoccer que no coinciden literalmente con el calendario oficial.
ALIASES = {
    "arenasdegetxo": "Arenas Club",
    "arenasclubdegetxo": "Arenas Club",
    "culturalleonesa": "CyD Leonesa",
    "culturalydeportivaleonesa": "CyD Leonesa",
    "bilbaoathletic": 'Athletic Club "B"',
    "athleticbilbaob": 'Athletic Club "B"',
    "deportivofabril": "RC Deportivo Fabril",
    "realclubdeportivofabril": "RC Deportivo Fabril",
    "rcdeportivob": "RC Deportivo Fabril",
    "juventudtorremolinos": "Juventud de Torremolinos CF",
    "juventuddetorremolinos": "Juventud de Torremolinos CF",
    "atleticomadridb": "Atlético Madrileño",
    "atleticomadrileno": "Atlético Madrileño",
    "atleticodemadridb": "Atlético Madrileño",
    "nasticdetarragona": "Gimnàstic de Tarragona",
    "nastictarragona": "Gimnàstic de Tarragona",
    "gimnastictarragona": "Gimnàstic de Tarragona",
    "villarealb": 'Villarreal CF "B"',
    "villarrealb": 'Villarreal CF "B"',
    "rmcastilla": "Real Madrid Castilla",
    "realmadridcastilla": "Real Madrid Castilla",
    "udibiza": "UD Ibiza",
    "udibizaeivissa": "UD Ibiza",
    "santandreu": "UE Sant Andreu",
    "uesantandreu": "UE Sant Andreu",
    "realjaen": "Real Jaén CF",
    "realjaencf": "Real Jaén CF",
    "hercules": "Hércules de Alicante CF",
    "herculesdealicante": "Hércules de Alicante CF",
    "herculesdealicantecf": "Hércules de Alicante CF",
    "alcorcon": "AD Alcorcón",
    "rayomajadahonda": "CF Rayo Majadahonda",
    "extremadura": "CD Extremadura",
    "coria": "CD Coria",
    "ourense": "UD Ourense",
    "ourensecf": "UD Ourense",
    "racingferrol": "Racing Club Ferrol",
    "barakaldo": "Barakaldo CF",
    "mirandes": "CD Mirandés",
    "ponferradina": "SD Ponferradina",
    "ponferradinasd": "SD Ponferradina",
    "pontevedra": "Pontevedra CF",
    "unionistascf": "Unionistas de Salamanca CF",
    "unionistasdesalamanca": "Unionistas de Salamanca CF",
    "realaviles": "Real Avilés Industrial",
    "huesca": "SD Huesca",
    "realmurcia": "Real Murcia CF",
    "algeciras": "Algeciras CF",
    "cartagena": "FC Cartagena",
    "teruel": "CD Teruel",
}


# Fallback estable: evita depender de /competicion/equipos cuando BeSoccer
# responde 406 a GitHub Actions. Los slugs proceden de las páginas oficiales
# de cada club en BeSoccer. El descubrimiento dinámico se conserva como primera
# opción para detectar futuros cambios de slug.
STATIC_TEAM_SLUGS = {
    1: {
        "AD Mérida": "merida-ad-senior",
        "Arenas Club": "arenas-club",
        'Athletic Club "B"': "athletic-bilbao-b",
        "Barakaldo CF": "barakaldo-cf",
        "CD Coria": "cd-coria",
        "CD Extremadura": "cd-extremadura",
        "CD Lugo": "lugo",
        "CD Mirandés": "mirandes",
        "CP Cacereño": "cacereno",
        "CyD Leonesa": "cultural-deportiva-leonesa",
        "Pontevedra CF": "pontevedra-cf",
        "RC Deportivo Fabril": "deportivo-b",
        "Racing Club Ferrol": "racing-club-ferrol",
        "Real Avilés Industrial": "real-aviles-ind",
        "Real Unión Club": "real-union-club-irun",
        "SD Ponferradina": "ponferradina-sd",
        "UD Logroñés": "ud-logrones",
        "UD Ourense": "ourense-ud",
        "Unionistas de Salamanca CF": "cd-unionistas-salamanca-cf-senior",
        "Zamora CF": "zamora",
    },
    2: {
        "AD Alcorcón": "ad-alcorcon",
        "Algeciras CF": "algeciras-cf",
        "Antequera CF": "antequera",
        "Atlético Madrileño": "at-madrid-b",
        "CD Teruel": "teruel",
        "CE Europa": "ce-europa",
        "CF Rayo Majadahonda": "rayo-majadahonda",
        "FC Cartagena": "cartagena",
        "Gimnàstic de Tarragona": "gimnastic-tarragona",
        "Hércules de Alicante CF": "hercules",
        "Juventud de Torremolinos CF": "juventud-torremolinos",
        "Real Jaén CF": "real-jaen",
        "Real Madrid Castilla": "rm-castilla",
        "Real Murcia CF": "real-murcia",
        "Real Zaragoza": "real-zaragoza",
        "SD Huesca": "huesca",
        "UD Ibiza": "ibiza-eivissa",
        "UE Sant Andreu": "sant-andreu",
        'Villarreal CF "B"': "villarreal-b",
        "Águilas FC": "aguilas-cf",
    },
}


def static_team_schedule_urls(group: int) -> dict[str, str]:
    return {
        team: f"https://es.besoccer.com/equipo/partidos/{slug}"
        for team, slug in STATIC_TEAM_SLUGS.get(group, {}).items()
    }


@dataclass
class Match:
    local: str
    visitante: str
    jornada: int | None = None
    fecha: str | None = None
    hora: str | None = None
    resultado: str | None = None
    tv: str | None = None
    fuente: str | None = None
    es_primera_federacion: bool = False


def normaliza(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def _www_fallback_url(url: str) -> str | None:
    """Convierte una URL española de equipo a la variante internacional.

    BeSoccer puede aplicar reglas anti-bot distintas por subdominio. La variante
    internacional sirve como segundo intento y usa los mismos datos de partido.
    Las horas se normalizan después a Europe/Madrid desde starttime.
    """
    parsed = urlparse(url)
    if parsed.netloc != "es.besoccer.com":
        return None

    path = parsed.path
    if path.startswith("/equipo/partidos/"):
        slug = path.split("/equipo/partidos/", 1)[1].strip("/")
        return f"https://www.besoccer.com/team/matches/{slug}"
    if path.startswith("/equipo/"):
        slug = path.split("/equipo/", 1)[1].strip("/")
        return f"https://www.besoccer.com/team/{slug}"
    return None


def _get_with_browser_fingerprint(url: str):
    """GET con huella TLS/HTTP2 de Chrome.

    requests con un User-Agent de navegador sigue teniendo una huella de red de
    cliente Python y BeSoccer puede responder 406 desde GitHub Actions.
    curl_cffi reproduce la huella TLS/JA3/HTTP2 de Chrome.
    """
    last_exc = None
    for attempt in range(3):
        try:
            response = curl_requests.get(
                url,
                headers=HEADERS,
                impersonate="chrome",
                timeout=30,
                allow_redirects=True,
            )
            if response.status_code < 400:
                return response
            last_exc = RuntimeError(f"HTTP {response.status_code} en {url}")
            # 406/403/429 no mejoran martilleando el servidor.
            if response.status_code in (403, 406, 429):
                break
        except Exception as exc:
            last_exc = exc
        if attempt < 2:
            time.sleep(1.2 * (attempt + 1))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"No se pudo descargar {url}")


def fetch(url: str) -> BeautifulSoup:
    errors = []
    candidates = [url]
    fallback = _www_fallback_url(url)
    if fallback and fallback not in candidates:
        candidates.append(fallback)

    for candidate in candidates:
        try:
            r = _get_with_browser_fingerprint(candidate)
            return BeautifulSoup(r.text, "html.parser")
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    raise RuntimeError(" | ".join(errors))


def _team_text(node: Tag, itemprop: str) -> str | None:
    el = node.find(attrs={"itemprop": itemprop})
    if not el:
        return None
    return el.get_text(" ", strip=True)


def _match_nodes(soup: BeautifulSoup) -> list[Tag]:
    """Devuelve tarjetas de partido sin depender de una sola clase CSS."""
    nodes: list[Tag] = []
    seen: set[int] = set()

    selectors = (
        "div.comp-matches a[data-status]",
        "div.matches a[data-status]",
        "a[data-status]",
        "article a[data-status]",
    )
    for selector in selectors:
        for node in soup.select(selector):
            if node.find(attrs={"itemprop": "homeTeam"}) and node.find(attrs={"itemprop": "awayTeam"}):
                if id(node) not in seen:
                    seen.add(id(node))
                    nodes.append(node)

    # Fallback semántico.
    if not nodes:
        for home in soup.find_all(attrs={"itemprop": "homeTeam"}):
            node = home
            for _ in range(9):
                if not isinstance(node, Tag):
                    break
                if node.find(attrs={"itemprop": "awayTeam"}):
                    if node.find(attrs={"starttime": True}) or node.name == "a" or node.get("data-status") is not None:
                        break
                node = node.parent
            if isinstance(node, Tag) and node.find(attrs={"itemprop": "awayTeam"}):
                if id(node) not in seen:
                    seen.add(id(node))
                    nodes.append(node)

    return nodes


def _parse_starttime(node: Tag) -> tuple[str | None, str | None]:
    el = node.find(attrs={"starttime": True})
    raw = el.get("starttime") if el else None
    if not raw:
        raw = node.get("starttime")
    if not raw:
        return None, None

    raw = str(raw).strip()
    try:
        if raw.isdigit() and len(raw) >= 10:
            ts = int(raw[:10])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(MADRID)
        else:
            raw = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MADRID)
            else:
                dt = dt.astimezone(MADRID)
        return dt.date().isoformat(), dt.strftime("%H:%M")
    except (ValueError, OverflowError):
        return None, None


def _infer_season_year(month: int) -> int:
    return 2026 if month >= 8 else 2027


def _parse_visible_datetime(node: Tag) -> tuple[str | None, str | None]:
    texto = node.get_text(" ", strip=True)
    fecha = None

    dm = DATE_DMY_RE.search(texto)
    if dm:
        d, m, y = map(int, dm.groups())
        try:
            fecha = date(y, m, d).isoformat()
        except ValueError:
            pass
    else:
        tm_date = DATE_TEXT_RE.search(texto)
        if tm_date:
            d = int(tm_date.group(1))
            m = MONTHS[tm_date.group(2).upper()]
            y = int(tm_date.group(3)) if tm_date.group(3) else _infer_season_year(m)
            try:
                fecha = date(y, m, d).isoformat()
            except ValueError:
                pass

    tm = TIME_RE.search(texto)
    hora = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None
    return fecha, hora


def _parse_tv(node: Tag) -> str | None:
    partes = []
    for el in node.find_all(True):
        clases = " ".join(el.get("class", []))
        ident = el.get("id", "") or ""
        marca = f"{clases} {ident}".lower()
        if any(k in marca for k in ("televis", "channel", "tv-", " tv ")):
            txt = el.get_text(" ", strip=True)
            if txt and txt not in partes:
                partes.append(txt)
    return " / ".join(partes) if partes else None


def parse_matches(soup: BeautifulSoup, source_url: str) -> list[Match]:
    matches: list[Match] = []
    for node in _match_nodes(soup):
        local = _team_text(node, "homeTeam")
        visitante = _team_text(node, "awayTeam")
        if not local or not visitante:
            continue

        texto = node.get_text(" ", strip=True)
        jmatch = ROUND_RE.search(texto)
        jornada = int(jmatch.group(1)) if jmatch else None

        fecha, hora = _parse_starttime(node)
        if not fecha:
            vfecha, vhora = _parse_visible_datetime(node)
            fecha = vfecha
            hora = hora or vhora
        elif not hora:
            _, vhora = _parse_visible_datetime(node)
            hora = vhora

        score = SCORE_RE.search(texto)
        resultado = f"{score.group(1)}-{score.group(2)}" if score else None

        matches.append(Match(
            local=local,
            visitante=visitante,
            jornada=jornada,
            fecha=fecha,
            hora=hora,
            resultado=resultado,
            tv=_parse_tv(node),
            fuente=source_url,
            es_primera_federacion=bool(LEAGUE_RE.search(texto)),
        ))
    return matches


def _official_team_name(name: str, official_names: list[str]) -> str | None:
    n = normaliza(name)
    if n in ALIASES:
        alias = ALIASES[n]
        if alias in official_names:
            return alias

    by_norm = {normaliza(e): e for e in official_names}
    if n in by_norm:
        return by_norm[n]

    candidatos = [e for key, e in by_norm.items() if n and (n in key or key in n)]
    return candidatos[0] if len(set(candidatos)) == 1 else None


def _official_names(data: dict, group: int) -> list[str]:
    out = set()
    for jornada in data["grupos"][str(group)]["jornadas"].values():
        for p in jornada["partidos"]:
            out.add(p["local"])
            out.add(p["visitante"])
    return sorted(out)


def _schedule_url(team_url: str) -> str:
    parsed = urlparse(team_url)
    path = parsed.path
    if "/equipo/partidos/" in path:
        return team_url
    if "/equipo/" in path:
        path = path.replace("/equipo/", "/equipo/partidos/", 1)
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def discover_team_schedule_urls(data: dict, group: int, soup: BeautifulSoup, page_url: str) -> dict[str, str]:
    official = _official_names(data, group)
    found: dict[str, str] = {}

    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        if "/equipo/" not in urlparse(href).path:
            continue
        label = a.get_text(" ", strip=True) or a.get("title", "")
        if not label:
            img = a.find("img")
            label = (img.get("alt", "") if img else "") or ""
        team = _official_team_name(label, official)
        if team:
            found[team] = _schedule_url(href)

    return found


def _in_season(raw: str | None) -> bool:
    if not raw:
        return False
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return False
    return SEASON_START <= d <= SEASON_END


def _match_quality(m: Match) -> int:
    return sum(bool(x) for x in (m.fecha, m.hora, m.resultado, m.tv, m.jornada))


def _merge_match(old: Match | None, new: Match) -> Match:
    if old is None:
        return new
    # Conserva el registro más completo y rellena huecos con el otro.
    best, other = (new, old) if _match_quality(new) >= _match_quality(old) else (old, new)
    return Match(
        local=best.local,
        visitante=best.visitante,
        jornada=best.jornada or other.jornada,
        fecha=best.fecha or other.fecha,
        hora=best.hora or other.hora,
        resultado=best.resultado or other.resultado,
        tv=best.tv or other.tv,
        fuente=best.fuente or other.fuente,
        es_primera_federacion=best.es_primera_federacion or other.es_primera_federacion,
    )


def apply_matches(data: dict, group: int, jornada: int, matches: list[Match], mode: str) -> tuple[bool, int]:
    jornada_data = data["grupos"].get(str(group), {}).get("jornadas", {}).get(str(jornada))
    if not jornada_data:
        return False, 0

    official = _official_names(data, group)
    changed = False
    changes = 0

    for m in matches:
        local = _official_team_name(m.local, official)
        visitante = _official_team_name(m.visitante, official)
        if not local or not visitante:
            continue

        partido = next((p for p in jornada_data["partidos"]
                        if p["local"] == local and p["visitante"] == visitante), None)
        if not partido:
            continue

        if mode == "horarios":
            if m.fecha and partido.get("fecha") != m.fecha:
                partido["fecha"] = m.fecha
                changed = True
                changes += 1
            if m.hora and partido.get("hora") != m.hora:
                partido["hora"] = m.hora
                changed = True
                changes += 1
            if m.tv and partido.get("tv") != m.tv:
                partido["tv"] = m.tv
                changed = True
                changes += 1
            if (m.fecha or m.hora or m.tv) and partido.get("fuente") != m.fuente:
                partido["fuente"] = m.fuente
        elif mode == "resultados":
            if m.resultado and partido.get("resultado") != m.resultado:
                partido["resultado"] = m.resultado
                partido["fuente_resultado"] = m.fuente
                changed = True
                changes += 1

    return changed, changes


def scrape_group(data: dict, group: int, mode: str) -> tuple[list[int], list[str], dict[int, dict[str, int]]]:
    """Scrapea un grupo completo desde las páginas de equipos de BeSoccer.

    La función falla si no puede descubrir o descargar los 20 equipos. Es mejor
    abortar una ejecución que guardar un scrapeo silenciosamente incompleto.
    """
    # BeSoccer usa /grupo2 de forma explícita, mientras que el Grupo 1 puede
    # aparecer como vista por defecto sin sufijo. Probamos ambas variantes.
    team_page_candidates = [f"{BASE_TEAMS}/grupo{group}"]
    if group == 1:
        team_page_candidates.append(BASE_TEAMS)

    warnings: list[str] = []
    changed_rounds: list[int] = []
    official = _official_names(data, group)
    urls: dict[str, str] = {}
    page_errors: list[str] = []

    for teams_page in team_page_candidates:
        try:
            soup = fetch(teams_page)
        except Exception as exc:
            page_errors.append(f"{teams_page}: {exc}")
            continue
        candidate_urls = discover_team_schedule_urls(data, group, soup, teams_page)
        urls.update(candidate_urls)
        if len(urls) == len(official):
            break

    # Si la portada de equipos devuelve 406 (caso observado en GitHub Actions),
    # completamos los slugs desde el mapa verificado de BeSoccer. Esto elimina
    # un punto único de fallo sin cambiar la fuente de datos.
    static_urls = static_team_schedule_urls(group)
    for team in official:
        if team not in urls and team in static_urls:
            urls[team] = static_urls[team]

    missing = [team for team in official if team not in urls]
    if missing:
        detail = (" | ".join(page_errors[:2]) + " | ") if page_errors else ""
        raise RuntimeError(
            f"G{group}: faltan URLs de {len(missing)} de {len(official)} equipos. "
            + detail + "Faltan: " + ", ".join(missing)
        )
    if page_errors:
        warnings.append(
            f"G{group}: la página índice de equipos no respondió; se usaron slugs verificados de BeSoccer."
        )

    aggregated: dict[tuple[int, str, str], Match] = {}
    failed: list[str] = []

    for team in official:
        url = urls[team]
        try:
            team_soup = fetch(url)
        except Exception as exc:
            failed.append(f"{team}: {exc}")
            continue

        parsed = parse_matches(team_soup, url)
        for m in parsed:
            if not m.es_primera_federacion or not m.jornada or not (1 <= m.jornada <= 38):
                continue
            if not _in_season(m.fecha):
                continue

            local = _official_team_name(m.local, official)
            visitante = _official_team_name(m.visitante, official)
            if not local or not visitante:
                continue

            # Reescribimos ya a nombres canónicos para deduplicar.
            m.local = local
            m.visitante = visitante
            key = (m.jornada, local, visitante)
            aggregated[key] = _merge_match(aggregated.get(key), m)

    if failed:
        raise RuntimeError(
            f"G{group}: scrapeo incompleto; fallaron {len(failed)} páginas de equipo: " + " | ".join(failed[:5])
        )

    by_round: dict[int, list[Match]] = {}
    for (jornada, _, _), m in aggregated.items():
        by_round.setdefault(jornada, []).append(m)

    coverage: dict[int, dict[str, int]] = {}
    for jornada in range(1, 39):
        matches = by_round.get(jornada, [])
        coverage[jornada] = {
            "detectados": len(matches),
            "con_hora": sum(bool(m.hora) for m in matches),
            "con_resultado": sum(bool(m.resultado) for m in matches),
        }
        if not matches:
            continue
        changed, _ = apply_matches(data, group, jornada, matches, mode)
        if changed:
            changed_rounds.append(jornada)

    # Control de integridad fuerte: las páginas de los 20 equipos muestran el
    # calendario completo de liga. Por tanto, cada una de las 38 jornadas debe
    # producir exactamente 10 cruces únicos. Si no ocurre, abortamos para no
    # volver a guardar un JSON aparentemente correcto pero incompleto.
    bad_rounds = [j for j, c in coverage.items() if c["detectados"] != 10]
    if bad_rounds:
        raise RuntimeError(
            f"G{group}: cobertura incompleta de BeSoccer. Se esperaban 10 partidos por jornada; "
            + ", ".join(f"J{j}={coverage[j]['detectados']}" for j in bad_rounds[:12])
            + (" ..." if len(bad_rounds) > 12 else "")
        )

    return sorted(set(changed_rounds)), warnings, coverage
