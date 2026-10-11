"""Fetch a pinned official npm distribution and verify its published integrity."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

VERSION='1.146.0'
INTEGRITY='hvKkURnmc8OZ8qKNrwawl/YijwAItaWLbpAdIVNAUXODCLMjpod4PbdLuwo8Ab6ETL915MUGV2NocHFCRCeqqA=='
URL=f'https://registry.npmjs.org/cesium/-/cesium-{VERSION}.tgz'
root=Path(__file__).resolve().parents[1]/'assets/satellite/vendor/cesium'
data=urllib.request.urlopen(URL,timeout=60).read()
if base64.b64encode(hashlib.sha512(data).digest()).decode()!=INTEGRITY:
    raise ValueError('Cesium distribution integrity check failed')
root.mkdir(parents=True,exist_ok=True)
count=0
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
    for member in archive.getmembers():
        prefix='package/Build/Cesium/'
        if member.isfile() and (member.name.startswith(prefix) or member.name in ('package/LICENSE.md','package/ThirdParty.json')):
            relative=member.name[len(prefix):] if member.name.startswith(prefix) else member.name.split('/')[-1]
            target=(root/relative).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError('Invalid distribution path')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.extractfile(member).read());count+=1
(root/'provenance.json').write_text(json.dumps(dict(package='cesium',version=VERSION,url=URL,
    integrity='sha512-'+INTEGRITY,files=count),indent=2),encoding='utf-8')
print(f'Cesium {VERSION}: {count} verified files, {len(data):,} archive bytes')
