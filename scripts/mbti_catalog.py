"""Explicit MBTI SQL initialization or read-only integrity verification.

python -m scripts.mbti_catalog initialize
python -m scripts.mbti_catalog verify
"""
import argparse
import json
from app.db.session import get_session_factory
from app.repositories.mbti_catalog import MbtiCatalogRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("initialize", "verify"))
    args = parser.parse_args()
    with get_session_factory()() as session:
        if args.command == "verify":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
            catalog = MbtiCatalogRepository(session).load()
        else:
            with session.begin():
                catalog = MbtiCatalogRepository(session).initialize()
        print(json.dumps({"source": catalog.source, "revision": catalog.revision,
            "profiles": len(catalog.profiles), "terms": sum(len(p.weighted_terms) for p in catalog.profiles),
            "content_hash": catalog.content_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()
