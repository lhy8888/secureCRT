"""Record build distributions and copy their license/notice files into a bundle."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sys


def collect(output):
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        folder = output/re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        item = dict(name=name, version=distribution.version,
                    license_expression=distribution.metadata.get('License-Expression'), files=[])
        for index, entry in enumerate(distribution.files or []):
            text = str(entry).lower()
            if not any(part in text for part in ('license', 'licence', 'copying', 'notice')): continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file() or source.stat().st_size > 5*1024*1024: continue
            folder.mkdir(exist_ok=True)
            target = folder/(str(index)+'-'+re.sub(r'[^A-Za-z0-9_.-]', '_', source.name))
            shutil.copyfile(source, target)
            item['files'].append(dict(path=str(target.relative_to(output)),
                                      sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
        packages.append(item)
    for name in ('LICENSE.txt','LICENSE'):
        source = Path(sys.base_prefix)/name
        if source.is_file(): shutil.copyfile(source, output/('Python-'+name))
    (output/'build-environment.json').write_text(json.dumps(dict(
        scope='Installed build distributions; not an exhaustive bundled-binary SBOM',
        python=sys.version, packages=packages), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    collect(parser.parse_args().out)
