from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.request import pathname2url
from urllib.request import url2pathname
import os
import subprocess


def filename_to_uri(path: str) -> str:
    # wslpath command doesn't handle unix-side paths correctly (always adds /mnt/c)
    wsl_path = '/' + '/'.join(path.split('\\')[4:])
    return urljoin('file:', pathname2url(wsl_path))


def uri_to_filename(uri: str) -> str:
    if os.name == 'nt':
        # url2pathname does not understand %3A (VS Code's encoding forced on all servers :/)
        wsl_path = '/' + url2pathname(urlparse(uri).path).strip('\\').replace('\\', '/')
        return subprocess.check_output(["wsl", "wslpath", "-w", wsl_path], universal_newlines=True, shell=True)[:-1]
    else:
        return url2pathname(urlparse(uri).path)
