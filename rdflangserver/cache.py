from __future__ import annotations

import logging
import os
from os.path import expanduser
from pathlib import Path
from urllib.parse import quote

from rdflib import ConjunctiveGraph, Graph, URIRef  # type: ignore[import]
from rdflib.namespace import XMLNS  # type: ignore[import]
from rdflib.parser import create_input_source  # type: ignore[import]
from rdflib.util import guess_format  # type: ignore[import]

XDG_CACHE_HOME = os.environ.get('XDG_CACHE_HOME', expanduser('~/.cache'))

DEFAULT_RDF_GRAPH_CACHE_DIR = XDG_CACHE_HOME + '/rdf-graph-cache/'
RDF_GRAPH_CACHE_DIRS = [
    os.environ.get('RDF_GRAPH_CACHE', expanduser('~/.rdf-graph-cache')),
    DEFAULT_RDF_GRAPH_CACHE_DIR,
    '/usr/local/share/rdf-graph-cache/',
]

VOCAB_SOURCE_MAP = {
    "http://schema.org/": "http://schema.org/docs/schema_org_rdfa.html",
    # "http://www.w3.org/2001/XMLSchema#": "./xsd.ttl",
}


def find_rdf_graph_cache_dir() -> Path:
    for fpath in RDF_GRAPH_CACHE_DIRS:
        if os.path.isdir(fpath):
            return Path(fpath)

    default_cachedir = Path(DEFAULT_RDF_GRAPH_CACHE_DIR)
    if not default_cachedir.exists():
        default_cachedir.mkdir(exist_ok=True, parents=True)
    else:
        assert default_cachedir.is_dir()

    return default_cachedir


logger = logging.getLogger(__name__)


class GraphCache:

    cachedir: Path
    graph: ConjunctiveGraph
    mtime_map: dict[str, str]

    def __init__(self, cachedir: Path | str | None):
        self.cachedir = Path(cachedir) if cachedir else find_rdf_graph_cache_dir()
        self.graph = ConjunctiveGraph()
        self.mtime_map = {}

    def load(self, url):
        src = VOCAB_SOURCE_MAP.get(str(url), url)
        if os.path.isfile(url):
            context_id = create_input_source(url).getPublicId()
            last_vocab_mtime = self.mtime_map.get(url)
            vocab_mtime = os.stat(url).st_mtime
            if not last_vocab_mtime or last_vocab_mtime < vocab_mtime:
                logger.debug("Parse file: '%s'", url)
                self.mtime_map[url] = vocab_mtime
                # use CG as workaround for json-ld always loading as dataset
                graph = ConjunctiveGraph()
                graph.parse(src, format=guess_format(src))
                self.graph.remove_context(context_id)
                for s, p, o in graph:
                    self.graph.add((s, p, o, context_id))
                return graph
        else:
            context_id = url

        if any(self.graph.triples((None, None, None), context=context_id)):
            logger.debug("Using context <%s>", context_id)
            return self.graph.get_context(context_id)

        cache_path = self.get_fs_path(url)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            logger.debug("Load local copy of <%s> from '%s'", context_id, cache_path)
            return self.graph.parse(
                str(cache_path), format='turtle', publicID=context_id
            )
        else:
            logger.debug("Fetching <%s> to '%s'", context_id, cache_path)
            graph = self.graph.parse(
                src, format='rdfa' if url.endswith('html') else None
            )
            with cache_path.open('wb') as f:
                graph.serialize(f, format='turtle')
            return graph

    def get_fs_path(self, url: str) -> Path:
        return self.cachedir / (quote(url, safe="") + '.ttl')


class PrefixCache:

    PREFIX_URI_TEMPLATE = 'http://prefix.cc/{pfx}.file.ttl'

    def __init__(self, prefix_file):
        self._prefix_file = prefix_file
        self._pfxgraph = Graph()
        if os.path.isfile(self._prefix_file):
            self._pfxgraph.parse(str(self._prefix_file), format='turtle')

    def lookup(self, pfx):
        ns = self._pfxgraph.store.namespace(pfx)
        return ns or self._fetch_ns(pfx)

    def prefix(self, uri):
        return self._pfxgraph.store.prefix(URIRef(uri.decode('utf-8')))

    def namespaces(self):
        return self._pfxgraph.namespaces()

    def _fetch_ns(self, pfx):
        url = self.PREFIX_URI_TEMPLATE.format(pfx=pfx)
        logger.debug("Fetching <%s>", url)
        try:
            self._pfxgraph.parse(url, format='turtle')
        except:  # not found
            logger.debug("Could not read <%s>", url)

        if self._prefix_file:
            logger.debug("Saving prefixes to '%s'", self._prefix_file)
            with self._prefix_file.open('w') as f:
                for pfx, ns in self._pfxgraph.namespaces():
                    if str(ns) == str(XMLNS):
                        continue
                    print(f"@prefix {pfx}: <{ns}> .", file=f)

        return self._pfxgraph.store.namespace(pfx)
