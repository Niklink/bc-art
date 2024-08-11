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

signal.signal(signal.SIGINT, lambda x, y: sys.exit(1))

total_count = 0

try:
    from tqdm import tqdm

    def will_tqdm():
        return not config.quiet

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

class Config:
    def __init__(self):
        self.urls = []
        self.verbose = False
        self.quiet = False
        self.dry = False
        self.hsmusic = False
        self.tracknums = True
        self.overwrite = False
        self.init_arg_parser()

    def init_arg_parser(self):
        self.argument_parser = ArgumentParser()
        ap = self.argument_parser

        ap.add_argument("--dry", action="store_true",       help="dry run: don't download or write any files, only print what what actions would be taken")
        ap.add_argument("--overwrite", action="store_true", help="overwrite existing files instead of skipping respective downloads")

        ap.add_argument("--hsmusic", action="store_true",       help="output directories and filenames in the format hsmusic-wiki uses")
        ap.add_argument("--no-track-nums", action="store_true", help="don't output track numbers in filenames (default for --hsmusic)")

        ap.add_argument("--quiet", action="store_true",   help="don't show any logging or progress bars")
        ap.add_argument("--verbose", action="store_true", help="print results as they are downloaded")

        ap.add_argument("urls", nargs="*", help="discography, album, or track URLs to download art for")

    def print_help(self, *args, **kwargs):
        return self.argument_parser.print_help(*args, **kwargs)

    def parse_args(self, *args, **kwargs):
        return self.argument_parser.parse_args(*args, **kwargs)

    def load_args(self, *args, **kwargs):
        args = self.parse_args(*args, **kwargs)

        if args.dry:
            self.dry = True
        if args.overwrite:
            self.overwrite = True

        if args.verbose:
            self.verbose = True
        if args.quiet:
            self.verbose = False
            self.quiet = True

        if args.hsmusic:
            self.hsmusic = True
        if args.no_track_nums:
            self.tracknums = False

        self.urls = args.urls

config = Config()

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

def log(message, file=None):
    if file is sys.stderr:
        log = not config.quiet
    elif config.verbose:
        log = True
    elif config.dry and not config.quiet:
        log = True
    else:
        log = False

    if log:
        print_tqdm(message, file=file)

def guess_extension(content):
    ext = filetype.guess_extension(content)
    if config.hsmusic and ext == 'jpeg':
        return 'jpg'
    else:
        return ext

def normalize_name(string):
    if config.hsmusic:
        r = string

        # Spaces to dashes
        r = "-".join(r.split(" "))
        r = r.replace("&", "and")

        # Punctuation as words
        r = re.sub(r"&", "-and-", r)
        r = re.sub(r"\+", "-plus-", r)
        r = re.sub(r"%", "-percent-", r)

        # Punctuation which only divides words, not single characters
        r = re.sub(r"(\b[^\s.-]{2,})\.", r"\1-", r)
        r = re.sub(r"\.([^\s.-]{2,})\b", r"-\1", r)

        # Punctuation which doesn't divide a number following a non-number
        r = re.sub(r"(?<=[0-9])\^", "-", r)
        r = re.sub(r"\^(?![0-9])", "-", r)

        # General punctuation which always separates surrounding words
        r = re.sub(r"[/@#$%*()_=,[\]{}|\\;:<>?`~]", "-", r)

        # Accented characters
        r = re.sub(r"[áâäàå]", "a", r, flags=re.IGNORECASE)
        r = re.sub(r"[çč]", "c", r, flags=re.IGNORECASE)
        r = re.sub(r"[éêëè]", "e", r, flags=re.IGNORECASE)
        r = re.sub(r"[íîïì]", "i", r, flags=re.IGNORECASE)
        r = re.sub(r"[óôöò]", "o", r, flags=re.IGNORECASE)
        r = re.sub(r"[úûüù]", "u", r, flags=re.IGNORECASE)

        # Strip other characters
        r = re.sub(r"[^a-z0-9-]", "", r, flags=re.IGNORECASE)

        # Combine consecutive dashes
        r = re.sub(r"-{2,}", "-", r)

        # Trim dashes on boundaries
        r = re.sub(r"^-+|-+$", "", r)

        # Always lowercase
        r = r.lower()

        return r
    else:
        return re.sub(r"[\\\\/:*?\"<>|\t]|\ +$", "-", string)

def get_text(url):
    return requests.get(url).text

def get_stream(url):
    stream = requests.get(url, stream=True)
    stream.raise_for_status()
    return stream

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

    page = bs4(get_text(url), features="html.parser")
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

    page = bs4(get_text(url), features="html.parser")
    tracks = page.findAll(itemprop="tracks") + page.findAll(class_="track_row_view")

    for track in iter_tqdm(tracks, desc=url.split("/")[-1], unit="track", leave=toplevel):
        track_no = track.find(class_="track-number-col").text
        track_url = urljoin(url, track.find(class_="title").find("a").get("href"))
        await process_track(track_url, track_no, seen=seen)

def consider_overwriting(out, quiet=False):
    if config.overwrite:
        return True

    name, __ = os.path.splitext(out)
    exists = os.path.isfile(f"{name}.jpg")
    exists = exists or os.path.isfile(f"{name}.jpeg")
    exists = exists or os.path.isfile(f"{name}.png")

    if not exists:
        return True

    if (not quiet) or config.verbose:
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
    page = bs4(get_text(url), features="html.parser")
    album_span = page.find("span", class_="fromAlbum")
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
    if config.hsmusic and ext.lower() == '.jpeg':
        ext = '.jpg'

    artist_slug = normalize_name(disco_name)
    album_slug = normalize_name(album_name)
    track_slug = normalize_name(track_name) or track_no or "indeterminable-track-name"

    if track_no and config.tracknums and not config.hsmusic:
        filename = f"{track_no} {track_slug}{ext}"
    else:
        filename = f"{track_slug}{ext}"

    dir = os.path.join(disco_name, album_slug)
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

    if not config.dry:
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
            if config.dry:
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

    if config.dry:
        log(f"[dry] {image_url} -> {out}")
    else:
        log(f"{image_url} -> {out}")

def main():
    if len(sys.argv) == 1:
        config.print_help(sys.stderr)
        sys.exit(1)

    config.load_args()

    for url in config.urls:
        asyncio.run(process_url(url))

    image_word = "image" if total_count == 1 else f"images"
    verb = "would've saved" if config.dry else "saved"
    print(f"Done, {verb} {total_count} {image_word}")
