"""Domain and API integration for MyEletricAssistent."""
from __future__ import annotations
import csv
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import httpx

REF_RE = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp'}

class MyEAError(Exception):
    pass

@dataclass
class DemandEntry:
    reference: str
    photos: list[Path]
    remote: dict[str, Any] = field(default_factory=dict)
    team: str = ''
    selected: bool = True
    error: str = ''
    result: str = 'Aguardando'


def load_entries(json_path: Path, media_root: Path) -> list[DemandEntry]:
    content = json.loads(json_path.read_text(encoding='utf-8-sig'))
    items = content.get('demandas', content.get('demands', [])) if isinstance(content, dict) else content
    if not isinstance(items, list):
        raise MyEAError('JSON deve conter uma lista de demandas')
    entries, seen = [], set()
    base = media_root.resolve()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise MyEAError(f'Demanda {index}: objeto inválido')
        ref = item.get('id_referencia') or item.get('idReferencia')
        if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
            raise MyEAError(f'Demanda {index}: id_referencia ausente/inválido')
        if ref in seen:
            raise MyEAError(f'ID duplicado no JSON: {ref}')
        seen.add(ref)
        names = item.get('fotos', [])
        if not isinstance(names, list):
            raise MyEAError(f'{ref}: fotos deve ser lista')
        paths = []
        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise MyEAError(f'{ref}: caminho de foto inválido')
            path = (base / name).resolve()
            if not path.is_relative_to(base):
                raise MyEAError(f'{ref}: foto fora da pasta permitida')
            paths.append(path)
        entries.append(DemandEntry(ref, paths))
    return entries


def validate_photo(entry: DemandEntry) -> None:
    if not entry.photos:
        raise MyEAError('Foto principal ausente')
    for photo in entry.photos:
        if not photo.is_file():
            raise MyEAError(f'Fotografia não encontrada: {photo.name}')
        if photo.suffix.lower() not in ALLOWED_EXT:
            raise MyEAError(f'Formato de fotografia inválido: {photo.name}')
        if photo.stat().st_size > 10 * 1024 * 1024:
            raise MyEAError(f'Fotografia acima de 10 MB: {photo.name}')
        if photo.stat().st_size == 0:
            raise MyEAError(f'Fotografia vazia: {photo.name}')


def planned_to_used(demand: dict) -> list[dict]:
    result = []
    for item in demand.get('plannedMaterials', []):
        material_id = item.get('materialId')
        qty = item.get('quantity')
        if not material_id or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise MyEAError('Material planejado inválido')
        result.append({'materialId': material_id, 'quantity': qty})
    if len({x['materialId'] for x in result}) != len(result):
        raise MyEAError('Material planejado duplicado')
    return result

class API:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/') + '/api'
        self.client = httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False)
        self.user: dict = {}

    def close(self):
        self.client.close()

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.client.request(method, self.base_url + path, **kwargs)
            if response.status_code >= 400:
                try: message = response.json().get('error', response.text[:250])
                except ValueError: message = response.text[:250]
                raise MyEAError(f'HTTP {response.status_code}: {message}')
            return response.json()
        except httpx.HTTPError as exc:
            raise MyEAError(f'Falha de conexão: {exc}') from exc

    def login(self, username: str, password: str):
        data = self._request('POST', '/auth/login', json={'username': username, 'password': password})
        if data.get('user', {}).get('role') != 'ADMIN':
            raise MyEAError('Somente administradores podem utilizar a automação')
        self.client.headers['Authorization'] = f"Bearer {data['token']}"
        self.user = data['user']

    def electricians(self) -> list[dict]:
        return [u for u in self._request('GET', '/users') if u.get('role') == 'ELECTRICIAN' and u.get('status') == 'APPROVED']

    def vehicles(self) -> list[dict]:
        return self._request('GET', '/vehicles')

    def demand(self, reference: str) -> dict:
        return self._request('GET', f'/demands/by-reference/{reference}')

    def finish(self, entry: DemandEntry, vehicle_id: str, returned: list[dict] | None = None):
        validate_photo(entry)
        demand = self.demand(entry.reference)  # fresh status and materials immediately before POST
        if demand.get('status') != 'PENDING':
            raise MyEAError(f"Status não permite baixa: {demand.get('status')}")
        materials = planned_to_used(demand)
        fields = {
            'usedMaterials': json.dumps(materials),
            'replacedMaterials': json.dumps(returned or []),
            'vehicles': vehicle_id,
            'tools': '', 'transformerNumber': '', 'observation': ''
        }
        from contextlib import ExitStack
        with ExitStack() as stack:
            files = []
            for index, photo in enumerate(entry.photos):
                f = stack.enter_context(photo.open('rb'))
                files.append(('photo' if index == 0 else f'extra_photo_{index-1}', (photo.name, f, mimetypes.guess_type(photo.name)[0] or 'application/octet-stream')))
            try:
                return self._request('POST', f"/demands/{demand['id']}/finish", data=fields, files=files, headers={'X-MyEA-Automation': '1'})
            except MyEAError as exc:
                # Network timeouts can occur after a successful server-side write.
                try:
                    latest = self.demand(entry.reference)
                    if latest.get('status') == 'PENDING_APPROVAL':
                        raise MyEAError('Estado remoto pendente de aprovação após erro de comunicação; verificar manualmente antes de repetir') from exc
                except MyEAError as verify_exc:
                    if 'Estado remoto pendente' in str(verify_exc):
                        raise
                raise


def save_report(entries: list[DemandEntry], path: Path):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['Referência', 'Equipe', 'Resultado', 'Erro'])
        for e in entries:
            writer.writerow([e.reference, e.team, e.result, e.error])
