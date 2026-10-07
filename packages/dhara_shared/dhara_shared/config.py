"""Central settings for every DHARA service.

All services import `get_settings()` rather than reading `os.environ`
directly, so there is exactly one place that knows the names of the
environment variables documented in /.env.example and /docs/azure-requirements.md.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core ---
    environment: str = "dev"
    log_level: str = "INFO"

    # --- Postgres (Azure Database for PostgreSQL Flexible Server) ---
    database_url: str = "postgresql+psycopg://dhara_admin:changeme@localhost:5432/dhara"

    # --- Azure IoT Hub ---
    iot_hub_connection_string: Optional[str] = None            # service-policy conn string (send C2D, registry ops)
    iot_hub_eventhub_compatible_endpoint: Optional[str] = None  # built-in Event Hub-compatible endpoint for telemetry
    iot_hub_eventhub_consumer_group: str = "$Default"
    iot_hub_name: Optional[str] = None
    dps_id_scope: Optional[str] = None

    # --- Azure Storage ---
    storage_account_connection_string: Optional[str] = None
    storage_container_photos: str = "advisory-photos"
    storage_container_firmware: str = "firmware"

    # --- Azure Key Vault ---
    key_vault_uri: Optional[str] = None

    # --- Azure Communication Services ---
    acs_connection_string: Optional[str] = None
    acs_whatsapp_channel_registration_id: Optional[str] = None
    acs_sender_phone_number: Optional[str] = None

    # --- Azure OpenAI ---
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_deployment: str = "dhara-advisory-gpt"
    azure_openai_api_version: str = "2024-10-21"

    # --- Azure AI Speech ---
    speech_key: Optional[str] = None
    speech_region: Optional[str] = None

    # --- Weather / solar forecast ---
    weather_api_base: str = "https://api.open-meteo.com/v1/forecast"

    # --- Auth ---
    api_shared_secret: str = "dev-only-change-me"  # HMAC secret edge devices/services use to sign requests
    entra_tenant_id: Optional[str] = None
    entra_api_client_id: Optional[str] = None

    # --- Application Insights ---
    applicationinsights_connection_string: Optional[str] = None

    # --- Business rules (design commitments from the DHARA architecture) ---
    control_loop_interval_minutes: int = 15
    seasonal_volumetric_cap_m3_per_ha: float = 6500.0  # rule 3: tank/allocation cap per plot per season
    advisory_confidence_threshold: float = 0.72


@lru_cache
def get_settings() -> Settings:
    return Settings()
