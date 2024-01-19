import asyncio
import os
import requests

from bs4 import BeautifulSoup as bs4
from urllib.parse import urljoin

import tqdm

try:
    from snip.filesystem import easySlug
    from snip.net import getStream, saveStreamAs
except ImportError:
    print("Using local network implementation")
    import urllib.parse

    def easySlug(string, repl="-", directory=False):
        import re
        if directory:
            return re.sub(r"^\.|\.+$", "", easySlug(string, repl=repl, directory=False))
        else:
            return re.sub(r"[\\\\/:*?\"<>|\t]|\ +$", repl, string)

    def getStream(url, prev_url=None):
        """Extremely light, dumb helper to get a stream from a url

        Args:
            url (str): Remote URL
            prev_url (str, optional): Previous url, for relative resolution

        Returns:
            Requests stream
        """
        url = urllib.parse.urljoin(prev_url, url)
        stream = requests.get(url, stream=True)
        stream.raise_for_status()
        return stream

    def _saveChunked(path, response):
        """Save a binary stream to a path. Dumb.

        Args:
            path (str): 
            response (response): 
        """
        try:
            with open(path, 'wb') as file:
                for chunk in response:
                    file.write(chunk)
        except Exception:
            # Clean up partial file
            os.unlink(path)
            raise

    def saveStreamAs(stream, dest_path, nc=False, verbose=False):
        """Save a URL to a path as file

        Args:
            stream (stream): Stream
            dest_path (str): Local path

        Returns:
            bool: Success
        """
        from os import path, stat

        stream_length = float(stream.headers.get("Content-Length", -1))
        if path.isfile(dest_path):
            if nc:
                return False
            if stream_length == stat(dest_path).st_size:
                if verbose:
                    print("Not overwriting same-size file at", dest_path)
                return False
            else:
                if verbose:
                    print("File sizes do not match for output", dest_path, ":", stream_length, "!=", stat(dest_path).st_size)

        _saveChunked(dest_path, stream)
        return True


downloaded_images = []


def getArgs():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--artists", nargs="*", default=[],
                    help="Usernames")
    ap.add_argument("--albums", nargs="*", default=[],
                    help="Album URLs")
    ap.add_argument("--tracks", nargs="*", default=[],
                    help="Track URLs")
    return ap.parse_args()


async def getMetadataFromArtist(artist):
    artist_page_url = f"https://{artist}.bandcamp.com/music"
    artist_page = bs4(requests.get(artist_page_url).text, features="html.parser")
    griditems = artist_page.findAll("li", class_="music-grid-item")
    for griditem in tqdm.tqdm(griditems, desc=artist, unit="album"):
        album_url = urljoin(artist_page_url, griditem.find("a").get("href"))
        if "/track/" in album_url:
            await getMetadataFromTrack(album_url, artist=artist, album="singles")
        else:
            await getMetadataFromAlbum(album_url, artist=artist)


async def getMetadataFromAlbum(album, artist=None):
    track_page = bs4(requests.get(album).text, features="html.parser")
    tracks = track_page.findAll(itemprop="tracks") + track_page.findAll(class_="track_row_view")
    for track in tqdm.tqdm(tracks, desc=album.split("/")[-1], unit="track"):
        track_no = track.find(class_="track-number-col").text
        try:
            track_url = urljoin(album, track.find(class_="title").find("a").get("href"))
            await getMetadataFromTrack(track_url, track_no, artist=artist)
        except AttributeError:
            print("ERROR!", artist, track, track_no)
            

async def getMetadataFromTrack(track, track_no=None, album=None, artist=None):
    track_page = bs4(requests.get(track).text, features="html.parser")
    if not album:
        album = track_page.find("span", class_="fromAlbum").text

    try:
        track_name = track_page.find("h2", class_="trackTitle").text.strip()
        if not artist:
            artist = track_page.find("h3", class_="albumTitle").findAll("span")[1].text.strip()
        image_url = track_page.find("a", class_="popupImage").get("href")
    except AttributeError as e:
        print(e)
        print(track)
        raise

    out_dir = os.path.join(
        easySlug(artist), 
        easySlug(album)
    )
    os.makedirs(out_dir, exist_ok=True)

    __, ext = os.path.splitext(image_url)

    if track_no:
        out_filename = f"{track_no} {easySlug(track_name)}{ext}"
    else:
        out_filename = f"{easySlug(track_name)}{ext}"

    # print(image_url, "->", out_dir, "as", out_filename)
    stream = getStream(image_url)
    hash_ = hash(stream.content)
    if hash_ not in downloaded_images:
        saveStreamAs(
            stream,
            os.path.join(out_dir, out_filename[:247]),
            nc=True
        )
        downloaded_images.append(hash_)
    return


if __name__ == "__main__":
    args = getArgs()
    albums = args.albums
    for artist in args.artists:
        asyncio.run(getMetadataFromArtist(artist))

    for album in args.albums:
        asyncio.run(getMetadataFromAlbum(album))

    for track in args.tracks:
        asyncio.run(getMetadataFromTrack(track))
