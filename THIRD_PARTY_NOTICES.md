# Third-party notices

yt2mp3 is a small UI around existing open-source tools. This file records the
direct dependencies and the main licensing points for a public source release.

| Component | License | Project |
| --- | --- | --- |
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| Flask | BSD-3-Clause | https://github.com/pallets/flask |
| imageio-ffmpeg | BSD-2-Clause | https://github.com/imageio/imageio-ffmpeg |
| Waitress | ZPL-2.1 | https://github.com/Pylons/waitress |
| FFmpeg | GPLv3 for the bundled build | https://ffmpeg.org/legal.html |
| mutagen (yt-dlp default extra) | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| pycryptodomex (yt-dlp default extra) | BSD-2-Clause / public domain | https://github.com/Legrandin/pycryptodome |
| requests (yt-dlp default extra) | Apache-2.0 | https://github.com/psf/requests |
| urllib3 (yt-dlp default extra) | MIT | https://github.com/urllib3/urllib3 |
| websockets (yt-dlp default extra) | BSD-3-Clause | https://github.com/python-websockets/websockets |
| brotli (yt-dlp default extra) | MIT | https://github.com/google/brotli |
| certifi (yt-dlp default extra) | MPL-2.0 | https://github.com/certifi/python-certifi |
| yt-dlp-ejs (yt-dlp default extra) | Unlicense / MIT / ISC | https://github.com/yt-dlp/yt-dlp-ejs |

`requests` also brings `charset-normalizer` (MIT) and `idna` (BSD-3-Clause).

## FFmpeg note

The source repository does **not** contain an FFmpeg binary. The
`imageio-ffmpeg` Python package downloads or bundles an FFmpeg executable for
the current platform when it is installed. If you publish a packaged `.exe`,
Docker image, or other binary distribution that includes FFmpeg, review the
license of that specific FFmpeg build and provide the corresponding notices and
source offer where required. The build used during development reports
`libmp3lame` support, which is typically associated with a GPL-enabled build.

## YouTube

yt2mp3 is not affiliated with YouTube or Google. Downloading content may
violate YouTube's Terms of Service and copyright law. The repository contains
no downloaded media.
