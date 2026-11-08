"""Build the QA-only incremental image; preserve pinned dependency base."""
import pathlib,shutil,subprocess,os
root=pathlib.Path(__file__).resolve().parents[2]
subprocess.run(['npm','run','build'],cwd=root/'frontend',check=True)
folder=pathlib.Path('/tmp/ut-full-qa-fixed');folder.mkdir(exist_ok=True)
shutil.copytree(root/'backend',folder/'backend',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(root/'frontend/dist',folder/'web',dirs_exist_ok=True)
(folder/'qa-coverage.pth').write_text('import os; exec("import sys; sys.path.append(\'/qa-tools\'); import coverage; coverage.process_startup()" if os.environ.get("COVERAGE_PROCESS_START") else "")\n')
(folder/'Dockerfile.qa').write_text('''FROM unlimited-talk-qa-api:work
ENV APP_REVISION=qa-audit-fixed-96f5055
LABEL org.opencontainers.image.revision="qa-audit-fixed-96f5055" io.unlimitedtalk.schema="0012_incoming_runtime"
USER root
COPY backend/ /app/
COPY web/ /app/web/
COPY qa-coverage.pth /usr/local/lib/python3.12/site-packages/ut_qa_coverage.pth
USER 10001:10001
''')
subprocess.run(['sudo','-n','docker','build','-f',str(folder/'Dockerfile.qa'),'-t',os.environ.get('QA_BUILD_IMAGE','unlimited-talk-qa-audit:fixed'),str(folder)],check=True)
