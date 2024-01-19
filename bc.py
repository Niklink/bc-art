import asyncio
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

totalCount = 0

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
        self.hashStore = _SeenStore()
        self.urlStore = _SeenStore()

    def recordHash(self, hash):
        return self.hashStore.record(hash)

    def recordURL(self, url):
        return self.urlStore.record(url)

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

def easySlug(string):
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

def getStream(url, prev_url=None):
    """Extremely light, dumb helper to get a stream from a url

    Args:
        url (str): Remote URL
        prev_url (str, optional): Previous url, for relative resolution

    Returns:
        Requests stream
    """
    url = urljoin(prev_url, url)
    stream = requests.get(url, stream=True)
    stream.raise_for_status()
    return stream

def saveStreamAs(stream, out):
    try:
        with open(out, 'wb') as file:
            for chunk in stream:
                file.write(chunk)
    except Exception:
        # Clean up partial file
        os.unlink(out)
        raise

    global totalCount
    totalCount += 1

def getArgs():
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

def extractArtistFromURL(url):
    o = urlparse(url)
    if o.hostname.endswith(".bandcamp.com"):
        return o.hostname[0:-len(".bandcamp.com")]
    else:
        return o.hostname

async def processURL(url):
    o = urlparse(url)
    if o.path == "":
        await processDiscography(f"{url}/music")
    elif o.path == "/":
        await processDiscography(f"{url}music")
    elif o.path == "/music":
        await processDiscography(url)
    elif o.path.startswith("/album"):
        await processAlbum(url)
    elif o.path.startswith("/track"):
        await processTrack(url)
    else:
        print_tqdm(f"unrecognized URL: {url}", file=sys.stderr)

async def processDiscography(url):
    artist = extractArtistFromURL(url)
    page = bs4(requests.get(url).text, features="html.parser")
    griditems = page.findAll("li", class_="music-grid-item")
    for griditem in iter_tqdm(griditems, desc=artist, unit="album"):
        item_url = urljoin(url, griditem.find("a").get("href"))
        if "/track/" in item_url:
            await processTrack(item_url)
        else:
            await processAlbum(item_url, toplevel=False)

async def processAlbum(url, toplevel=True):
    seen = Seen() # One "seen" cache per album
    await processAlbumCover(url, seen)
    page = bs4(requests.get(url).text, features="html.parser")
    tracks = page.findAll(itemprop="tracks") + page.findAll(class_="track_row_view")
    for track in iter_tqdm(tracks, desc=url.split("/")[-1], unit="track", leave=toplevel):
        track_no = track.find(class_="track-number-col").text
        try:
            track_url = urljoin(url, track.find(class_="title").find("a").get("href"))
            await processTrack(track_url, track_no, seen=seen)
        except AttributeError as e:
            print_tqdm(e, file=sys.stderr)
            print_tqdm(url, file=sys.stderr)
            raise

def considerOverwriting(out, quiet=False):
    if overwrite:
        return True

    if os.path.isfile(out):
        if not (quiet and not verbose):
            log(f"Skip {out}, not overwriting extant file", file=sys.stderr)
        return False

    return True

async def processAlbumCover(url, seen=None):
    artist_name = extractArtistFromURL(url)
    album_name, track_name, image_url = processPage(url)
    out = getOutPath(image_url, artist_name, album_name, "Cover", 0)
    await processCoverDownload(image_url, out, seen, allow_skipping=False)

async def processTrack(url, track_no=None, seen=None):
    artist_name = extractArtistFromURL(url)
    album_name, track_name, image_url = processPage(url)
    out = getOutPath(image_url, artist_name, album_name, track_name, track_no)
    await processCoverDownload(image_url, out, seen)

def processPage(url):
    page = bs4(requests.get(url).text, features="html.parser")

    isTrack = "/track/" in url

    try:
        fromAlbum = page.find("span", class_="fromAlbum")
        title = page.find("h2", class_="trackTitle").text.strip()
        image_url = page.find("a", class_="popupImage").get("href")
    except AttributeError as e:
        print_tqdm(e, file=sys.stderr)
        print_tqdm(url, file=sys.stderr)
        raise

    if isTrack and fromAlbum:
        album_name = fromAlbum.text
        track_name = title
    elif isTrack:
        album_name = "singles"
        track_name = title
    else:
        album_name = title
        track_name = None

    return album_name, track_name, image_url

def getOutPath(image_url, artist_name, album_name, track_name, track_no):
    __, ext = os.path.splitext(image_url)
    if hsmusic and ext.lower() == '.jpeg':
        ext = '.jpg'

    artist_slug = easySlug(artist_name)
    album_slug = easySlug(album_name)
    track_slug = easySlug(track_name)

    if track_no and tracknums and not hsmusic:
        filename = f"{track_no} {track_slug}{ext}"
    else:
        filename = f"{track_slug}{ext}"

    artist = extractArtistFromURL(url)
    dir = os.path.join(artist, album_slug)
    return os.path.join(dir, filename[:247])

async def processCoverDownload(image_url, out, seen=None, allow_skipping=True):
    if allow_skipping:
        if not considerOverwriting(out):
            return

    if seen:
        seen_result = seen.recordURL(image_url)
        if allow_skipping and seen_result == 'seen':
            log(f"Skip {out}, re-used image: {image_url}")
            return

    if dry:
        log(f"{image_url} -> {out}")
        return

    stream = getStream(image_url)

    if seen:
        seen_result = seen.recordHash(hash(stream.content))
        if allow_skipping and seen_result == 'seen':
            log(f"Skip {out}, re-used hash")
            return

    if not allow_skipping:
        if not considerOverwriting(out, quiet=True):
            return

    log(f"{image_url} -> {out}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    saveStreamAs(stream, out)

if __name__ == "__main__":
    args = getArgs()
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
        asyncio.run(processURL(url))

    imageWord = "image" if totalCount == 1 else f"images"
    print(f"Done, downloaded {totalCount} {imageWord}")
