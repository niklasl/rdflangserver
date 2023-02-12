import re

NOT_TERM_CHAR = re.compile(r'[^:A-Za-z0-9-_]|$')


def get_term_at(line: str, i: int) -> str | None:
    """
    >>> get_term_at('some rdf:term here', 7)
    'rdf:term'
    >>> get_term_at('some rdf:term here', 12)
    'rdf:term'
    >>> get_term_at('some rdf:term here', 17)
    'here'
    >>> get_term_at('<> a bibo:Article', 16)
    'bibo:Article'
    """
    m = NOT_TERM_CHAR.search(line[i:])
    if not m:
        return None
    front = m.span()[0]

    m = NOT_TERM_CHAR.search(line[i::-1])
    if not m:
        return None
    back = m.span()[0]

    return line[i - back + 1 : i + front]


if __name__ == '__main__':
    import doctest

    doctest.testmod()
