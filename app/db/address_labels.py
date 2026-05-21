"""Shared SQL fragments for building human-readable address labels.

Used by public/addresses.py, admin/addresses.py and admin/bulk.py — import from here
so changes to the address format (new fields, abbreviation rules) stay in one place.
"""

_MUNI_SHORT = "replace(replace(m.name, ' rajono', ' raj.'), ' miesto', ' m.')"

_LOCALITY_LABEL = f"""
    CASE l.type
        WHEN 'miestas' THEN l.name
        ELSE l.name || COALESCE(' ' || l.type_abbr, '') || ', ' || ({_MUNI_SHORT})
    END
"""

_STREET_WITH_TYPE = "s.name || COALESCE(' ' || s.type_abbr, '')"

_HOUSE = "a.house_no || COALESCE(' k.' || a.corpus_no, '') || COALESCE('-' || a.flat_no, '')"

_FULL_ADDRESS = f"""
    CASE WHEN s.name IS NOT NULL
         THEN ({_STREET_WITH_TYPE}) || ' ' || ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
         ELSE ({_HOUSE}) || ', ' || ({_LOCALITY_LABEL})
    END
"""

_ADDR_JOINS = """
    LEFT JOIN streets s ON s.rc_code = a.street_code
    JOIN localities l ON l.rc_code = a.locality_code
    JOIN municipalities m ON m.rc_code = l.muni_code
"""
