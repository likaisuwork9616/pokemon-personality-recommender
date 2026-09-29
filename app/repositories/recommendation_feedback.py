"""Anonymous recommendation impression and bounded feedback persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    RecommendationFeedback,
    RecommendationImpression,
    RecommendationImpressionItem,
)


class FeedbackReceiptNotFound(ValueError):
    pass


class FeedbackItemMismatch(ValueError):
    pass


class RecommendationFeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_impression(
        self,
        *,
        recommendation_id: UUID,
        algorithm_version: str,
        ranked_pokemon: list[tuple[int, int]],
    ) -> None:
        self.session.add(
            RecommendationImpression(
                id=recommendation_id,
                algorithm_version=algorithm_version,
            )
        )
        self.session.add_all(
            [
                RecommendationImpressionItem(
                    recommendation_id=recommendation_id,
                    pokemon_id=pokemon_id,
                    rank=rank,
                )
                for rank, pokemon_id in ranked_pokemon
            ]
        )

    def upsert_feedback(
        self,
        *,
        recommendation_id: UUID,
        pokemon_id: int,
        rank: int,
        verdict: str,
        reason: str,
    ) -> bool:
        item = self.session.scalar(
            select(RecommendationImpressionItem).where(
                RecommendationImpressionItem.recommendation_id == recommendation_id,
                RecommendationImpressionItem.pokemon_id == pokemon_id,
            )
        )
        if item is None:
            receipt_exists = self.session.scalar(
                select(RecommendationImpression.id).where(
                    RecommendationImpression.id == recommendation_id
                )
            )
            if receipt_exists is None:
                raise FeedbackReceiptNotFound("找不到這次推薦紀錄。")
            raise FeedbackItemMismatch("這隻寶可夢不屬於該次推薦結果。")
        if item.rank != rank:
            raise FeedbackItemMismatch("回饋名次與原始推薦不一致。")

        feedback = self.session.get(
            RecommendationFeedback,
            {"recommendation_id": recommendation_id, "pokemon_id": pokemon_id},
        )
        created = feedback is None
        if feedback is None:
            self.session.add(
                RecommendationFeedback(
                    recommendation_id=recommendation_id,
                    pokemon_id=pokemon_id,
                    verdict=verdict,
                    reason=reason,
                )
            )
        else:
            feedback.verdict = verdict
            feedback.reason = reason
        return created

    def summary(self) -> dict[str, object]:
        positive = case((RecommendationFeedback.verdict == "match", 1), else_=0)
        total_impressions = int(
            self.session.scalar(
                select(func.count()).select_from(RecommendationImpression)
            )
            or 0
        )
        rated_impressions = int(
            self.session.scalar(
                select(func.count(distinct(RecommendationFeedback.recommendation_id)))
            )
            or 0
        )
        total_feedback, positive_feedback = self.session.execute(
            select(func.count(), func.coalesce(func.sum(positive), 0)).select_from(
                RecommendationFeedback
            )
        ).one()
        total_feedback = int(total_feedback or 0)
        positive_feedback = int(positive_feedback or 0)

        by_rank = [
            {
                "rank": int(rank),
                "feedback_count": int(count),
                "match_rate": round(int(matches) / int(count), 6),
            }
            for rank, count, matches in self.session.execute(
                select(
                    RecommendationImpressionItem.rank,
                    func.count(),
                    func.coalesce(func.sum(positive), 0),
                )
                .join(
                    RecommendationFeedback,
                    (
                        RecommendationFeedback.recommendation_id
                        == RecommendationImpressionItem.recommendation_id
                    )
                    & (
                        RecommendationFeedback.pokemon_id
                        == RecommendationImpressionItem.pokemon_id
                    ),
                )
                .group_by(RecommendationImpressionItem.rank)
                .order_by(RecommendationImpressionItem.rank)
            ).all()
        ]
        by_reason = {
            str(reason): int(count)
            for reason, count in self.session.execute(
                select(RecommendationFeedback.reason, func.count())
                .group_by(RecommendationFeedback.reason)
                .order_by(RecommendationFeedback.reason)
            ).all()
        }
        by_algorithm = [
            {
                "algorithm_version": str(version),
                "feedback_count": int(count),
                "match_rate": round(int(matches) / int(count), 6),
            }
            for version, count, matches in self.session.execute(
                select(
                    RecommendationImpression.algorithm_version,
                    func.count(),
                    func.coalesce(func.sum(positive), 0),
                )
                .join(
                    RecommendationFeedback,
                    RecommendationFeedback.recommendation_id
                    == RecommendationImpression.id,
                )
                .group_by(RecommendationImpression.algorithm_version)
                .order_by(RecommendationImpression.algorithm_version)
            ).all()
        ]
        return {
            "total_impressions": total_impressions,
            "rated_impressions": rated_impressions,
            "response_rate": (
                round(rated_impressions / total_impressions, 6)
                if total_impressions
                else 0.0
            ),
            "total_feedback": total_feedback,
            "match_rate": (
                round(positive_feedback / total_feedback, 6)
                if total_feedback
                else 0.0
            ),
            "by_rank": by_rank,
            "by_reason": by_reason,
            "by_algorithm": by_algorithm,
        }

    def purge_before(self, cutoff: datetime) -> int:
        result = self.session.execute(
            delete(RecommendationImpression).where(
                RecommendationImpression.created_at < cutoff
            )
        )
        return int(result.rowcount or 0)
