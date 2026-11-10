class DsoSecretsError(Exception):
    """Erreur de base du package."""


class ConfigError(DsoSecretsError):
    pass


class AuthError(DsoSecretsError):
    pass


class NotFoundError(DsoSecretsError):
    pass


class ReadOnlyError(DsoSecretsError):
    pass


class ApiError(DsoSecretsError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
