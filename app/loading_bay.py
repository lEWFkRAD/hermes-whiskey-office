"""Persistent personal file shelf. Explicit copies and optimistic return checks.

No network listener, file execution, ambient sync, remote commands or deletion.
Agents may invoke this CLI over their existing authenticated SSH connection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

MACHINES = ('forge', 'shatner', 'onyx')
LIMIT = 1024 * 1024 * 1024

def default_root():
    return Path(os.environ.get('HERMES_OFFICE_DATA_DIR', str(Path.home()/'.local/share/hermes-whiskey-office')))/'loading-bay'

def safe_name(name):
    return re.sub(r'[^A-Za-z0-9._ -]', '_', name)[:120].strip(' .') or 'artifact'

def plain(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in [path,*path.parents]):
        raise ValueError('Symbolic links are not accepted in the loading bay')
    return path

class Bay:
    def __init__(self, root=None):
        self.root=plain(root or default_root())
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        for name in ['Inbox','Shelf','Work','objects','pending']:
            plain(self.root/name).mkdir(exist_ok=True,mode=0o700)
        for machine in MACHINES:plain(self.root/'Work'/machine).mkdir(exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(plain(self.root/'catalog.sqlite3'),timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,name TEXT,head TEXT);
          CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,artifact TEXT,parent TEXT,hash TEXT,origin TEXT,created REAL,conflict INTEGER);
          CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY,artifact TEXT,base TEXT,machine TEXT,path TEXT,closed INTEGER DEFAULT 0);
        ''')
        self.db.row_factory=sqlite3.Row
    def close(self):self.db.close()
    def rows(self):
        return [dict(r) for r in self.db.execute('SELECT a.*,r.origin,r.created FROM artifacts a JOIN revisions r ON r.id=a.head ORDER BY r.created DESC')]
    def store(self, source):
        source=plain(source)
        before=source.stat()
        if not source.is_file() or before.st_size>LIMIT:raise ValueError('Choose a regular file up to 1 GiB')
        fd,temp=tempfile.mkstemp(dir=self.root/'pending')
        try:
            h=hashlib.sha256();size=0
            with source.open('rb') as inp,os.fdopen(fd,'wb') as out:
                while block:=inp.read(1024*1024):
                    size+=len(block)
                    if size>LIMIT:raise ValueError('File exceeds 1 GiB')
                    h.update(block);out.write(block)
                out.flush();os.fsync(out.fileno())
            after=source.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                raise ValueError('File changed during capture; retry after its writer finishes')
            sha=h.hexdigest();target=plain(self.root/'objects'/sha)
            # Exclusive publication; another writer can publish identical bytes.
            try:os.link(temp,target)
            except FileExistsError:
                if self.hash(target)!=sha:raise ValueError('Existing object failed integrity verification')
            Path(temp).unlink()
            target.chmod(0o444)
            return sha
        finally:Path(temp).unlink(missing_ok=True)
    @staticmethod
    def hash(path):
        h=hashlib.sha256()
        with plain(path).open('rb') as stream:
            while block:=stream.read(1024*1024):h.update(block)
        return h.hexdigest()
    def snapshot(self, revision, name, sha):
        source=plain(self.root/'objects'/sha)
        if self.hash(source)!=sha:raise ValueError('Stored revision failed integrity verification')
        target=plain(self.root/'Shelf'/(revision+' -- '+safe_name(name)))
        if not target.exists():
            # A copy rather than a hard link prevents a file manager edit corrupting the object store.
            with target.open('xb') as out,source.open('rb') as inp:shutil.copyfileobj(inp,out)
            target.chmod(0o444)
        return str(target)
    def put(self, source, origin='forge'):
        if origin not in MACHINES:raise ValueError('Unknown machine')
        sha=self.store(source);artifact=uuid.uuid4().hex;revision=uuid.uuid4().hex
        name=Path(source).name
        with self.db:
            self.db.execute('INSERT INTO artifacts VALUES(?,?,?)',(artifact,name,revision))
            self.db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',(revision,artifact,None,sha,origin,time.time(),0))
        self.snapshot(revision,name,sha)
        return dict(artifact=artifact,revision=revision,sha256=sha,name=name)
    def checkout(self, artifact, machine):
        if machine not in MACHINES:raise ValueError('Unknown machine')
        row=self.db.execute('SELECT a.name,a.head,r.hash FROM artifacts a JOIN revisions r ON r.id=a.head WHERE a.id=?',(artifact,)).fetchone()
        if row is None:raise ValueError('Unknown artifact')
        if self.hash(self.root/'objects'/row['hash'])!=row['hash']:raise ValueError('Stored revision failed integrity verification')
        lease=uuid.uuid4().hex;folder=plain(self.root/'Work'/machine/lease);folder.mkdir()
        target=folder/safe_name(row['name'])
        shutil.copyfile(self.root/'objects'/row['hash'],target)
        with self.db:self.db.execute('INSERT INTO leases(id,artifact,base,machine,path) VALUES(?,?,?,?,?)',(lease,artifact,row['head'],machine,str(target)))
        return dict(lease=lease,artifact=artifact,base=row['head'],machine=machine,path=str(target))
    def working(self, lease):
        row=self.db.execute('SELECT * FROM leases WHERE id=?',(lease,)).fetchone()
        if row is None or row['closed']:raise ValueError('Unknown or already returned working copy')
        return dict(row)
    def put_back(self, lease, source=None):
        row=self.db.execute('SELECT * FROM leases WHERE id=?',(lease,)).fetchone()
        if row is None or row['closed']:raise ValueError('Unknown or already returned working copy')
        sha=self.store(source or row['path']);revision=uuid.uuid4().hex
        # Serialize the compare-and-swap, so simultaneous returns cannot lose an edit.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            current=self.db.execute('SELECT * FROM leases WHERE id=?',(lease,)).fetchone()
            if current['closed']:raise ValueError('Working copy already returned')
            artifact=self.db.execute('SELECT * FROM artifacts WHERE id=?',(row['artifact'],)).fetchone()
            conflict=artifact['head']!=row['base']
            self.db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?)',(revision,row['artifact'],row['base'],sha,row['machine'],time.time(),int(conflict)))
            if not conflict:self.db.execute('UPDATE artifacts SET head=? WHERE id=?',(revision,row['artifact']))
            self.db.execute('UPDATE leases SET closed=1 WHERE id=?',(lease,));self.db.commit()
        except BaseException:self.db.rollback();raise
        path=self.snapshot(revision,artifact['name'],sha)
        return dict(revision=revision,conflict=conflict,head_advanced=not conflict,path=path,sha256=sha)
    def history(self, artifact):
        return [dict(r) for r in self.db.execute('SELECT * FROM revisions WHERE artifact=? ORDER BY created',(artifact,))]
    def keep_inbox(self):
        # Explicit capture only. Never remove or rename a user's inbox files.
        rows=[]
        for path in sorted((self.root/'Inbox').iterdir()):
            if path.is_file() and not path.is_symlink():
                rows.append(self.put(path))
        return rows

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ['init','list','keep-inbox']:sub.add_parser(action)
    p=sub.add_parser('put');p.add_argument('path',type=Path);p.add_argument('--origin',choices=MACHINES,default='forge')
    p=sub.add_parser('checkout');p.add_argument('artifact');p.add_argument('machine',choices=MACHINES)
    p=sub.add_parser('return');p.add_argument('lease');p.add_argument('--source',type=Path)
    p=sub.add_parser('working');p.add_argument('lease')
    p=sub.add_parser('history');p.add_argument('artifact')
    args=parser.parse_args();bay=Bay(args.root)
    try:
        if args.action=='init':result={'root':str(bay.root),'machines':MACHINES}
        elif args.action=='list':result=bay.rows()
        elif args.action=='put':result=bay.put(args.path,args.origin)
        elif args.action=='checkout':result=bay.checkout(args.artifact,args.machine)
        elif args.action=='return':result=bay.put_back(args.lease,args.source)
        elif args.action=='working':result=bay.working(args.lease)
        elif args.action=='history':result=bay.history(args.artifact)
        else:result=bay.keep_inbox()
        print(json.dumps(result))
    finally:bay.close()

if __name__=='__main__':main()
