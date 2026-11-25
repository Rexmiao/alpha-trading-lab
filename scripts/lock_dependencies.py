"""Pin installed versions of this project's dependency closure, without env/secrets."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.markers import default_environment

root = Path(__file__).resolve().parents[1]
pending = [Requirement(line.strip()).name for line in (root/'requirements.txt').read_text().splitlines()
           if line.strip() and not line.startswith('#')]
resolved = {}
environment = {**default_environment(), 'extra': ''}
while pending:
    name = pending.pop()
    package = distribution(name)
    canonical = package.metadata['Name']
    key = canonical.lower().replace('_', '-')
    if key in resolved:
        continue
    resolved[key] = f'{canonical}=={package.version}'
    for requirement in package.requires or []:
        parsed = Requirement(requirement)
        if parsed.marker is None or parsed.marker.evaluate(environment):
            pending.append(parsed.name)
header = '# Tested installed dependency closure; Windows + Python 3.12.7.\n# Regenerate: python scripts/lock_dependencies.py\n'
(root/'requirements-lock.txt').write_text(header+'\n'.join(resolved[key] for key in sorted(resolved))+'\n', encoding='utf8')
print(f'Locked {len(resolved)} installed distributions; no environment variable values recorded.')
