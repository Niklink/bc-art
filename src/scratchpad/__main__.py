import itertools
import re

from bs4 import BeautifulSoup as bs4

# Utilities

def iter_unique(iterable):
    seen = set()
    for element in itertools.filterfalse(seen.__contains__, iterable):
        seen.add(element)
        yield element

# Things

class Thing:
    def satisfied(self, attr):
        return hasattr(self, attr)

class Album(Thing):
    pass

class Track(Thing):
    pass

# Provisions

class Provision:
    def __init__(self, provider, thing):
        self.provider = provider
        self.thing = thing

    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration

class WebProvision(Provision):
    def __init__(self, provider, thing):
        super().__init__(provider, thing)

        url = provider.select_url(thing)

# Providers

class Provider:
    def opens(self, thing):
        raise NotImplementedError

    def capabilities(self, thing):
        raise NotImplementedError

    def open(self, thing):
        return Provision(self, thing)

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
        return WebProvision(self, thing)

class BandcampAlbumPageProvider(WebProvider):
    def opens_url(self, url):
        o = urlparse(url)
        return (
            ro.hostname.endswith('.bandcamp.com') and
            re.search('^/album/.+', o.path)
        )

class BandcampTrackPageProvider(WebProvider):
    pass

bandcamp_providers = [
    BandcampAlbumPageProvider,
    BandcampTrackPageProvider
]

# Secretary

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

class Investigation:
    def __init__(self, secretary, thing, query):
        self.secretary = secretary
        self.thing = thing
        self.query = query

    def __iter__(self):
        self.direct_query = self.get_direct_query()
        self.indirect_query = self.get_indirect_query()
        self.query_stage = 'direct'
        return self

    def get_direct_query(self):
        query = iter(self.query)
        return iter_unique(q if len(q) == 1 else (q[0],) for q in self.query)

    def get_indirect_query(self):
        indirect = (q for q in self.query if len(q) > 1)
        groups = itertools.groupby(indirect, lambda q: q[0])
        return ((key, (q[1:] for q in group)) for key, group in groups)

    def __next__(self):
        if self.query_stage == 'direct':
            try:
                next_query = next(self.direct_query)
            except StopIteration:
                self.query_stage = 'indirect'
                return next(self)
            return self.do_direct(next_query)

        elif self.query_stage == 'indirect':
            try:
                next_query = next(self.indirect_query)
            except StopIteration:
                self.query_stage = 'done'
                raise StopIteration
            self.prepare_indirect(next_query)
            self.query_stage = 'indirect-sub'
            return next(self)

        elif self.query_stage == 'indirect-sub':
            try:
                next_investigation = next(self.sub_query)
            except StopIteration:
                self.query_stage = 'indirect'
                return self.__next__()
            self.sub_inv = iter(next_investigation)
            self.query_stage = 'indirect-sub-inv'
            return next(self)

        elif self.query_stage == 'indirect-sub-inv':
            try:
                return next(self.sub_inv)
            except StopIteration:
                self.query_stage = 'indirect-sub'
                self.sub_inv = None
                return next(self)

        else:
            raise StopIteration

    def do_direct(self, query):
        attr = query[0]

        if self.thing.satisfied(attr):
            return None, self.thing, attr

        return True, self.thing, attr

    def prepare_indirect(self, query):
        own_attr, sub_query = query

        if not self.thing.satisfied(own_attr):
            self.sub_query = iter([])
            return

        own_value = getattr(self.thing, own_attr)
        self.sub_query = (self.sub(thing, sub_query) for thing in own_value)

    def sub(self, thing, query):
        return Investigation(self.secretary, thing, query)

# Scratchpad

if __name__ == '__main__':
    album = Album()
    album.urls = ['https://erikscheele.bandcamp.com/album/one-year-older']

    track = Track()
    album.tracks = [track]

    sec = Secretary([
        (Album, 'name'),
        (Album, 'tracks', 'name')
    ])

    inv = sec.investigate(album)

    for result in inv:
        print(result)
