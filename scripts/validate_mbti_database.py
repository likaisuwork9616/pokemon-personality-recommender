"""Compare SQL/bundled catalogs against a real indexed development database.

Read-only: never calls explanation providers or writes query text/vector to DB.
Run with python -m scripts.validate_mbti_database --output evaluation-report-mbti.json
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import text
from app.db.session import get_session_factory
from app.main import _default_engine_factory
from app.repositories.vector import VectorRepository
from app.services.mbti_provider import MbtiCatalogProvider
from app.services.evaluation import evaluate_recommendations
from scripts.evaluate_recommendations import load_cases
from app.services.csv_importer import DEFAULT_CSV_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    import torch
    torch.set_num_threads(args.threads)
    factory = get_session_factory()
    bundled, database = MbtiCatalogProvider("bundled"), MbtiCatalogProvider("database",factory)
    engine = _default_engine_factory(mbti_provider=bundled)
    dataset = Path("evaluation/recommendation_cases.jsonl")
    cases = load_cases(dataset)
    report = {"generated_at":datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "dataset_sha256":hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "seed_sha256":hashlib.sha256(DEFAULT_CSV_PATH.read_bytes()).hexdigest(),
        "model":list(engine.embedding_model_key), "cases":len(cases),
        "catalog_hash":database.catalog().content_hash,"catalog_revision":database.catalog().revision,
        "same_catalog_hash":bundled.catalog().content_hash==database.catalog().content_hash}
    reports = {}
    for source,provider in (("bundled",bundled),("database",database)):
        engine.mbti_provider = provider
        reports[source] = evaluate_recommendations(engine,cases,retrieval_k=10)
    report["metrics"] = {source:result["metrics"] for source,result in reports.items()}
    report["same_metrics"] = report["metrics"]["bundled"] == report["metrics"]["database"]
    checks = []
    variants = [("text_only","我喜歡獨自安靜思考，也會照顧朋友。",None),
        ("same_type_quiet","我喜歡獨自安靜思考，也會照顧朋友。","INFP"),
        ("same_type_social","我喜歡帶領團隊，主動與人交流並分享新點子。","INFP"),
        ("same_text_other_type","我喜歡獨自安靜思考，也會照顧朋友。","ENTJ"),
        ("conflicting_type","我喜歡獨自安靜思考，也會照顧朋友。","ESTP")]
    for label,query,mbti in variants:
        engine.mbti_provider=bundled
        first=engine.recommend(query,mbti=mbti)
        engine.mbti_provider=database
        second=engine.recommend(query,mbti=mbti)
        repeat=engine.recommend(query,mbti=mbti)
        identity=lambda rows:[row["pokedex_number"] for row in rows]
        same_scores=all(np.allclose(
            [value for value in a["scores"].values() if isinstance(value,(int,float))],
            [value for value in b["scores"].values() if isinstance(value,(int,float))]) for a,b in zip(first,second))
        checks.append({"case":label,"top3":identity(second),"names":[row["name"] for row in second],
            "same_sources":identity(first)==identity(second) and same_scores,
            "stable":identity(second)==identity(repeat),
            "top1_evidence":[{"document_id":ev["document_id"],"chunk_id":ev["chunk_id"],"content_hash":ev["content_hash"],"text":ev["text"]} for ev in second[0]["matching_evidence"]]})
    report["variants"]=checks
    with factory() as s:
        repository=VectorRepository(s)
        model=repository.active_model()
        report["coverage"]={"active_pokemon":s.execute(text("SELECT count(*) FROM pokemon WHERE is_active")).scalar(),
            "ready_pokemon":repository.ready_pokemon_count(model.id),
            "pending_or_hash_mismatch_chunks":len(repository.pending_chunks(model.id)),
            "ready_vectors":s.execute(text("SELECT count(*) FROM pokemon_chunk_embeddings WHERE status='ready' AND embedding_model_id=:id"),{"id":model.id}).scalar(),
            "migration":s.execute(text("SELECT version_num FROM alembic_version")).scalar()}
        for check in checks:
            for ev in check["top1_evidence"]:
                found=s.execute(text("SELECT content_hash FROM pokemon_knowledge_chunks WHERE id=cast(:id as uuid) AND document_id=cast(:document as uuid)"),{"id":ev["chunk_id"],"document":ev["document_id"]}).scalar()
                if found!=ev["content_hash"]: raise RuntimeError("Evidence lineage mismatch")
    report["evidence_lineage_verified"]=True
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"same_metrics":report["same_metrics"],"same_catalog_hash":report["same_catalog_hash"],
        "coverage":report["coverage"],"variants_passed":all(row["stable"] and row["same_sources"] for row in checks)},ensure_ascii=False))
    if not report["same_metrics"] or not report["same_catalog_hash"] or not all(row["same_sources"] and row["stable"] for row in checks):
        raise SystemExit(1)


if __name__=="__main__":
    main()
