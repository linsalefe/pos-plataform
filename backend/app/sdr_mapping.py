# Mapeia o nome do SDR vindo do Exact Spotter para o id do usuario no Hub.
_RAW = {
    "Victória": 6,
    "Valéria": 4,
    "Thobias": 5,
    "Isabela": 2,   # Isa no Hub
    "Marina": 7,
    "Ana": 8,
}
EXACT_SDR_TO_USER_ID = {k.strip().casefold(): v for k, v in _RAW.items()}


def resolve_sdr_user_id(sdr_name):
    """Retorna o id do usuario do Hub para um sdr_name do Exact, ou None."""
    if not sdr_name or not isinstance(sdr_name, str):
        return None
    return EXACT_SDR_TO_USER_ID.get(sdr_name.strip().casefold())
