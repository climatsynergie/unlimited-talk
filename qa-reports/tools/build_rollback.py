"""Rebuild actual662 source with cached identical pinned dependencies (QA only)."""
from pathlib import Path
import subprocess,tarfile,io,shutil,hashlib
root=Path(__file__).resolve().parents[2];rev='662b450501a70431b0effbb087501e727111099d';folder=Path('/tmp/ut-full-qa-rollback');folder.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['git','archive',rev],cwd=root))) as archive:archive.extractall(folder,filter='data')
base_lock=subprocess.check_output(['sudo','-n','docker','run','--rm','--network','none','--entrypoint','cat','unlimited-talk-qa-api:work','/app/requirements.lock'])
assert base_lock==(folder/'backend/requirements.lock').read_bytes(),'Cached dependency lock must match actual preceding release'
(folder/'frontend/node_modules').symlink_to(root/'frontend/node_modules',target_is_directory=True)
subprocess.run(['npm','run','build'],cwd=folder/'frontend',check=True)
shutil.copytree(folder/'frontend/dist',folder/'web',dirs_exist_ok=True)
(folder/'Dockerfile.qa').write_text(f'''FROM unlimited-talk-qa-api:work
ENV APP_REVISION={rev}
LABEL org.opencontainers.image.revision="{rev}"
USER root
COPY backend/ /app/
COPY web/ /app/web/
USER 10001:10001
''')
subprocess.run(['sudo','-n','docker','build','-f',str(folder/'Dockerfile.qa'),'-t','unlimited-talk-qa-audit:rollback-662',str(folder)],check=True)
print('Actual git archive662 runtime and dependency-lock equality verified; QA-only incremental rollback image built.')
