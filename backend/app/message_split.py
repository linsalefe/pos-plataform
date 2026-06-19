def split_message(text: str) -> list[str]:
    """Divide a resposta da IA em vários balões nos pontos marcados com [[quebra]].
    Sem marcador (ou resposta curta) → retorna lista de 1 item (não quebra)."""
    if not text:
        return [""]
    partes = [p.strip() for p in text.split("[[quebra]]")]
    partes = [p for p in partes if p]          # remove vazios
    return partes if partes else [text.strip()]
