import sys
import json.decoder
from urllib.request import Request, urlopen
import urllib.error
import html.parser
import tempfile
import shutil
import io
import gzip
import codecs

from . import v1
from . import v2


try:
    JSONDecodeError = json.decoder.JSONDecodeError
except AttributeError:
    JSONDecodeError = ValueError


class LoadError(Exception):
    pass


class Parser(html.parser.HTMLParser):
    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.url = None

    def handle_starttag(self, tag, attrs_list):
        # look for <link rel="alternate" type="application/asciicast+json" href="https://...json">
        if tag == 'link':
            attrs = {}
            for k, v in attrs_list:
                attrs[k] = v

            if attrs.get('rel') == 'alternate' and attrs.get('type') == 'application/asciicast+json':
                self.url = attrs.get('href')


def open_url(url):
    if url == "-":
        return sys.stdin

    if url.startswith("ipfs:/"):
        url = "https://gateway.ipfs.io/%s" % url[6:]
    elif url.startswith("fs:/"):
        url = "https://gateway.ipfs.io/%s" % url[4:]

    if url.startswith("http:") or url.startswith("https:"):
        req = Request(url)
        req.add_header('Accept-Encoding', 'gzip')
        response = urlopen(req)
        body = response

        if response.headers['Content-Encoding'] == 'gzip':
            body = gzip.open(body)

        utf8_reader = codecs.getreader('utf-8')
        content_type = response.headers['Content-Type']

        if content_type and content_type.startswith('text/html'):
            html = utf8_reader(body, errors='replace').read()
            parser = Parser()
            parser.feed(html)
            url = parser.url

            if not url:
                raise LoadError("""<link rel="alternate" type="application/asciicast+json" href="..."> not found in fetched HTML document""")

            return open_url(url)

        return utf8_reader(body, errors='strict')

    return open(url, mode='rt', encoding='utf-8')


class open_from_url():
    FORMAT_ERROR = "only asciicast v1 and v2 formats can be opened"

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        try:
            self.file = open_url(self.url)
            first_line = self.file.readline()

            try:  # parse it as v2
                v2_header = json.loads(first_line)
                if v2_header.get('version') == 2:
                    return v2.load_from_file(v2_header, self.file)
                else:
                    raise LoadError(self.FORMAT_ERROR)
            except JSONDecodeError as e:
                try:  # parse it as v1
                    attrs = json.loads(first_line + self.file.read())
                    if attrs.get('version') == 1:
                        return v1.load_from_dict(attrs)
                    else:
                        raise LoadError(self.FORMAT_ERROR)
                except JSONDecodeError as e:
                    raise LoadError(self.FORMAT_ERROR)
        except (OSError, urllib.error.HTTPError) as e:
            raise LoadError(str(e))

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.file.close()
