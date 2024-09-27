# Oh god.
from __future__ import annotations

import bs4
import itertools
import logging
import re
import requests
import sys

from dataclasses import dataclass
from typing import Any, Iterator, Self, Sequence, Type, TypeAlias, TypeVar
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Utilities

def iter_unique(iterable: Iterator[T]) -> Iterator[T]:
    seen: set[T] = set()
    for element in itertools.filterfalse(seen.__contains__, iterable):
        seen.add(element)
        yield element


# Attributes

AttributePath: TypeAlias = tuple[str, ...]
AttributeQuery: TypeAlias = Sequence[AttributePath]
T = TypeVar('T')

@dataclass
class AttributeCapability:
    thing_type: Type[Thing]
    attr_path: AttributePath

    def matches(self, thing: Thing, attr_path: AttributePath) -> bool:
        if not isinstance(thing, self.thing_type):
            return False

        return list(attr_path) == list(self.attr_path)

@dataclass
class DirectedCapability:
    thing_type: Type[Thing]
    receiving_attr_path: AttributePath
    providing_attr_path: AttributePath

# Things

class Thing:
    def satisfied(self, *attr_path: *AttributePath) -> bool:
        own_attr, *rest = attr_path
        if not hasattr(self, own_attr):
            return False

        if rest:
            own_value = getattr(self, own_attr)
            for thing in own_value:
                if not thing.satisfied(*rest):
                    return False

        return True

    def filter_query(self, query: AttributeQuery) -> AttributeQuery:
        return [line for line in query if not self.satisfied(*line)]


class Album(Thing):
    def __init__(self):
        super().__init__()

        self.urls = []
        self.tracks = []


class Track(Thing):
    def __init__(self):
        super().__init__()

        self.urls = []


# Providers

@dataclass
class ProviderResult:
    attr_path: AttributePath
    value: Any


Provision: TypeAlias = Iterator[ProviderResult]


class Provider:
    capabilities: Sequence[AttributeCapability]

    def opens(self, thing: Thing) -> bool:
        raise NotImplementedError

    def open(self, thing: Thing) -> Provision:
        raise NotImplementedError


WebProviderSlurpResult: TypeAlias = tuple[str | AttributePath, Any]


class WebProvider(Provider):
    def opens(self, thing) -> bool:
        return bool(self.select_url(thing))

    def select_url(self, thing) -> str | None:
        for url in thing.urls:
            if self.opens_url(url):
                return url
        return None

    def opens_url(self, url) -> bool:
        raise NotImplementedError

    def open(self, thing: Thing) -> Provision:
        soup = self.fetch_page(thing)
        if not soup:
            return

        for result in self.slurp(soup):
            r_attr, r_value = result
            r_attr = self.tidy_attr(r_attr)
            r_value = self.tidy_value(r_value)
            if r_value is not None:
                yield ProviderResult(r_attr, r_value)

    def fetch_page(self, thing) -> bs4.BeautifulSoup | None:
        url = self.select_url(thing)
        if not url:
            logger.debug(f"WebProvider couldn't select a url for: {thing}")
            return None

        logger.debug(f"WebProvider fetching page for thing: {thing}")

        req = requests.get(url)
        return bs4.BeautifulSoup(req.text, features="html.parser")

    def tidy_attr(self, attr) -> tuple:
        if isinstance(attr, str):
            return (attr,)
        return attr

    def tidy_value(self, value) -> str | None:
        if not value:
            return None

        if isinstance(value, bs4.Tag):
            if value.name == 'meta':
                assert isinstance(value['content'], str)
                return value['content']
            return value.get_text()
        return value

    def slurp(self, soup: bs4.BeautifulSoup) -> Iterator[WebProviderSlurpResult]:
        raise NotImplementedError


def is_hostname_bandcamp(url) -> bool:
    return urlparse(url).hostname.endswith('.bandcamp.com')


class BandcampAlbumPageProvider(WebProvider):
    capabilities = (
        AttributeCapability(Album, ('name',)),
        AttributeCapability(Album, ('tracks', 'bandcamp_track_url')),
    )

    def opens_url(self, url) -> bool:
        o = urlparse(url)
        return (
            is_hostname_bandcamp(url) and
            bool(re.search('^/album/.+', o.path))
        )

    def slurp(self, soup) -> Iterator[WebProviderSlurpResult]:
        yield 'name', soup.css.select_one('meta[name=title]')


class BandcampTrackPageProvider(WebProvider):
    capabilities = (
        AttributeCapability(Track, ('name',)),
        AttributeCapability(Track, ('duration',)),
    )

    def opens_url(self, url) -> bool:
        o = urlparse(url)
        return (
            is_hostname_bandcamp(url) and
            bool(re.search('^/track/.+', o.path))
        )

    def slurp(self, soup) -> Iterator[WebProviderSlurpResult]:
        yield 'duration', 413


bandcamp_providers = (
    BandcampAlbumPageProvider(),
    BandcampTrackPageProvider(),
)


# sentinel

class SentinelReadyResults(dict[AttributePath, Any]):
    missing = object()

    def __get__(self, key):
        try:
            return super().__get__(key)
        except KeyError:
            return SentinelReadyResults.missing


@dataclass
class SentinelResult:
    attr_path: AttributePath
    value: Any


class Sentinel:
    capabilities: Sequence[DirectedCapability]

    def receive(self, thing: Thing, results: SentinelReadyResults) -> Iterator[SentinelResult]:
        raise NotImplementedError


class ThingSentinel(Sentinel):
    capabilities = (
        DirectedCapability(Thing, ('url',), ('urls',)),
    )

    def receive(self, thing: Thing, results: SentinelReadyResults) -> Iterator[SentinelResult]:
        if hasattr(thing, 'urls'):
            try:
                url = results['url',]
            except KeyError:
                url = None

            if url and not url in thing.urls:
                thing.urls.append(url)

        yield from ()


class BandcampAlbumSentinel(Sentinel):
    capabilities = (
        DirectedCapability(
            Album,
            ('bandcamp_album_url',),
            ('url',)),

        DirectedCapability(
            Album,
            ('tracks', 'bandcamp_track_url'),
            ('tracks', 'url')),
    )

    def receive(self, thing: Thing, results: SentinelReadyResults) -> Iterator[SentinelResult]:
        assert isinstance(thing, Album)

        yield SentinelResult(
            ('url',),
            results['bandcamp_album_url',])

        yield SentinelResult(
            ('tracks', 'url'),
            results['tracks', 'bandcamp_track_url'])


hsmusic_sentinels = (
    ThingSentinel(),
    BandcampAlbumSentinel(),
)


# Secretary

@dataclass
class SecretaryQueryLine:
    thing_type: Type[Thing]
    attr_path: AttributePath


@dataclass
class Secretary:
    query: Sequence[SecretaryQueryLine]
    providers: Sequence[Provider] = bandcamp_providers
    sentinels: Sequence[Sentinel] = hsmusic_sentinels

    def investigate(self, thing: Thing) -> Investigation:
        return Investigation(
            self,
            thing,
            self.get_top_level_query(thing))

    def get_top_level_query(self, thing: Thing) -> AttributeQuery:
        return [q.attr_path for q in self.query if isinstance(thing, q.thing_type)]

    def request(self, thing: Thing, query: AttributeQuery) -> bool:
        logger.debug(f'Secretary received request: {query}')
        for provider in self.filter_providers(thing, query):
            logger.debug(f'Secretary opening provider: {provider}')
            results = self.sentinel_results_from_provision(provider.open(thing))
            logger.debug(f'Secretary got provision results: {results}')

        return False

    def filter_providers(
            self,
            thing: Thing,
            query: AttributeQuery) -> Iterator[Provider]:

        def any_line_matches(c: AttributeCapability) -> bool:
            return any(c.matches(thing, line) for line in query)

        def any_capability_matches(p: Provider) -> bool:
            return any(any_line_matches(c) for c in p.capabilities)

        return (p for p in self.providers if any_capability_matches(p))

    def sentinel_results_from_provision(self, provision: Provision) -> SentinelReadyResults:
        return SentinelReadyResults((r.attr_path, r.value) for r in provision)


def group_query(query: AttributeQuery) -> Iterator[tuple[str, AttributeQuery]]:
    indirect = (q for q in query if len(q) > 1)
    groups = itertools.groupby(indirect, lambda q: q[0])

    for key, group in groups:
        yield key, [q[1:] for q in group]


InvestigationResult: TypeAlias = tuple[bool, Thing, AttributeQuery]


@dataclass
class Investigation:
    secretary: Secretary
    thing: Thing
    query: AttributeQuery

    def __iter__(self) -> Iterator[InvestigationResult]:
        filtered = self.thing.filter_query(self.query)
        result = self.secretary.request(self.thing, filtered)
        yield result, self.thing, list(filtered)

        for query_group in group_query(self.query):
            yield from self.subs(query_group)

    def subs(self, query_group) -> Iterator[InvestigationResult]:
        own_attr, sub_query = query_group
        if self.thing.satisfied(own_attr):
            for thing in getattr(self.thing, own_attr):
                yield from self.sub(thing, sub_query)

    def sub(self, thing, query) -> Self:
        return type(self)(self.secretary, thing, query)


# Scratchpad

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    album = Album()
    album.urls = ['https://erikscheele.bandcamp.com/album/one-year-older']

    track = Track()
    album.tracks = [track]

    query = (
        SecretaryQueryLine(Album, ('name',)),
        SecretaryQueryLine(Album, ('tracks', 'name')),
        SecretaryQueryLine(Album, ('tracks', 'duration')),
    )

    sec = Secretary(query)

    inv = sec.investigate(album)

    for result in inv:
        print(result)
