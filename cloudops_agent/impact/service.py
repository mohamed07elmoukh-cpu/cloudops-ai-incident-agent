"""Explainable business impact, SLO, and capacity saturation calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from cloudops_agent.models import Evidence, Incident, IncidentStatus

ImpactStatus = Literal["healthy", "at_risk", "exhausted"]
ForecastMethod = Literal["observed_trend", "conservative_projection", "unavailable"]

ACTIVE_STATUSES = {
    IncidentStatus.OPEN,
    IncidentStatus.INVESTIGATING,
    IncidentStatus.REMEDIATING,
    IncidentStatus.VERIFYING,
    IncidentStatus.ESCALATED,
}


@dataclass(frozen=True)
class ServiceProfile:
    """Business context and reliability objective for one application service."""

    key: str
    name: str
    transactions_per_minute: float
    slo_target_percent: float
    window_days: int
    criticality: Literal["standard", "high", "critical"]
    resource_patterns: tuple[str, ...]


@dataclass(frozen=True)
class SaturationForecast:
    minutes: float | None
    metric: str | None
    method: ForecastMethod


@dataclass(frozen=True)
class BusinessImpactAssessment:
    service_key: str
    service_name: str
    criticality: Literal["standard", "high", "critical"]
    transactions_per_minute: float
    transactions_at_risk_per_minute: float
    slo_target_percent: float
    slo_window_days: int
    window_started_at: datetime
    assessed_at: datetime
    availability_percent: float
    error_budget_total_minutes: float
    error_budget_consumed_minutes: float
    error_budget_remaining_minutes: float
    error_budget_remaining_percent: float
    error_budget_burn_rate: float
    status: ImpactStatus
    active_incidents: int
    affected_resources: list[str]
    time_to_saturation_minutes: float | None
    saturation_metric: str | None
    saturation_method: ForecastMethod
    summary: str
    assumptions: list[str]


@dataclass(frozen=True)
class BusinessImpactOverview:
    assessed_at: datetime
    total_transactions_at_risk_per_minute: float
    services_at_risk: int
    services: list[BusinessImpactAssessment]


DEFAULT_SERVICE_PROFILES = (
    ServiceProfile(
        key="service:checkout",
        name="Commandes",
        transactions_per_minute=240.0,
        slo_target_percent=99.9,
        window_days=30,
        criticality="critical",
        resource_patterns=("checkout", "orders", "api-production"),
    ),
)


class BusinessImpactService:
    """Calculate live SLO exposure from incident history and metric evidence."""

    def __init__(self, profiles: tuple[ServiceProfile, ...] = DEFAULT_SERVICE_PROFILES) -> None:
        if not profiles:
            raise ValueError("at least one business service profile is required")
        self.profiles = profiles

    def overview(
        self, incidents: list[Incident], *, now: datetime | None = None
    ) -> BusinessImpactOverview:
        assessed_at = self._as_utc(now or datetime.now(UTC))
        services = [
            self._assess(profile, self._incidents_for(profile, incidents), assessed_at)
            for profile in self.profiles
        ]
        status_order: dict[ImpactStatus, int] = {"exhausted": 0, "at_risk": 1, "healthy": 2}
        services.sort(
            key=lambda item: (
                status_order[item.status],
                -item.transactions_at_risk_per_minute,
                item.service_name,
            )
        )
        return BusinessImpactOverview(
            assessed_at=assessed_at,
            total_transactions_at_risk_per_minute=round(
                sum(item.transactions_at_risk_per_minute for item in services), 2
            ),
            services_at_risk=sum(item.status != "healthy" for item in services),
            services=services,
        )

    def assess_incident(
        self,
        incident: Incident,
        incidents: list[Incident],
        *,
        now: datetime | None = None,
    ) -> BusinessImpactAssessment:
        assessed_at = self._as_utc(now or datetime.now(UTC))
        profile = self._profile_for(incident)
        related = self._incidents_for(profile, incidents)
        if incident not in related:
            related.append(incident)
        return self._assess(profile, related, assessed_at)

    def _assess(
        self, profile: ServiceProfile, incidents: list[Incident], now: datetime
    ) -> BusinessImpactAssessment:
        window_start = now - timedelta(days=profile.window_days)
        window_minutes = profile.window_days * 24 * 60.0
        budget_total = window_minutes * (1 - profile.slo_target_percent / 100)
        intervals = self._outage_intervals(incidents, window_start, now)
        consumed = sum((end - start).total_seconds() / 60 for start, end in intervals)
        consumed = min(consumed, window_minutes)
        remaining = max(0.0, budget_total - consumed)
        availability = max(0.0, 100 * (1 - consumed / window_minutes))
        active = [incident for incident in incidents if incident.status in ACTIVE_STATUSES]
        at_risk = profile.transactions_per_minute if active else 0.0
        forecast = self._forecast(active, now)
        status: ImpactStatus
        if remaining <= 0:
            status = "exhausted"
        elif active or remaining / budget_total < 0.5:
            status = "at_risk"
        else:
            status = "healthy"
        resources = sorted({incident.source for incident in active})
        summary = self._summary(profile, active, at_risk, remaining, forecast)
        return BusinessImpactAssessment(
            service_key=profile.key,
            service_name=profile.name,
            criticality=profile.criticality,
            transactions_per_minute=profile.transactions_per_minute,
            transactions_at_risk_per_minute=at_risk,
            slo_target_percent=profile.slo_target_percent,
            slo_window_days=profile.window_days,
            window_started_at=window_start,
            assessed_at=now,
            availability_percent=round(availability, 5),
            error_budget_total_minutes=round(budget_total, 2),
            error_budget_consumed_minutes=round(consumed, 2),
            error_budget_remaining_minutes=round(remaining, 2),
            error_budget_remaining_percent=round(
                100 * remaining / budget_total if budget_total else 0.0, 2
            ),
            error_budget_burn_rate=round(consumed / budget_total if budget_total else 0.0, 2),
            status=status,
            active_incidents=len(active),
            affected_resources=resources,
            time_to_saturation_minutes=forecast.minutes,
            saturation_metric=forecast.metric,
            saturation_method=forecast.method,
            summary=summary,
            assumptions=[
                (
                    "Les incidents corrélés qui se chevauchent comptent comme une seule "
                    "indisponibilité."
                ),
                (
                    "Le trafic exposé représente un risque potentiel, pas des transactions "
                    "perdues confirmées."
                ),
                (
                    "La projection conservatrice est utilisée lorsqu'une seule observation "
                    "est disponible."
                ),
            ],
        )

    def _profile_for(self, incident: Incident) -> ServiceProfile:
        for profile in self.profiles:
            if incident.correlation_group == profile.key or self._matches(profile, incident.source):
                return profile
        key = incident.correlation_group or f"service:{incident.source}"
        label = key.split(":", maxsplit=1)[-1].replace("-", " ").title()
        return ServiceProfile(
            key=key,
            name=label,
            transactions_per_minute=100.0,
            slo_target_percent=99.9,
            window_days=30,
            criticality="high",
            resource_patterns=(incident.source.lower(),),
        )

    def _incidents_for(self, profile: ServiceProfile, incidents: list[Incident]) -> list[Incident]:
        return [
            incident
            for incident in incidents
            if incident.correlation_group == profile.key or self._matches(profile, incident.source)
        ]

    @staticmethod
    def _matches(profile: ServiceProfile, source: str) -> bool:
        normalized = source.lower()
        return any(pattern.lower() in normalized for pattern in profile.resource_patterns)

    def _outage_intervals(
        self, incidents: list[Incident], window_start: datetime, now: datetime
    ) -> list[tuple[datetime, datetime]]:
        intervals: list[tuple[datetime, datetime]] = []
        for incident in incidents:
            detected_at = self._as_utc(incident.detected_at)
            resolved_at = self._as_utc(incident.resolved_at) if incident.resolved_at else None
            if detected_at > now or (resolved_at is not None and resolved_at <= window_start):
                continue
            start = max(detected_at, window_start)
            if resolved_at is not None:
                end = min(resolved_at, now)
            elif incident.status in ACTIVE_STATUSES:
                end = now
            else:
                evidence_times = [self._as_utc(item.timestamp) for item in incident.evidence]
                end = min(max(evidence_times, default=start), now)
            if end > start:
                intervals.append((start, end))
        intervals.sort(key=lambda item: item[0])
        merged: list[tuple[datetime, datetime]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    def _forecast(self, incidents: list[Incident], now: datetime) -> SaturationForecast:
        forecasts = [
            forecast
            for incident in incidents
            if (forecast := self._incident_forecast(incident, now)).minutes is not None
        ]
        if not forecasts:
            return SaturationForecast(None, None, "unavailable")
        return min(forecasts, key=lambda item: item.minutes or 0.0)

    def _incident_forecast(self, incident: Incident, now: datetime) -> SaturationForecast:
        if not incident.evidence:
            return SaturationForecast(None, None, "unavailable")
        grouped: dict[str, list[Evidence]] = {}
        for evidence in incident.evidence:
            grouped.setdefault(evidence.metric_name, []).append(evidence)
        metric, observations = max(
            grouped.items(),
            key=lambda item: max(self._as_utc(point.timestamp) for point in item[1]),
        )
        observations.sort(key=lambda item: self._as_utc(item.timestamp))
        recent = observations[-6:]
        latest = recent[-1]
        low_is_bad = self._low_is_bad(incident, metric, latest)
        target = 0.0 if low_is_bad else self._upper_saturation_target(metric, latest.threshold)
        rate: float | None = None
        method: ForecastMethod = "unavailable"
        if len(recent) >= 2:
            first = recent[0]
            elapsed = (
                self._as_utc(latest.timestamp) - self._as_utc(first.timestamp)
            ).total_seconds() / 60
            if elapsed > 0:
                observed_rate = (latest.metric_value - first.metric_value) / elapsed
                if (low_is_bad and observed_rate < 0) or (not low_is_bad and observed_rate > 0):
                    rate = observed_rate
                    method = "observed_trend"
        if rate is None:
            distance_beyond_threshold = abs(latest.metric_value - latest.threshold)
            reference_minutes = 30.0 if low_is_bad else 15.0
            minimum_rate = max(abs(latest.threshold) * 0.005, 0.01)
            magnitude = max(distance_beyond_threshold / reference_minutes, minimum_rate)
            rate = -magnitude if low_is_bad else magnitude
            method = "conservative_projection"
        distance = target - latest.metric_value
        if (low_is_bad and latest.metric_value <= target) or (
            not low_is_bad and latest.metric_value >= target
        ):
            minutes = 0.0
        elif rate == 0 or distance / rate < 0:
            return SaturationForecast(None, metric, "unavailable")
        else:
            minutes = min(distance / rate, 7 * 24 * 60)
        observed_age = max(0.0, (now - self._as_utc(latest.timestamp)).total_seconds() / 60)
        return SaturationForecast(round(max(0.0, minutes - observed_age), 1), metric, method)

    @staticmethod
    def _low_is_bad(incident: Incident, metric: str, evidence: Evidence) -> bool:
        raw_condition = str(evidence.raw_data.get("condition", "")).lower()
        return (
            raw_condition == "below"
            or incident.incident_type == "RDS_STORAGE_LOW"
            or "free" in metric.lower()
            or "remaining" in metric.lower()
        )

    @staticmethod
    def _upper_saturation_target(metric: str, threshold: float) -> float:
        normalized = metric.lower()
        if any(token in normalized for token in ("cpu", "utilization", "percent", "usage")):
            return 100.0
        return max(threshold * 1.25, threshold + 1.0)

    @staticmethod
    def _summary(
        profile: ServiceProfile,
        active: list[Incident],
        at_risk: float,
        remaining: float,
        forecast: SaturationForecast,
    ) -> str:
        if not active:
            return f"Aucun incident actif ne menace le service {profile.name}."
        services = sorted({incident.incident_type.split("_", maxsplit=1)[0] for incident in active})
        signal = " + ".join(services)
        message = (
            f"L'incident {signal} menace le service {profile.name} et "
            f"{at_risk:.0f} transactions/minute."
        )
        if remaining <= 0:
            message += " Le budget d'erreur SLO est épuisé."
        if forecast.minutes is not None:
            if forecast.minutes <= 0:
                message += " La saturation est atteinte ou imminente."
            else:
                message += f" Saturation estimée dans {forecast.minutes:.0f} min."
        return message

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
