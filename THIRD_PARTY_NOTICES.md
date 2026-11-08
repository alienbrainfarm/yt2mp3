# Third-party notices

yt2mp3 is a small UI around existing open-source tools. This file records the
direct dependencies and the main licensing points for a public source release.

| Component | License | Project |
| --- | --- | --- |
| yt-dlp | Unlicense | https://github.com/yt-dlp/yt-dlp |
| Flask | BSD-3-Clause | https://github.com/pallets/flask |
| imageio-ffmpeg | BSD-2-Clause | https://github.com/imageio/imageio-ffmpeg |
| Waitress | ZPL-2.1 | https://github.com/Pylons/waitress |
| FFmpeg | LGPL/GPL depending on the build | https://ffmpeg.org/legal.html |

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
