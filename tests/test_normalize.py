# -*- coding: utf-8 -*-
"""Testes da normalização pt-BR para narração (números/abreviações)."""
from backend.tts.normalize_ptbr import normalize as N


def test_numeros_inteiros_e_anos():
    assert N("Havia 1234 pessoas") == "Havia mil duzentos e trinta e quatro pessoas"
    assert N("em 1990") == "em mil novecentos e noventa"


def test_moeda():
    assert N("R$ 1") == "um real"
    assert N("custa R$ 45,90") == "custa quarenta e cinco reais e noventa centavos"
    assert "mil duzentos e trinta e quatro reais e cinquenta e seis centavos" in N("R$ 1.234,56")


def test_porcentagem():
    assert N("50%") == "cinquenta por cento"
    assert N("3,5%") == "três vírgula cinco por cento"


def test_ordinais():
    assert N("1º lugar") == "primeiro lugar"
    assert N("2ª vez") == "segunda vez"


def test_romanos_em_contexto():
    assert N("século XIX") == "século dezenove"
    assert N("Dom Pedro II") == "Dom Pedro segundo"
    assert N("Luís XIV") == "Luís catorze"


def test_horas():
    assert N("às 14h30") == "às catorze horas e trinta"
    assert N("chegue 9h") == "chegue nove horas"


def test_abreviacoes():
    assert N("Dr. Silva") == "Doutor Silva"
    assert N("a Dra. Souza") == "a Doutora Souza"
    assert N("pág. 42").startswith("página")
    assert N("nº 7") == "número sete"


def test_nao_pega_palavra_no():
    # "no" (n+o) NÃO pode virar "número"
    assert N("no total") == "no total"
    assert N("No século XX") == "No século vinte"


def test_temperatura_nao_vira_ordinal():
    # 30°C -> não é "trigésimo"; o "°" vira "graus" no pipeline de sanitização
    assert "trigésimo" not in N("faz 30°C")
