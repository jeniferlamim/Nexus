"""Deterministic validators for Brazilian fiscal identifiers.

All algorithms are the public ones (Receita Federal / Manual de Orientação do Contribuinte NF-e).
"""
from __future__ import annotations

import re

_DIGITS = re.compile(r"\D")

# Códigos IBGE de UF usados na chave de acesso
UF_CODES = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}
UF_TO_CODE = {v: k for k, v in UF_CODES.items()}


def only_digits(value: str | None) -> str:
    return _DIGITS.sub("", value or "")


def is_valid_cnpj(value: str | None) -> bool:
    cnpj = only_digits(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    def dv(base: str, weights: list[int]) -> str:
        total = sum(int(d) * w for d, w in zip(base, weights))
        rest = total % 11
        return "0" if rest < 2 else str(11 - rest)

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    d1 = dv(cnpj[:12], w1)
    d2 = dv(cnpj[:12] + d1, w2)
    return cnpj[-2:] == d1 + d2


def cnpj_with_dv(base12: str) -> str:
    """Helper (used by the demo generator/tests) to build a valid CNPJ from 12 digits."""
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1

    def dv(base: str, weights: list[int]) -> str:
        rest = sum(int(d) * w for d, w in zip(base, weights)) % 11
        return "0" if rest < 2 else str(11 - rest)

    d1 = dv(base12, w1)
    return base12 + d1 + dv(base12 + d1, w2)


def access_key_dv(first43: str) -> str:
    """Módulo 11 com pesos 2..9 da direita para a esquerda (MOC NF-e)."""
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = sum(int(d) * weights[i % 8] for i, d in enumerate(reversed(first43)))
    rest = total % 11
    return "0" if rest < 2 else str(11 - rest)


def validate_access_key(key: str | None) -> list[str]:
    """Return a list of problems (empty == valid)."""
    k = only_digits(key)
    problems: list[str] = []
    if len(k) != 44:
        return [f"chave deve ter 44 dígitos (tem {len(k)})"]
    if k[:2] not in UF_CODES:
        problems.append(f"código de UF inválido na chave: {k[:2]}")
    month = int(k[4:6])
    if not 1 <= month <= 12:
        problems.append(f"mês de emissão inválido na chave: {k[4:6]}")
    if k[20:22] not in {"55", "65"}:
        problems.append(f"modelo de documento não suportado na chave: {k[20:22]}")
    if access_key_dv(k[:43]) != k[43]:
        problems.append("dígito verificador da chave não confere")
    return problems


def access_key_parts(key: str) -> dict[str, str]:
    k = only_digits(key)
    return {
        "uf": UF_CODES.get(k[:2], "?"),
        "yymm": k[2:6],
        "cnpj": k[6:20],
        "model": k[20:22],
        "series": k[22:25],
        "number": k[25:34],
    }


def build_access_key(uf: str, yymm: str, cnpj: str, model: str, series: int, number: int,
                     emission_type: int = 1, code: int = 12345678) -> str:
    base = f"{UF_TO_CODE[uf]}{yymm}{cnpj}{model}{series:03d}{number:09d}{emission_type}{code:08d}"
    return base + access_key_dv(base)


def is_valid_ncm(value: str | None) -> bool:
    n = only_digits(value)
    return len(n) == 8 and n == (value or "").replace(".", "").strip()


def is_valid_cfop(value: str | None) -> bool:
    c = only_digits(value)
    return len(c) == 4 and c[0] in "123567"


def cfop_is_inbound(cfop: str) -> bool:
    return cfop[:1] in {"1", "2", "3"}


def cfop_is_outbound(cfop: str) -> bool:
    return cfop[:1] in {"5", "6", "7"}


def expected_inbound_cfop_prefix(issuer_uf: str, recipient_uf: str, foreign: bool = False) -> str:
    """1 = operação interna, 2 = interestadual, 3 = exterior (perspectiva do destinatário)."""
    if foreign:
        return "3"
    return "1" if issuer_uf == recipient_uf else "2"


def mask_cpf(value: str) -> str:
    """LGPD: we never need an individual's full CPF for corporate tax analysis."""
    d = only_digits(value)
    if len(d) != 11:
        return d
    return f"***.{d[3:6]}.***-**"
