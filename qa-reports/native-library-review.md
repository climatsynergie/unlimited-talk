# Native-library review — 2026-11-09

**The native dependency gate is not fully cleared.** Refreshed official images fix several affected APK versions, and the maintained Nginx slim variant removes unnecessary codec/client/XML packages. However, the new official Python base still statically bundles affected Expat 2.9.0. The installed Psycopg binary wheel also carries its own older OpenSSL. Neither issue is repaired by upgrading Alpine packages alone.

No production changes, provider calls, exploit traffic, deployment or merge was performed for this review. Candidate registry inventories are evidence of package contents; they are not substitutes for the rebuilt-application CI results, recorded separately.

## Refreshed evidence and exact fix versions

Thirty-three primary vendor/distribution documents were retrieved successfully on **2026-11-09 19:41 UTC**. URLs, UTC timestamps, hashes and response metadata are in [the evidence index](evidence/native-refresh/primary-index.json). The historical audit evidence remains intact.

| Component / advisory | Exact fixed version relevant here | Assessment |
|---|---|---|
| musl, CVE-2026-107891; CNA CVSS 3.1 HIGH 8.1 | Alpine 3.24: **1.2.6-r3**; Alpine 3.22: **1.2.5-r13**. Upstream recommends its patch or 1.2.7. | Fresh candidates contain the Alpine backport. The trigger is an untrusted *pattern* passed to libc `regcomp`, not arbitrary text matched by Python `re`. No such application path was identified; this does not replace the package fix. |
| zlib, CVE-2026-85091; CNA HIGH | Alpine **1.3.2-r1**; upstream **1.4** | Fresh candidates contain r1. The advisory concerns the gzip write-buffer path, not every inflate/deflate operation. |
| zlib-origin CVE-2026-4738; CNA CRITICAL 9.4 | Alpine **1.4-r0**, available in the supported 3.24 **and** 3.22 main repositories | Fresh image snapshots still contain 1.3.2-r1, so Alpine's origin-based scan still reports this range. The CVE concerns GDAL's bundled `contrib/infback9/inftree9.c`. See the narrowly scoped component evidence below. |
| Brotli, CVE-2026-111497; Google CNA CRITICAL 9.2, Node vendor HIGH | Alpine **1.2.1-r0**, upstream **1.2.1** for the affected 1.2 branch | Fresh full gateway has the fixed package; fresh slim gateway has no Brotli APK. Trigger requires decoding attacker-controlled Brotli. Node's patched backport must be assessed by Node release/patch, not solely its Brotli version string. |
| curl/libcurl, CVE-2026-92392; vendor HIGH | Alpine 3.24 **8.23.0-r0**, upstream **8.23.0**; maintained 3.22 backport **8.14.1-r4** | Fresh full gateway/libcurl candidates are patched; slim has no curl/libcurl APK. Trigger is the HTTP/2 upload retry/use-after-free path. No reviewed application curl HTTP/2 upload path was found. |
| Expat, CVE-2026-113351 / 115506 / 117610 / 118370 | Alpine **2.10.0-r0**, upstream **2.10.0** | Fresh full gateway patches its APK; slim has no Expat APK. **Python's separate embedded copy remains affected.** CNA CVSS 4 scores are HIGH 8.2/8.7/8.2/8.2; CVSS 3.1 scores differ and are retained in the source records. |

Primary sources: [Alpine 3.24 security database](https://secdb.alpinelinux.org/v3.24/main.json), [Alpine 3.22 security database](https://secdb.alpinelinux.org/v3.22/main.json), [musl maintainer advisory](https://www.openwall.com/lists/musl/2026/10/21/1), [zlib 1.4 changelog](https://github.com/madler/zlib/blob/v1.4/ChangeLog), [Google Brotli release](https://github.com/google/brotli/releases/tag/v1.2.1), [curl advisory](https://curl.se/docs/CVE-2026-92392.html), [Expat maintainer announcement](https://www.openwall.com/lists/oss-security/2026/11/02/6).

The prior curl discrepancy remains explicit: curl's 8.22 vendor table lists **21** affected issues, including one HIGH. Alpine's grouped 8.23 security-fix entry lists 24 identifiers, three of which the vendor already considers fixed in 8.22. Do not report all 24 as independently confirmed vulnerabilities in 8.22. [Vendor affected-version table](https://curl.se/docs/vuln-8.22.0.html).

## Maintained official image choices

The upstream Nginx project documents a registry migration: stable **1.30.6 and later** use **`nginx/nginx-unprivileged`** on Docker Hub; the old `nginxinc` namespace is for preceding releases. Its [README](https://github.com/nginx/docker-nginx-unprivileged) and captured [Dockerfiles](evidence/native-refresh/nginx-alpine-slim.Dockerfile) establish the supported non-root layout: port 8080, UID 101 by default, and PID/temporary files under `/tmp`.

| Actual inspected candidate | Alpine / APK count | Relevant contents |
|---|---|---|
| Python 3.12-Alpine, index `e064671c…` | 3.24.4 / 38 | musl 1.2.6-r3; zlib 1.3.2-r1. No Expat APK does **not** mean Python has no Expat. |
| New-namespace Nginx stable-alpine-slim, index `e333a5b9…` | 3.24.4 / 21 | nginx 1.30.6-r1; patched musl/zlib r1; no curl/libcurl, Brotli, Expat or nghttp2 APKs. |
| New-namespace full Nginx, index `c3fc8fa4…` | 3.24.4 / 70 | Adds optional XSLT/image/GeoIP/njs modules and curl; Brotli 1.2.1, curl 8.23, Expat 2.10. |
| Old-namespace full/slim | 3.24.2 / 70 or 21 | Remain on musl r2 and zlib r0. Merely selecting the old namespace's slim tag would retain those findings. |
| Redis 8.2 candidate, index `fe9daae3…` | 3.22.8 / 22 | musl 1.2.5-r13; zlib 1.3.2-r1. |
| PostgreSQL 18 candidate, index `123b1799…` | 3.24.4 / 53 | Patched musl/zlib r1 and libcurl 8.23. This is the **local QA database image**, not evidence about DigitalOcean managed PostgreSQL internals. |

Full digests, manifests and SHA-256-verified layer inventories are in [inventories.json](evidence/native-refresh/inventories.json). Independent APK-version comparisons against current Alpine security records are in [apk-advisories.json](evidence/native-refresh/apk-advisories.json). Each fresh candidate's remaining APK-origin match is the zlib 4738 range; this says nothing about unscanned embedded components.

The slim variant fits the reviewed gateway's core HTTP reverse-proxy/rate/body-limit configuration; no application image-filter/XSLT/GeoIP/njs usage was found. Fresh QA-source405dc5a functional CI passed the actual ingress, browser and integration gates after rebuilding; [execution ledger](native-refresh-validation.md). This does not close the remaining native advisories.

## zlib component scope and VEX limits

The extracted candidate `libz.so.1.3.2` has SHA-256 **`ecc8b9dfc45eb7fa29b410ffaca6257873890de53b80fe91735737b49067c5f2`**. ELF inspection finds normal `inflateBack` exports and **no `inflateBack9` export**. The [upstream regular zlib build source](https://github.com/madler/zlib/blob/v1.3.2/CMakeLists.txt) excludes `contrib/infback9`; the CVE record identifies that contributed GDAL-bundled code. Evidence: [ELF observations](evidence/native-refresh/elf-component-review.json), [fresh CNA record](evidence/native-refresh/CVE-2026-4738.json).

This supports a **candidate component/digest-scoped `vulnerable_code_not_present` justification for the inspected regular libz**, not a signed image-wide VEX and not a reason to suppress all zlib advisories. Export absence alone does not prove absence from every statically bundled library. Updating to supported-branch **zlib 1.4-r0** is preferable when building a maintained derivative and removes the origin-range match directly; its availability is independently recorded in [supported package versions](evidence/native-refresh/supported-branch-package-versions.json). No such upgrade is claimed executed by this review.

## Confirmed embedded-runtime residuals

**Vendored Expat remains BLOCKED.** The cached application executes CPython **3.12.15** with Expat **2.8.5**. The newly pulled official base was executed offline and reports CPython **3.12.16** with Expat **2.9.0**; its extension depends only on musl, not system `libexpat`. Both runtime execution and the independently extracted ELF establish static vendoring. Evidence: [new-base runtime](evidence/native-refresh/current-python-base-runtime.json), [old application inventory](evidence/native-refresh/native-image-inventory.json).

Python 3.12.16 repairs the older bundled-Expat findings CVE-2026-77214/102633 and adds the compromised-CA protection described in the [official Python release](https://www.python.org/downloads/release/python-31216/). It does **not** include the subsequent four Expat 2.10 fixes. Installing/upgrading an Expat APK cannot replace this embedded code. No application route that parses caller-supplied XML was identified: imports accept CSV; phone hooks accept bounded form data and emit XML. That is bounded source evidence, not proof of complete native non-reachability. An upstream-fixed runtime or a reproducible, tested CPython/system-Expat build is required, or a separately reviewed, narrowly scoped VEX. No speculative CPython rebuild was attempted during the pilot window.

**Psycopg's bundled OpenSSL is a separate affected component.** Actual `psycopg-binary` **3.3.6** loads libpq **18.6** but its own OpenSSL **3.5.7**. The stdlib uses system OpenSSL **3.5.9**; `cryptography` 50.0.2 embeds **4.0.3**. These are distinct copies. Vendor's [September advisory](https://openssl-library.org/news/secadv/20260929.txt) fixes the HIGH DTLS issue CVE-2026-84782 in 3.5.9, plus lower-severity issues. The application/libpq uses PostgreSQL TCP/TLS; no DTLS call path was identified. This supports further execution-path review, not a blanket clean-wheel declaration. No exploit was attempted.

The latest compatible **psycopg-binary 3.3.8** wheel was independently downloaded and verified against its published SHA; its embedded library still identifies OpenSSL **3.5.7**. A package bump would therefore **not** establish native remediation. Evidence: [wheel inventory](evidence/native-refresh/psycopg-binary-3.3.8-wheel.json), [actual loaded version](evidence/native-refresh/wheel-openssl-version.json). The [Psycopg documentation](https://www.psycopg.org/psycopg3/docs/basic/install.html) distinguishes self-contained binary wheels from system-linked local builds. A vendor rebuild or a properly tested system-libpq/`psycopg[c]` build is an update path. Bundled LDAP/Kerberos/SASL and other native wheel dependencies have not received an exhaustive independent component-advisory scan here.

**Node scope is separated from the API runtime.** The original pinned build image, executed by its immutable `fe4f6d74…` digest, actually runs **Node 22.23.4**, including the vendor's Brotli/TLS/DNS security patches; its Brotli string remains 1.1.0 because fixes were backported. The host's 22.23.3 observation must not be attributed to that image. The refreshed Node image also records 22.23.4 with newer Alpine packages. Node builds the static frontend and is absent from the final Python runtime. Evidence: [actual original pinned Node](evidence/native-refresh/original-pinned-node-runtime.json), [Node security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases).

## Executed package checks and remaining validation

The exact **64 installed Python distributions** in cached image `sha256:b372437211d7274d9de00926a04d63558f2a275a5a6425ed9a76633096030875` were inventoried offline and queried against OSV: **PASS, exit 0, 64 audited, zero matches** at **19:42 UTC**. Exact command/timestamps: [OSV execution metadata](evidence/native-refresh/native-image-osv-command.json); [raw result](evidence/native-refresh/native-image-osv.json). This covers distribution names/versions, **not** vulnerabilities identified only by embedded Expat/OpenSSL/native library versions.

Reproduction commands, from the QA repository:

```sh
python3 qa-reports/evidence/native-refresh/fetch_primary.py
python3 qa-reports/evidence/native-refresh/inventory_python_image.py unlimited-talk-qa-audit:dependency-hardened
```

Both exited **0**. Registry inspection and ELF checks are read-only; primary-source downloads are not exploit tests. The attempted refreshed application build failed locally for disk capacity, and that failed attempt is preserved. The independent clean QA build and full functional CI then **passed** on source405dc5a: [run42685739475](https://github.com/climatsynergie/unlimited-talk/actions/runs/42685739475). Publication was skipped. Its public metadata exposes step conclusions, not numeric shell exits or raw individual-test counts; the fresh log request returned403. No complete final-image native scan is claimed: actual new-base execution, verified candidate APK layers and unchanged-wheel inventory retain their stated scopes. Image-wide native clearance remains **BLOCKED**, specifically by vendored Expat and the unresolved reviewed scope of bundled wheel libraries; managed-provider internals and host patch levels remain outside these image inventories.
