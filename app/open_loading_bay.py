"""Open the persistent bay in the user's existing GNOME Files application."""
from pathlib import Path
import os
import subprocess
from loading_bay import Bay

if __name__=='__main__':
    bay=Bay();root=bay.root;bay.close()
    hidden=root/'.hidden'
    existing=hidden.read_text().splitlines() if hidden.exists() else []
    with hidden.open('a') as stream:
        for name in ['objects','pending','catalog.sqlite3','catalog.sqlite3-shm','catalog.sqlite3-wal']:
            if name not in existing:stream.write(name+'\n')
    readme=root/'START HERE.txt'
    if not readme.exists():readme.write_text('HERMES LOADING BAY\n\nInbox: copy files here to keep them between visits.\nShelf: preserved version snapshots.\nWork: independent working copies for Forge, SHATNER and Onyx.\n\nAgent commands: loading_bay.py put PATH, list, checkout ARTIFACT MACHINE, return LEASE, history ARTIFACT.\nThe bay keeps both versions of conflicting returns. No automatic overwrite or remote sync.\n',encoding='utf-8')
    os.execv('/usr/bin/nautilus',['/usr/bin/nautilus','--new-window',str(root)])
