"""Create a verified static deployment bundle; never uploads or publishes."""
import argparse, json, os, shutil, tempfile
from pathlib import Path
from .core import ROOT, verify_release

def export(destination):
    source=(ROOT/'current').resolve(); a=verify_release(source)
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('Choose a new export directory; existing output is never overwritten')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.export-',dir=destination.parent))
    try:
        # Both paths serve the same verified bytes. The existing site uses /report/.
        for prefix in (staging,staging/'report'):
            prefix.mkdir(exist_ok=True)
            for item in source.iterdir():
                if item.is_file(): shutil.copyfile(item,prefix/item.name)
            verify_release(prefix)
        os.replace(staging,destination)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return {'directory':str(destination),'release_id':a['release_id'],'published':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('destination'); args=p.parse_args()
    print(json.dumps(export(args.destination),indent=2))
