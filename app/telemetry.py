import os

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


def configure_telemetry(app, engine) -> None:
    """Set up OpenTelemetry tracing. Exporter controlled by OTEL_EXPORTER env var.

    OTEL_EXPORTER=console  — print spans to stdout (default, dev)
    OTEL_EXPORTER=otlp     — send to OTLP endpoint (set OTEL_EXPORTER_OTLP_ENDPOINT)
    OTEL_EXPORTER=none     — disable tracing
    """
    from app.config import settings

    exporter_type = settings.otel_exporter.lower()
    if exporter_type == "none":
        return

    resource = Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME", "etanetas-address-api")}
    )
    provider = TracerProvider(resource=resource)

    if exporter_type == "otlp":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
