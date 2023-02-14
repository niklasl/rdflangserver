from __future__ import annotations

import re
from urllib.parse import quote

from lsprotocol.types import (TEXT_DOCUMENT_COMPLETION,
                              TEXT_DOCUMENT_DEFINITION, CompletionItem,
                              CompletionList, CompletionOptions,
                              CompletionParams, DefinitionOptions,
                              LocationLink, Position, Range,
                              TypeDefinitionParams)
from pygls.server import LanguageServer

from .completer import MAX_LINE_SCAN, RdfCompleter, get_pfxns, get_pfxns_map
from .utils import get_term_at

server = LanguageServer('rdflangserver', 'v0.1')

rdfcompleter = RdfCompleter()


# trigger_characters=[':', '=', ' ']
@server.feature(TEXT_DOCUMENT_COMPLETION, CompletionOptions(resolve_provider=True))
def completions(params: CompletionParams):
    document, line, pos = _get_doc_line_and_pos(params)
    values = rdfcompleter.get_completions(
        document.lines, line, pos.character, lang=document.language_id
    )
    items = [
        CompletionItem(
            label=it.label,
            detail=it.detail,
            documentation=it.documentation,
        )
        for it in values
    ]

    return CompletionList(
        is_incomplete=False,
        items=items,
    )


@server.feature(TEXT_DOCUMENT_DEFINITION, DefinitionOptions())
def definition(params: TypeDefinitionParams):
    document, line, pos = _get_doc_line_and_pos(params)
    col = pos.character
    term = get_term_at(line, col)
    if not term:
        return

    if ':' not in term:  # OK in RDF/XML and JSON-LD (and special in RDFa)
        return

    pfx, lname = term.split(':', 1)

    ns = rdfcompleter.expand_pfx(document.lines, pfx)
    if not ns:
        return

    doc_uri = rdfcompleter.graphcache.get_fs_path(ns)

    # Find line of symbol:
    document = server.workspace.get_document(quote(doc_uri))
    prefixes: dict[str, str] = {}

    expanded_term = f"<{ns}{lname}>"
    col = -1
    for at_line, l in enumerate(document.lines):
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

    pos = Position(line=at_line, character=col)
    rng = Range(start=pos, end=pos)
    return LocationLink(
        target_uri=quote(doc_uri), target_range=rng, target_selection_range=rng
    )


def _get_doc_line_and_pos(params):
    document = server.workspace.get_document(params.text_document.uri)
    pos = params.position
    line = document.lines[pos.line].removesuffix('\n')
    return document, line, pos


def main():
    import sys

    if '-d' in sys.argv[1:]:
        server.start_tcp('127.0.0.1', 7612)
    else:
        server.start_io()


if __name__ == '__main__':
    main()
