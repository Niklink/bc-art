# Bandcamp Art Downloader (`bc-art`)

### Installation

You'll need Python 3 to run `bc-art`. You can check if it's installed by running `python3 --version` or `python --version`. If you haven't got Python 3, you can download it from [python.org](https://www.python.org/downloads/) or your package manager.

Download the repository (click "Code" above, then "Download ZIP", or clone it with `git`). Then `cd` into the repository and run this:

```
python3 -m pip install .
```

It'll install into your `site-packages` or other Python binary installation folder, so you should be able to run with `bc-art`; otherwise, try `python3 -m bc_art`.

### Usage

Typically, just provide the URLs for the discographies, albums, or tracks you want to download artwork for, and `bc-art` will handle the rest. If you're working with HSMusic data, also provide `--hsmusic`, which will write to more suitable filenames.

Output is saved into the same folder you're running `bc-art` from, and placed under a folder based on the discography - for example, `homestuck` if you're downloading artworks from `https://homestuck.bandcamp.com/`.

If you'd like to customize further, see the option list below, or by running `bc-art --help`.

```
usage: bc-art [-h]
              [--hsmusic] [--no-track-nums]
              [--dry] [--quiet] [--verbose]
              [urls ...]

positional arguments:
  urls             discography, album, or track URLs to download art for

options:
  -h, --help       show this help message and exit

  --dry            dry run: don't download or write any files,
                   only print what what actions would be taken

  --overwrite      overwrite existing files instead of
                   skipping respective downloads

  --hsmusic        output directories and filenames in the format
                   hsmusic-wiki uses

  --no-track-nums  don't output track numbers in filenames
                   (default for --hsmusic)

  --quiet          don't show any logging or progress bars

  --verbose        print results as they are downloaded
```
