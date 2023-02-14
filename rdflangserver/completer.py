from __future__ import annotations

import re
from itertools import chain
from typing import Iterable, NamedTuple

from rdflib import ConjunctiveGraph
from rdflib.namespace import RDF, RDFS, split_uri  # type: ignore[import]
from rdflib.plugins.parsers.notation3 import BadSyntax

from .cache import GraphCache, PrefixCache
from .keywords import LANG_KEYWORDS
from .utils import get_term_at

MAX_LINE_SCAN = 80
MATCH_NS_DECL = re.compile(
    r'''(?:@prefix\s+|xmlns:?|vocab|prefix\s+|PREFIX\s+|")(?:@vocab|(\w*))"?[:=]\s*[<"'"](.+?)[>"']'''
)

Lines = list[str]


def get_pfxns(line: str) -> Iterable[tuple[str, str]]:
    return MATCH_NS_DECL.findall(line)


def get_pfxns_map(buffer: Lines) -> dict[str, str]:
    return {pfx: ns for line in buffer[:MAX_LINE_SCAN] for pfx, ns in get_pfxns(line)}


class Completion(NamedTuple):
    label: str
    detail: str | None = None
    documentation: str | None = None


class RdfCompleter:
    graphcache: GraphCache
    prefixes: PrefixCache

    def __init__(self, cachedir=None):
        self.graphcache = GraphCache(cachedir)
        self.prefixes = PrefixCache(self.graphcache.cachedir / 'prefixes.ttl')
        self._terms_by_ns = {}
        self._keywords = LANG_KEYWORDS

    def get_vocab_terms(self, ns):
        terms = self._terms_by_ns.get(ns)
        if terms is None and ns:
            graph = self.graphcache.load(ns)
            self._collect_vocab_terms(graph, ns)
        return self._terms_by_ns.get(ns)

    def _collect_vocab_terms(self, graph, ns):
        terms = {}
        items = set(graph.subjects(RDF.type | RDFS.isDefinedBy, None))
        for subject in items:
            try:
                uri, leaf = split_uri(subject)
                if uri == str(ns) and leaf:
                    terms[leaf] = graph.resource(subject)
            except:
                pass
        self._terms_by_ns[ns] = terms  # TODO: OrderedDict

    def get_completions(
        self, buffer: Lines, line: str, col: int, lang: str | None = None
    ) -> list[Completion]:
        term = get_term_at(line, col - 1)
        assert term is not None
        pfx, cln, trail = term.partition(':')

        prefixdecl = line.split(':')[0].strip()
        pfx_fmt = (
            '%s: <%s>'
            if prefixdecl.startswith(('PREFIX', 'prefix', '@prefix'))
            else '%s="%s"'
            if prefixdecl == 'xmlns'
            else None
        )

        results: Iterable[str]
        if pfx_fmt:
            if term.endswith(':'):
                ns = self.prefixes.lookup(term[:-1])
                results = [" <%s>" % ns] if ns else []
            else:
                results = self._get_pfx_declarations(pfx_fmt, trail)
        else:
            pfxns = get_pfxns_map(buffer)
            ns = pfxns.get(pfx)
            terms = self.get_vocab_terms(ns) or {}
            if ':' in term:
                return sorted(
                    Completion(
                        key,
                        res.value(RDF.type).qname() if res.value(RDF.type) else None,
                        res.value(RDFS.comment),
                    )
                    for key, res in terms.items()
                    if key.startswith(trail)
                )

            keywords = self._keywords.get(lang, [])
            curies = chain((pfx + ':' for pfx in sorted(pfxns)), terms, keywords)
            results = (curie for curie in curies if curie.startswith(trail))

        return [Completion(value) for value in results]

    def expand_pfx(self, buffer: Lines, pfx: str) -> str | None:
        return get_pfxns_map(buffer).get(pfx)

    def to_pfx(self, buffer: Lines, uri: str) -> str | None:
        for pfx, ns in get_pfxns_map(buffer).items():
            if ns == uri:
                return pfx
        return None

    def _get_pfx_declarations(self, pfx_fmt, base):
        return [
            pfx_fmt % (pfx, ns)
            for pfx, ns in self.prefixes.namespaces()
            if pfx.startswith(base)
        ]

    def get_term(
        self, buffer: Lines, line: str, col: int, lang: str | None = None
    ) -> tuple[str | None, str]:
        term = get_term_at(line, col)
        if not term:
            return None, ''

        if ':' not in term:  # OK in RDF/XML and JSON-LD (and special in RDFa)
            return None, ''

        pfx, lname = term.split(':', 1)
        ns = self.expand_pfx(buffer, pfx)

        return ns, lname or ''

    def find_term_definition(
        self, lines: Lines, ns: str, lname: str
    ) -> tuple[int, int]:
        prefixes: dict[str, str] = {}
        expanded_term = f"<{ns}{lname}>"
        col = -1
        for at_line, l in enumerate(lines):
            if at_line < MAX_LINE_SCAN:
                for def_pfx, def_ns in get_pfxns(l):
                    if def_ns not in prefixes:
                        prefixes[def_ns] = def_pfx

            dpfx = prefixes.get(ns)
            defterm = f"{dpfx}:{lname}" if dpfx is not None else expanded_term

            m = re.search(fr"^{re.escape(defterm)}\b", l)
            if m:
                col = 0
                break
        else:
            at_line = 0
            col = 0

        return at_line, col

    def check(self, buffer: Lines, lang: str | None = None) -> Iterable:
        if lang == 'sparql':
            return
        try:
            # TODO: io wrapper to iterate over buffer directly?
            data = ''.join(buffer)
            ConjunctiveGraph().parse(data=data, format=lang)
        except BadSyntax as e:
            lastnl = data[: e._i].rfind('\n')
            if e._i >= 0:
                col = e._i - lastnl - 1
            else:
                col = len(data)

            yield e.lines, col, e._why


if __name__ == '__main__':
    import logging

    from .cache import logger

    rootlogger = logger  # logging.getLogger()
    rootlogger.addHandler(logging.StreamHandler())
    rootlogger.setLevel(logging.DEBUG)

    import sys

    args = sys.argv[1:]
    pfx = args.pop(0) if args else 'schema'

    rdfcompleter = RdfCompleter()
    uri = rdfcompleter.prefixes.lookup(pfx)
    print("%s: %s" % (pfx, uri))
    for t in rdfcompleter.get_vocab_terms(uri):
        print("    %s" % t)
