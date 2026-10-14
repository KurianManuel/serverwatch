from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")
    app_name: str = "ServerWatch"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: str = "/var/lib/serverwatch/serverwatch.db"
    cpu_interval: float = 5.0
    memory_interval: float = 5.0
    network_interval: float = 5.0
    disk_interval: float = 5.0
    processes_interval: float = 10.0
    temperature_interval: float = 10.0
    filesystem_interval: float = 30.0
    db_queue_size: int = 1000
    db_batch_size: int = 50
    db_flush_interval: float = 1.0
    ws_max_connections: int = 100
    ws_max_message_size: int = 65536
    ws_heartbeat_interval: float = 30.0
    retention_raw_hours: int = 24
    retention_1min_days: int = 7
    retention_5min_days: int = 30
    retention_1h_days: int = 365
    retention_1d_days: int = 730
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

settings = Settings()
