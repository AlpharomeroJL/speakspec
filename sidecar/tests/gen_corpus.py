"""Generate the 20-spec Mermaid release-gate corpus (checked-in fixtures).

Each spec is a valid ``ArchitectureSpec`` for a different system type, and
deliberately seeds diagram hazards — parentheses, double quotes, reserved
words like ``end``, CJK punctuation, slashes — into component names so the
model-generated diagrams provoke the exact failure modes the repair loop
must handle.

Run once: ``python tests/gen_corpus.py`` (writes tests/fixtures/corpus/).
"""

import json
from pathlib import Path

from speakspec.schemas import ArchitectureSpec

CORPUS_DIR = Path(__file__).parent / "fixtures" / "corpus"

# name, language, domain summary, key components (with hazard bait), entities
SYSTEMS: list[tuple[str, str, str, list[str], list[str]]] = [
    (
        "chat-support-widget",
        "TypeScript",
        "embeddable customer support chat widget with canned replies",
        ["Widget (embed.js)", "Reply Router", "Agent Console"],
        ["Conversation", "Message", "Agent"],
    ),
    (
        "iot-sensor-ingest",
        "Rust",
        "MQTT ingestion service for greenhouse sensors with alert rules",
        ["MQTT Broker Bridge", 'Rule Engine "hot path"', "Alert Dispatcher"],
        ["Sensor", "Reading", "AlertRule"],
    ),
    (
        "recipe-meal-planner",
        "Python",
        "weekly meal planning with unit-aware grocery merge",
        ["Merge Engine (pint)", "Menu Calendar", "Email Reminder Job"],
        ["Recipe", "Ingredient", "MenuWeek"],
    ),
    (
        "podcast-clipper",
        "Python",
        "podcast highlight clipping with waveform UI and share pages",
        ["Clip Extractor (ffmpeg)", "Waveform Renderer", "Share Page Generator"],
        ["Episode", "Clip", "ShareLink"],
    ),
    (
        "fleet-fuel-tracker",
        "Go",
        "fuel receipt tracking for a delivery fleet with OCR import",
        ["Receipt OCR (Tesseract)", "Trip Matcher", "Fraud Flagger"],
        ["Vehicle", "Receipt", "Trip"],
    ),
    (
        "clinic-queue-board",
        "TypeScript",
        "walk-in clinic queue display with SMS notify",
        ["Check-in Kiosk", 'Queue "fast lane" Manager', "SMS Notifier (Twilio)"],
        ["Patient", "Visit", "QueueSlot"],
    ),
    (
        "warehouse-bin-audit",
        "Rust",
        "barcode-driven warehouse bin auditing with offline sync",
        ["Scanner PWA", "Sync Engine (CRDT)", "Discrepancy Reporter"],
        ["Bin", "Item", "AuditRun"],
    ),
    (
        "school-trip-permits",
        "Python",
        "digital permission slips with guardian e-sign and reminders",
        ["Form Builder", "Signature Service", "Reminder Scheduler"],
        ["Trip", "Student", "Permit"],
    ),
    (
        "game-leaderboard-api",
        "Go",
        "low-latency leaderboard API for an indie game with anti-cheat",
        ["Score Validator (HMAC)", "Ranking Store (Redis)", "Season Roller"],
        ["Player", "Score", "Season"],
    ),
    (
        "ml-feature-store",
        "Python",
        "batch feature store with point-in-time joins for churn models",
        ["Feature Registry", "Backfill Runner (Spark)", "Serving Cache"],
        ["Feature", "FeatureSet", "TrainingRun"],
    ),
    (
        "ecommerce-returns",
        "TypeScript",
        "self-serve returns portal with label generation and refunds",
        ["Return Wizard", "Label Service (EasyPost)", "Refund Orchestrator"],
        ["Order", "ReturnCase", "Label"],
    ),
    (
        "city-noise-map",
        "Python",
        "crowdsourced city noise measurements with heatmap tiles",
        ["Mobile Capture", "Tile Renderer (end-to-end)", "Calibration Service"],
        ["Measurement", "Device", "Tile"],
    ),
    (
        "legal-doc-redactor",
        "Rust",
        "on-prem PII redaction for legal PDFs with review queue",
        ["PII Detector (regex+NER)", "Redaction Renderer", "Review Queue"],
        ["Document", "Finding", "ReviewTask"],
    ),
    (
        "band-merch-store",
        "TypeScript",
        "tiny merch storefront with print-on-demand fulfillment",
        ["Catalog", "Checkout (Stripe)", "Fulfillment Webhook Handler"],
        ["Product", "MerchOrder", "Shipment"],
    ),
    (
        "hiking-trail-conditions",
        "Go",
        "trail condition reports with seasonal closures and offline maps",
        ["Report Intake", "Closure Sync (规则)", "Map Pack Builder"],
        ["Trail", "Report", "Closure"],
    ),
    (
        "invoice-late-chaser",
        "Python",
        "automated overdue invoice chasing with escalating tone",
        ["Invoice Importer (CSV/API)", "Tone Escalator", "Send Window Scheduler"],
        ["Invoice", "Chase", "Customer"],
    ),
    (
        "museum-audio-guide",
        "TypeScript",
        "QR-triggered audio guide with multilingual tracks",
        ["QR Resolver", "Track Streamer", "Visit Analytics (privacy-first)"],
        ["Exhibit", "Track", "Visit"],
    ),
    (
        "homelab-backup-orchestrator",
        "Rust",
        "scheduled encrypted backups across home servers to B2",
        ["Snapshot Agent", "Encryption Layer (age)", "Restore Verifier"],
        ["Host", "Snapshot", "RestoreTest"],
    ),
    (
        "conference-talk-voting",
        "Go",
        "CFP talk voting with conflict-of-interest blinding",
        ["Ballot Builder", "Blinding Service", "Result Tabulator"],
        ["Talk", "Vote", "Reviewer"],
    ),
    (
        "plant-watering-coach",
        "Python",
        "houseplant watering schedule coach with photo health checks",
        ["Schedule Engine", "Photo Health Scorer (CV)", "Nudge Sender"],
        ["Plant", "WateringEvent", "HealthCheck"],
    ),
]


def build_spec(
    name: str, language: str, summary: str, components: list[str], entities: list[str]
) -> dict:
    """Assemble one schema-valid ArchitectureSpec dict with hazard bait."""
    return {
        "system_overview": (
            f"{name} is a {summary}. It is built as a small focused system with "
            f"{components[0]} at its core, supported by {components[1]} and {components[2]}."
        ),
        "recommended_language": {
            "language": language,
            "confidence": "medium",
            "rationale": f"{language} fits the {summary} workload on technical grounds.",
            "overridden_by_user": False,
        },
        "quality_goals": [
            {
                "goal": "Correct output under normal failure modes",
                "driver": "core feature correctness",
            },
            {"goal": "Maintainable by one person", "driver": "solo team size"},
        ],
        "architecture_decisions": [
            {
                "title": f"Use {components[0]} as the system core",
                "chosen_option": components[0],
                "confidence": "high",
                "rationale": f"The {summary} hinges on this component working well.",
                "consequences": {
                    "positive": ["Single place to harden the critical path"],
                    "negative": ["Core component becomes a bottleneck for change"],
                },
                "ruled_out": [
                    {
                        "option": "Spreading the logic across services",
                        "rejection_reason": "Operational overhead for a small system.",
                    }
                ],
            },
            {
                "title": f"Run {components[2]} asynchronously",
                "chosen_option": f"Background processing for {components[2]}",
                "confidence": "medium",
                "rationale": "Keeps the interactive path fast on modest hardware.",
                "consequences": {
                    "positive": ["Responsive UI under load"],
                    "negative": ["Eventually-consistent side effects need messaging"],
                },
                "ruled_out": [
                    {
                        "option": "Synchronous in-request processing",
                        "rejection_reason": "Ties user latency to slow external work.",
                    }
                ],
            },
        ],
        "oss_components": [
            {
                "name": "SQLite",
                "version": "3.45",
                "purpose": "primary store",
                "why_selected": "single-node scale, zero ops",
                "do_not_build": True,
            }
        ],
        "what_not_to_build": [
            "A custom database or queue",
            "A plugin system before there are users",
        ],
        "risk_flags": [
            {
                "risk": "External dependency outage stalls the async path",
                "severity": "medium",
                "mitigation": "Retry with backoff and a dead-letter table.",
            }
        ],
        "open_questions": ["What is the realistic peak concurrent usage?"],
        "complexity": {
            "rating": "M",
            "time_estimate": "1-2 weeks to first working slice",
            "key_drivers": [f"Hardening {components[0]}", "Async orchestration"],
        },
        "constraints": [
            f"Entities {', '.join(entities)} must persist relationally",
            f"Components: {', '.join(components)}",
        ],
    }


def main() -> None:
    """Write all 20 corpus specs, validating each against the schema."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    for i, (name, language, summary, components, entities) in enumerate(SYSTEMS, start=1):
        spec = build_spec(name, language, summary, components, entities)
        ArchitectureSpec.model_validate(spec)  # corpus must itself be valid
        path = CORPUS_DIR / f"spec_{i:02d}_{name}.json"
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.name}")
    print(f"{len(SYSTEMS)} corpus specs written to {CORPUS_DIR}")


if __name__ == "__main__":
    main()
