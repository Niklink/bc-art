import requests

import snip.filesystem
import snip.net
from urllib.parse import urljoin

import asyncio

import os
from bs4 import BeautifulSoup as bs4

import tqdm


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
        snip.filesystem.easySlug(artist), 
        snip.filesystem.easySlug(album)
    )
    os.makedirs(out_dir, exist_ok=True)

    __, ext = os.path.splitext(image_url)

    if track_no:
        out_filename = f"{track_no} {snip.filesystem.easySlug(track_name)}{ext}"
    else:
        out_filename = f"{snip.filesystem.easySlug(track_name)}{ext}"

    # print(image_url, "->", out_dir, "as", out_filename)
    stream = snip.net.getStream(image_url)
    hash_ = hash(stream.content)
    if hash_ not in downloaded_images:
        snip.net.saveStreamAs(
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
