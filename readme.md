# Bandcamp Art Downloader

### Installation

`bc.py` is the only code file you need here. You can [save it locally](https://raw.githubusercontent.com/Niklink/bc-art/master/bc.py) or download the repository.

Install dependencies:

```
python3 -m pip install requests beautifulsoup4 filetype tqdm
```

(`tqdm` is optional, but will enable nice progress bars. The other dependencies are required.)

### Usage

Typically, just pass the URLs for the discographies, albums, or tracks you want to download artwork for, and the program will handle the rest. If you're working with HSMusic data, also provide `--hsmusic`, which will write to more suitable filenames.

Output is saved into the same folder you're running the program from, and placed under a folder based on the discography - for example, `homestuck` if you're downloading artworks from `https://homestuck.bandcamp.com/`.

If you'd like to customize further, see the option list below, or by running `--help`.

```
usage: bc.py [-h]
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
