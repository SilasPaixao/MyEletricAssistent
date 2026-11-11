"""GitHub Releases updater for public repositories and Windows one-file builds."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

import httpx

from .update_config import APP_VERSION, GITHUB_REPOSITORY
ASSET_NAME = 'MyEletricAssistent.exe'


def is_configured():
    return bool(GITHUB_REPOSITORY and '/' in GITHUB_REPOSITORY)


def parse_version(value):
    parts = value.removeprefix('v').split('.')
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f'Versão inválida: {value}')
    return tuple(map(int, parts))


def check_latest(repository=None, current_version=APP_VERSION):
    repo = repository or GITHUB_REPOSITORY
    if not repo or '/' not in repo or any(x not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/' for x in repo):
        raise ValueError('Configure MYEA_GITHUB_REPOSITORY como usuario/repositorio')
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        response = client.get(f'https://api.github.com/repos/{repo}/releases/latest',
                              headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'MyEletricAssistent-updater'})
        response.raise_for_status()
        release = response.json()
    version = release['tag_name'].removeprefix('v')
    if parse_version(version) <= parse_version(current_version):
        return None
    asset = next((a for a in release.get('assets', []) if a.get('name') == ASSET_NAME), None)
    if not asset:
        raise ValueError('Release não contém MyEletricAssistent.exe')
    url = asset['browser_download_url']
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('github.com', 'objects.githubusercontent.com'):
        raise ValueError('URL de download não confiável')
    digest = asset.get('digest') or ''
    if not digest.startswith('sha256:') or len(digest) != 71:
        raise ValueError('Release sem SHA-256 do arquivo; atualização recusada')
    return {'version': version, 'url': url, 'sha256': digest[7:], 'notes': release.get('body', '')}


def download_verified(update, progress=None):
    """Download into a temporary file, then validate SHA-256 before returning path."""
    target = Path(tempfile.mkdtemp(prefix='myea-update-')) / ASSET_NAME
    expected = update['sha256'].lower()
    digest = hashlib.sha256()
    try:
        with httpx.Client(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client:
            with client.stream('GET', update['url'], headers={'User-Agent': 'MyEletricAssistent-updater'}) as response:
                response.raise_for_status()
                total = int(response.headers.get('content-length') or 0)
                received = 0
                with target.open('wb') as file:
                    for chunk in response.iter_bytes(chunk_size=1024 * 256):
                        file.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if progress and total:
                            progress(min(100, int(received * 100 / total)))
        if digest.hexdigest().lower() != expected:
            raise ValueError('SHA-256 não confere: download descartado')
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


# A separate process waits until Windows releases the running executable.
_UPDATE_SCRIPT = r'''param([int]$OldPid, [string]$CurrentExe, [string]$NewExe)
$ErrorActionPreference = 'Stop'
try {
    Wait-Process -Id $OldPid -Timeout 60 -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
    $backup = "$CurrentExe.previous"
    Copy-Item -LiteralPath $CurrentExe -Destination $backup -Force
    try {
        Copy-Item -LiteralPath $NewExe -Destination $CurrentExe -Force
    } catch {
        Copy-Item -LiteralPath $backup -Destination $CurrentExe -Force
        throw
    }
    Start-Process -FilePath $CurrentExe
} catch {
    $log = Join-Path $env:TEMP 'MyEletricAssistent-update-error.log'
    $_ | Out-String | Out-File -FilePath $log -Encoding utf8 -Append
}
'''


def launch_replacement(downloaded):
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Substituição disponível apenas no executável Windows')
    current = Path(sys.executable).resolve()
    downloaded = Path(downloaded).resolve()
    if not downloaded.is_file():
        raise FileNotFoundError(downloaded)
    script = downloaded.parent / 'replace.ps1'
    script.write_text(_UPDATE_SCRIPT, encoding='utf-8-sig')
    creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
    subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                      '-OldPid', str(os.getpid()), '-CurrentExe', str(current), '-NewExe', str(downloaded)],
                     creationflags=creationflags, close_fds=True)
