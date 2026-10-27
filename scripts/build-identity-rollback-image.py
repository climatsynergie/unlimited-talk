"""Build the reviewed preceding compatibility release for real rollback tests."""
from pathlib import Path
import subprocess
import tarfile
import tempfile
import io

revision = '911177b3181d849115fa5cedd00dd4a21cfcda60'
root = Path(__file__).resolve().parents[1]
if subprocess.run(['git','cat-file','-e',revision+'^{commit}'],cwd=root,capture_output=True).returncode:
    subprocess.run(['git','fetch','--depth=1','origin',revision],cwd=root,check=True)
archive = subprocess.check_output(['git','archive',revision],cwd=root)
with tempfile.TemporaryDirectory(prefix='identity-rollback-image-') as tmp:
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(tmp,filter='data')
    subprocess.run(['sudo','-n','docker','build','--build-arg','GIT_REVISION='+revision,
                    '-t','unlimited-talk-staging-api:identity-rollback',tmp],check=True)
