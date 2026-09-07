"""Reject input-spec updates that leave CI testing an incompatible old lock."""
from pathlib import Path
import re
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]

def requirements(path, seen=None):
    seen=set() if seen is None else seen
    path=path.resolve()
    if path in seen: return
    seen.add(path)
    for line in path.read_text().splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        if line.startswith('-r '):
            yield from requirements(path.parent/line[3:].strip(),seen)
        else:
            yield Requirement(line)

def check(spec, lock):
    pins={canonicalize_name(name):version for name,version in re.findall(r'^([\w.-]+)==([^\s;\\]+)',lock.read_text(),re.M)}
    expected=list(requirements(spec))
    if not expected or not pins:raise ValueError('Empty dependency input or lock')
    for req in expected:
        version=pins.get(canonicalize_name(req.name))
        if version is None or version not in req.specifier:
            raise ValueError(f'{req} is not satisfied by {lock.name}: {version}; regenerate the hash lock')

if __name__=='__main__':
    for name in ['requirements','requirements-dev','integrations/object-studio/requirements']:
        check(ROOT/(name+'.in'),ROOT/(name+'.lock'))
    print('All direct dependency inputs agree with the locked versions.')

