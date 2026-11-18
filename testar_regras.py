# -*- coding: utf-8 -*-
"""
Teste automatico da regra das 6 atualizacoes (roda sem internet).
Execute:  python testar_regras.py
"""
import importlib.util
import copy

spec = importlib.util.spec_from_file_location("m3u", "atualizar_m3u.py")
m3u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m3u)


def canal(nome, cat="Teste"):
    return {"url": f"https://fotodicas.com/{nome}/", "id": nome, "nome": nome,
            "categoria": cat, "logo": "", "stream": "https://x/y.m3u8"}


def roda(estado, resultado):
    res = {resultado["id"]: resultado}
    return m3u.reconciliar(estado, res)


falhas_totais = 0


def checa(descricao, condicao):
    global falhas_totais
    print(("  OK   " if condicao else "  FALHA") + "  " + descricao)
    if not condicao:
        falhas_totais += 1


print("\n1) Canal novo que toca entra na lista")
est = {"canais": {}, "execucoes": 0}
r = canal("Novo"); r["status"] = m3u.OK
pub, novos, removidos = roda(est, r)
checa("entrou na lista", "Novo" in pub)
checa("contado como novo", novos == 1)

print("\n2) Canal que falha 5 vezes continua na lista")
est = {"canais": {}, "execucoes": 0}
r = canal("Oscilante"); r["status"] = m3u.OK
roda(est, r)
r2 = dict(r); r2["status"] = m3u.QUEBRADO
for i in range(5):
    pub, _, _ = roda(est, r2)
checa("segue publicado com 5 falhas", "Oscilante" in pub)
checa("contador igual a 5", est["canais"]["Oscilante"]["falhas"] == 5)

print("\n3) Na 6a falha o canal sai")
pub, _, removidos = roda(est, r2)
checa("saiu da lista", "Oscilante" not in pub)
checa("marcado inativo", est["canais"]["Oscilante"]["ativo"] is False)
checa("contado como removido", removidos == 1)

print("\n4) Canal que volta a tocar zera as falhas")
r3 = dict(r); r3["status"] = m3u.OK
pub, _, _ = roda(est, r3)
checa("voltou para a lista", "Oscilante" in pub)
checa("falhas zeradas", est["canais"]["Oscilante"]["falhas"] == 0)

print("\n5) Falha de rede/geo (inconclusivo) nao conta falha")
est = {"canais": {}, "execucoes": 0}
r = canal("Geo"); r["status"] = m3u.OK
roda(est, r)
r2 = dict(r); r2["status"] = m3u.INCONCLUSIVO
for i in range(8):
    pub, _, _ = roda(est, r2)
checa("continua publicado", "Geo" in pub)
checa("falhas continuam 0", est["canais"]["Geo"]["falhas"] == 0)

print("\n6) Canal que desaparece do site sai apos 6 execucoes")
est = {"canais": {}, "execucoes": 0}
r = canal("Sumido"); r["status"] = m3u.OK
roda(est, r)
for i in range(5):
    pub, _, _ = m3u.reconciliar(est, {})
checa("ainda publicado com 5 faltas", "Sumido" in pub)
pub, _, _ = m3u.reconciliar(est, {})
checa("saiu na 6a falta", "Sumido" not in pub)

print("\n7) YouTube/embed nao entram na lista")
est = {"canais": {}, "execucoes": 0}
r = canal("YT"); r["status"] = "youtube"; r["stream"] = ""
pub, _, _ = roda(est, r)
checa("fora da lista", "YT" not in pub)

print("\n" + ("TODOS OS TESTES PASSARAM" if falhas_totais == 0 else f"{falhas_totais} TESTE(S) FALHARAM"))
raise SystemExit(1 if falhas_totais else 0)
