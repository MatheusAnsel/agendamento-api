class AppError(Exception):
    """Erro de regra de negocio, devolvido ao cliente como JSON {detail, code}."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
