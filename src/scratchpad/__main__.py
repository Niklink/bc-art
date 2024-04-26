import bs4
import itertools
import re
import requests

from urllib.parse import urlparse

# Utilities

def iter_unique(iterable):
    seen = set()
    for element in itertools.filterfalse(seen.__contains__, iterable):
        seen.add(element)
        yield element

# Things

class Thing:
    def satisfied(self, *attr_path):
        own_attr, *rest = attr_path
        if not hasattr(self, own_attr):
            return False

        if rest:
            own_value = getattr(self, own_attr)
            for thing in own_value:
                if not thing.satisfied(*rest):
                    return False

        return True

    def filter_query(self, query):
        return [line for line in query if not self.satisfied(*line)]

class Album(Thing):
    def __init__(self):
        super().__init__()

        self.urls = []

class Track(Thing):
    def __init__(self):
        super().__init__()

        self.urls = []

# Providers

class Provider:
    def opens(self, thing):
        raise NotImplementedError

    def capabilities(self, thing):
        raise NotImplementedError

    def open(self, thing):
        raise NotImplementedError

class WebProvider(Provider):
    def opens(self, thing):
        return bool(self.select_url(thing))

    def select_url(self, thing):
        for url in thing.urls:
            if self.opens_url(url):
                return url

    def opens_url(self, url):
        raise NotImplementedError

    def open(self, thing):
        for result in self.slurp(self.fetch_page(thing)):
            r_attr, r_value = result
            r_attr = self.tidy_attr(r_attr)
            r_value = self.tidy_value(r_value)
            if r_value is not None:
                yield r_attr, r_value

    def fetch_page(self, thing):
        req = requests.get(self.select_url(thing))
        return bs4.BeautifulSoup(req.text, features="html.parser")

    def tidy_attr(self, attr):
        if isinstance(attr, str):
            return (attr,)
        return attr

    def tidy_value(self, value):
        if not value:
            return None

        if isinstance(value, bs4.Tag):
            if value.name == 'meta':
                return value['content']
            return value.text()
        return value

    def slurp(self, soup):
        raise NotImplementedError

def is_hostname_bandcamp(url):
    return urlparse(url).hostname.endswith('.bandcamp.com')

class BandcampAlbumPageProvider(WebProvider):
    def opens_url(self, url):
        o = urlparse(url)
        return (
            is_hostname_bandcamp(url) and
            re.search('^/album/.+', o.path)
        )

    def capabilities(self, track):
        return [
            (Album, 'name'),
            (Album, 'tracks', 'urls'),
            (Album, 'tracks', 'name')
        ]

    def slurp(self, soup):
        yield 'name', soup.css.select_one('meta[name=title]')

class BandcampTrackPageProvider(WebProvider):
    def opens_url(self, url):
        o = urlparse(url)
        return (
            is_hostname_bandcamp(url) and
            re.search('^/track/.+', o.path)
        )

    def capabilities(self, album):
        return [
            (Track, 'name'),
            (Track, 'duration')
        ]

bandcamp_providers = [
    BandcampAlbumPageProvider(),
    BandcampTrackPageProvider()
]

# Secretary

def capability_matches(capability, thing, *attr_path):
    c_class, c_path = capability[0], capability[1:]

    if not isinstance(thing, c_class):
        return False

    return list(attr_path) == list(c_path)

class Secretary:
    providers = bandcamp_providers

    def __init__(self, query):
        self.query = query

    def investigate(self, thing):
        return Investigation(
            self,
            thing,
            list(self.get_top_level_query(thing)))

    def get_top_level_query(self, thing):
        for query in self.query:
            q_class, q_path = query[0], query[1:]
            if isinstance(thing, q_class):
                yield q_path

    def request(self, thing, query):
        for provider in self.filter_providers(thing, query):
            provision = provider.open(thing)
            for result in provision:
                print(result)

        return False

    def filter_providers(self, thing, query):
        def any_line_matches(c):
            return any(capability_matches(c, thing, *line) for line in query)

        def any_capability_matches(p):
            return any(any_line_matches(c) for c in p.capabilities(thing))

        return (p for p in self.providers if any_capability_matches(p))

def group_query(query):
    indirect = (q for q in query if len(q) > 1)
    groups = itertools.groupby(indirect, lambda q: q[0])
    return [[key, (q[1:] for q in group)] for key, group in groups]

class Investigation:
    def __init__(self, secretary, thing, query):
        self.secretary = secretary
        self.thing = thing
        self.query = query

    def __iter__(self):
        filtered = self.thing.filter_query(self.query)
        result = self.secretary.request(self.thing, filtered)
        yield result, self.thing, list(filtered)

        for query_group in group_query(self.query):
            yield from self.subs(query_group)

    def subs(self, query_group):
        own_attr, sub_query = query_group
        if self.thing.satisfied(own_attr):
            for thing in getattr(self.thing, own_attr):
                yield from self.sub(thing, sub_query)

    def sub(self, thing, query):
        return Investigation(self.secretary, thing, query)

# Scratchpad

if __name__ == '__main__':
    album = Album()
    album.urls = ['https://erikscheele.bandcamp.com/album/one-year-older']

    track = Track()
    album.tracks = [track]

    query = [
        (Album, 'name'),
        (Album, 'tracks', 'name'),
        (Album, 'tracks', 'duration')
    ]

    sec = Secretary(query)

    inv = sec.investigate(album)

    for result in inv:
        print(result)
