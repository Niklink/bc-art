import asyncio
import filetype
import os
import re
import requests
import signal
import sys

from argparse import ArgumentParser
from bs4 import BeautifulSoup as bs4
from urllib.parse import urljoin, urlparse

verbose = False
quiet = False
dry = False
hsmusic = False
tracknums = True
overwrite = False

signal.signal(signal.SIGINT, lambda x, y: sys.exit(1))

total_count = 0

try:
    from tqdm import tqdm

    def will_tqdm():
        return not quiet

    def iter_tqdm(iterable, **kwargs):
        if will_tqdm():
            return tqdm(iterable, **kwargs)
        else:
            return iterable

    def print_tqdm(message, file=None):
        if will_tqdm():
            tqdm.write(message, file=file)
        else:
            print(message, file=file)

except ImportError:
    def iter_tqdm(iterable, **kwargs):
        return iterable

    def print_tqdm(message, file=None):
        print(message, file=file)

class _SeenStore:
    def __init__(self):
        self.values = []

    def record(self, value):
        if value in self.values:
            return 'seen'
        else:
            self.values.append(value)
            return 'recorded'

class Seen:
    def __init__(self):
        self.hash_store = _SeenStore()
        self.url_store = _SeenStore()

    def record_hash(self, hash):
        return self.hash_store.record(hash)

    def record_url(self, url):
        return self.url_store.record(url)

def logging():
    return (dry and not quiet) or verbose

def log(message, file=None):
    log = False

    if file is sys.stderr:
        log = not quiet
    else:
        log = verbose or (dry and not quiet)

    if not log:
        return

    print_tqdm(message, file=file)

def guess_extension(content):
    ext = filetype.guess_extension(content)
    if hsmusic and ext == 'jpeg':
        return 'jpg'
    else:
        return ext

def normalize_name(string):
    if hsmusic:
        r = string
        r = "-".join(r.split(" "))
        r = r.replace("&", "and")
        r = re.sub(r"[^a-zA-Z0-9-]", "", r)
        r = re.sub(r"-{2,}", "-", r)
        r = re.sub(r"^-+|-+$", "", r)
        r = r.lower()
        return r
    else:
        return re.sub(r"[\\\\/:*?\"<>|\t]|\ +$", "-", string)

def get_stream(url, prev_url=None):
    url = urljoin(prev_url, url)
    stream = requests.get(url, stream=True)
    stream.raise_for_status()
    return stream

def get_args():
    ap = ArgumentParser()

    ap.add_argument("--dry", action="store_true",
                    help="dry run: don't download or write any files, only print what what actions would be taken")
    ap.add_argument("--overwrite", action="store_true",
                    help="overwrite existing files instead of skipping respective downloads")
    ap.add_argument("--hsmusic", action="store_true",
                    help="output directories and filenames in the format hsmusic-wiki uses")
    ap.add_argument("--no-track-nums", action="store_true",
                    help="don't output track numbers in filenames (default for --hsmusic)")
    ap.add_argument("--quiet", action="store_true",
                    help="don't show any logging or progress bars")
    ap.add_argument("--verbose", action="store_true",
                    help="print results as they are downloaded")
    ap.add_argument("urls", nargs="*",
                    help="discography, album, or track URLs to download art for")

    if len(sys.argv) == 1:
        ap.print_help(sys.stderr)
        return None

    return ap.parse_args()

def extract_discography_from_url(url):
    o = urlparse(url)
    if o.hostname.endswith(".bandcamp.com"):
        return o.hostname[0:-len(".bandcamp.com")]
    else:
        return o.hostname

async def process_url(url):
    o = urlparse(url)
    if o.path == "":
        await process_discography(f"{url}/music")
    elif o.path == "/":
        await process_discography(f"{url}music")
    elif o.path == "/music":
        await process_discography(url)
    elif o.path.startswith("/album"):
        await process_album(url)
    elif o.path.startswith("/track"):
        await process_track(url)
    else:
        print_tqdm(f"unrecognized URL: {url}", file=sys.stderr)

async def process_discography(url):
    disco_name = extract_discography_from_url(url)

    page = bs4(requests.get(url).text, features="html.parser")
    grid_items = page.findAll("li", class_="music-grid-item")

    for griditem in iter_tqdm(grid_items, desc=disco_name, unit="album"):
        item_url = urljoin(url, griditem.find("a").get("href"))
        if "/track/" in item_url:
            await process_track(item_url)
        else:
            await process_album(item_url, toplevel=False)

async def process_album(url, toplevel=True):
    seen = Seen() # One "seen" cache per album

    await process_album_cover(url, seen)

    page = bs4(requests.get(url).text, features="html.parser")
    tracks = page.findAll(itemprop="tracks") + page.findAll(class_="track_row_view")

    for track in iter_tqdm(tracks, desc=url.split("/")[-1], unit="track", leave=toplevel):
        track_no = track.find(class_="track-number-col").text
        track_url = urljoin(url, track.find(class_="title").find("a").get("href"))
        await process_track(track_url, track_no, seen=seen)

def consider_overwriting(out, quiet=False):
    if overwrite:
        return True

    name, __ = os.path.splitext(out)
    exists = os.path.isfile(f"{name}.jpg")
    exists = exists or os.path.isfile(f"{name}.jpeg")
    exists = exists or os.path.isfile(f"{name}.png")

    if not exists:
        return True

    if not (quiet and not verbose):
        log(f"Skip {out}, not overwriting extant file", file=sys.stderr)

    return False

async def process_album_cover(url, seen=None):
    disco_name = extract_discography_from_url(url)
    album_name, track_name, image_url = process_album_track_page(url)
    out = get_out_path(image_url, disco_name, album_name, "Cover", 0)
    await process_cover_download(image_url, out, seen, allow_skipping=False)

async def process_track(url, track_no=None, seen=None):
    disco_name = extract_discography_from_url(url)
    album_name, track_name, image_url = process_album_track_page(url)
    out = get_out_path(image_url, disco_name, album_name, track_name, track_no)
    await process_cover_download(image_url, out, seen)

def process_album_track_page(url):
    page = bs4(requests.get(url).text, features="html.parser")
    album_span = page.find("span", class_="album_span")
    title = page.find("h2", class_="trackTitle").text.strip()
    image_url = page.find("a", class_="popupImage").get("href")

    is_track = "/track/" in url
    if is_track and album_span:
        album_name = album_span.text
        track_name = title
    elif is_track:
        album_name = "singles"
        track_name = title
    else:
        album_name = title
        track_name = None

    image_url = image_url.replace("_10.jpg", "_0")

    return album_name, track_name, image_url

def get_out_path(image_url, disco_name, album_name, track_name, track_no):
    __, ext = os.path.splitext(image_url)
    if hsmusic and ext.lower() == '.jpeg':
        ext = '.jpg'

    artist_slug = normalize_name(disco_name)
    album_slug = normalize_name(album_name)
    track_slug = normalize_name(track_name) or track_no or "indeterminable-track-name"

    if track_no and tracknums and not hsmusic:
        filename = f"{track_no} {track_slug}{ext}"
    else:
        filename = f"{track_slug}{ext}"

    artist = extract_discography_from_url(url)
    dir = os.path.join(artist, album_slug)
    return os.path.join(dir, filename[:247])

async def process_cover_download(image_url, out, seen=None, allow_skipping=True):
    if allow_skipping:
        if not consider_overwriting(out):
            return

    if seen:
        seen_result = seen.record_url(image_url)
        if allow_skipping and seen_result == 'seen':
            log(f"Skip {out}, re-used image: {image_url}")
            return

    stream = get_stream(image_url)

    if seen:
        seen_result = seen.record_hash(hash(stream.content))
        if allow_skipping and seen_result == 'seen':
            log(f"Skip {out}, re-used hash")
            return

    if not consider_overwriting(out, quiet=not allow_skipping):
        return

    if not dry:
        temp_dir = os.path.dirname(out)
        os.makedirs(temp_dir, exist_ok=True)

    chunks = []
    write_into_memory = True
    write_into_file = False

    for chunk in stream:
        if write_into_memory:
            chunks.append(chunk)
            content = b''.join(chunks)
            if len(content) < 40:
                continue

            write_into_memory = False
            if dry:
                break

            out += f".{guess_extension(content)}"
            out_file = open(out, 'wb')
            out_file.write(content)
            write_into_file = True
        elif write_into_file:
            out_file.write(chunk)

    if write_into_memory:
        out += f".{guess_extension(content)}"
        out_file = open(out, 'wb')
        out_file.write(content)
        out_file.close()
    elif write_into_file:
        out_file.close()

    global total_count
    total_count += 1

    if dry:
        log(f"[dry] {image_url} -> {out}")
    else:
        log(f"{image_url} -> {out}")

if __name__ == "__main__":
    args = get_args()
    if args is None:
        sys.exit(1)

    if args.dry:
        dry = True

    if args.overwrite:
        overwrite = True

    if args.verbose:
        verbose = True

    if args.quiet:
        verbose = False
        quiet = False

    if args.hsmusic:
        hsmusic = True

    if args.no_track_nums:
        tracknums = False

    for url in args.urls:
        asyncio.run(process_url(url))

    image_word = "image" if total_count == 1 else f"images"
    verb = "would've saved" if dry else "saved"
    print(f"Done, {verb} {total_count} {image_word}")
